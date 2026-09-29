"""SQLite repository layer for PriceGuard.

Connection management, schema creation, bulk inserts and query helpers.
The ground_truth table is read ONLY by the backtest module; nothing in
the validation path should call ``get_ground_truth``.
"""

import hashlib
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

SCHEMA_VERSION = 2
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_exception_id(mark_date: str, position_id: str, check_name: str) -> str:
    """Deterministic exception ID: sha256(mark_date|position_id|check_name).

    Re-running validation for the same day never creates duplicates.
    """
    payload = f"{mark_date}|{position_id}|{check_name}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def make_run_id(mark_date: str, config_hash: str, run_ts: str) -> str:
    """Deterministic validation run ID."""
    payload = f"{mark_date}|{config_hash}|{run_ts}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class Repository:
    """Thin repository layer over a SQLite database."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        """Open a connection and ensure the schema exists."""
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.create_schema()

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def __enter__(self) -> "Repository":
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()

    def create_schema(self) -> None:
        """Create tables from schema.sql and stamp the schema version."""
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        self.conn.executescript(sql)
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(exceptions)")}
        if "is_simulated" not in columns:
            self.conn.execute(
                "ALTER TABLE exceptions ADD COLUMN is_simulated INTEGER NOT NULL "
                "DEFAULT 0"
            )
        self.conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_ts) VALUES (?, ?)",
            (SCHEMA_VERSION, utc_now_iso()),
        )
        self.conn.commit()

    def get_schema_version(self) -> int:
        """Return the current schema version."""
        row = self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def query(self, sql: str, params: Any = ()) -> pd.DataFrame:
        """Run a query and return a DataFrame."""
        return pd.read_sql_query(sql, self.conn, params=params)

    def insert_dataframe(self, table: str, df: pd.DataFrame) -> int:
        """Bulk insert (replace) a tidy DataFrame into a table.

        Column order is taken from the DataFrame; NaN values are
        converted to None so they persist as NULL.
        """
        if df.empty:
            return 0
        columns = list(df.columns)
        placeholders = ", ".join(["?"] * len(columns))
        col_list = ", ".join(columns)
        sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"
        rows = [
            tuple(None if pd.isna(v) else v for v in row)
            for row in df.itertuples(index=False, name=None)
        ]
        self.conn.executemany(sql, rows)
        self.conn.commit()
        return len(rows)

    def upsert_exceptions(self, df: pd.DataFrame) -> int:
        """Idempotent upsert of exceptions keyed by deterministic ID.

        Preserves workflow columns (status, resolved_date, assigned_to,
        resolution_note, opened_date) of existing rows by only updating
        the validation-derived fields.
        """
        if df.empty:
            return 0
        df = df.copy()
        if "is_simulated" not in df.columns:
            df["is_simulated"] = 0
        sql = """
        INSERT INTO exceptions (
            exception_id, run_id, position_id, mark_date, check_name,
            severity, mark, reference_price, deviation_bps, mv_impact_usd,
            suspected_cause, status, opened_date, resolved_date, age_days,
            assigned_to, resolution_note, is_primary, is_material, is_simulated
        ) VALUES (
            :exception_id, :run_id, :position_id, :mark_date, :check_name,
            :severity, :mark, :reference_price, :deviation_bps,
            :mv_impact_usd, :suspected_cause,
            'OPEN', :opened_date, NULL, 0, NULL, NULL,
            :is_primary, :is_material, :is_simulated
        )
        ON CONFLICT(exception_id) DO UPDATE SET
            run_id = excluded.run_id,
            severity = excluded.severity,
            mark = excluded.mark,
            reference_price = excluded.reference_price,
            deviation_bps = excluded.deviation_bps,
            mv_impact_usd = excluded.mv_impact_usd,
            suspected_cause = excluded.suspected_cause,
            is_primary = excluded.is_primary,
            is_material = excluded.is_material,
            is_simulated = excluded.is_simulated
        """
        records = [
            {
                k: (None if isinstance(v, float) and pd.isna(v) else v)
                for k, v in rec.items()
            }
            for rec in df.to_dict(orient="records")
        ]
        self.conn.executemany(sql, records)
        self.conn.commit()
        return len(df)

    def insert_validation_run(
        self,
        run_id: str,
        mark_date: str,
        config_hash: str,
        n_positions: int,
        n_exceptions: int,
    ) -> None:
        """Insert or replace a validation_runs row."""
        self.conn.execute(
            "INSERT OR REPLACE INTO validation_runs "
            "(run_id, run_ts, mark_date, config_hash, n_positions, "
            "n_exceptions) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, utc_now_iso(), mark_date, config_hash, n_positions, n_exceptions),
        )
        self.conn.commit()

    def write_audit(
        self,
        actor: str,
        action: str,
        entity: str,
        entity_id: str,
        before_json: str | None = None,
        after_json: str | None = None,
    ) -> None:
        """Append an entry to the audit log."""
        self.conn.execute(
            "INSERT INTO audit_log "
            "(event_ts, actor, action, entity, entity_id, before_json, "
            "after_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (utc_now_iso(), actor, action, entity, entity_id, before_json, after_json),
        )
        self.conn.commit()

    def save_commentary(
        self,
        exception_id: str,
        draft_text: str,
        provider: str,
        model_name: str | None,
        prompt_hash: str,
        facts_json: str,
        guardrail_passed: bool,
    ) -> None:
        """Persist or replace a draft commentary as ``DRAFT``."""
        self.conn.execute(
            "DELETE FROM commentary WHERE exception_id = ?", (exception_id,)
        )
        self.conn.execute(
            "INSERT INTO commentary (exception_id, draft_text, provider, model_name, "
            "prompt_hash, created_ts, facts_json, guardrail_passed, review_state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT')",
            (
                exception_id,
                draft_text,
                provider,
                model_name,
                prompt_hash,
                utc_now_iso(),
                facts_json,
                int(guardrail_passed),
            ),
        )
        self.conn.commit()

    def get_marks_with_references(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        """Marks joined with positions, instruments and reference prices.

        This is the validation context. It deliberately excludes any
        join against ground_truth.
        """
        sql = """
        SELECT
            m.position_id,
            m.mark_date,
            m.mark,
            m.mark_currency,
            p.instrument_id,
            p.book,
            p.quantity,
            p.currency AS position_currency,
            i.ticker,
            i.name,
            i.asset_class,
            i.fv_level,
            i.ref_source,
            r.price AS reference_price,
            r.source AS reference_source
        FROM internal_marks m
        JOIN positions p ON p.position_id = m.position_id
        JOIN instruments i ON i.instrument_id = p.instrument_id
        LEFT JOIN reference_prices r
            ON r.instrument_id = p.instrument_id
            AND r.price_date = m.mark_date
        """
        conditions = []
        params: list[Any] = []
        if start_date is not None:
            conditions.append("m.mark_date >= ?")
            params.append(start_date.isoformat())
        if end_date is not None:
            conditions.append("m.mark_date <= ?")
            params.append(end_date.isoformat())
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY m.mark_date, m.position_id"
        return self.query(sql, tuple(params))

    def get_ground_truth(self) -> pd.DataFrame:
        """Return the ground-truth table. BACKTEST ONLY.

        The validation engine must never call this.
        """
        return self.query("SELECT * FROM ground_truth")

    def get_exceptions(self, mark_date: str | None = None) -> pd.DataFrame:
        """Return stored exceptions, optionally filtered by mark date."""
        if mark_date is None:
            return self.query("SELECT * FROM exceptions ORDER BY mark_date")
        return self.query(
            "SELECT * FROM exceptions WHERE mark_date = ? ORDER BY position_id",
            (mark_date,),
        )
