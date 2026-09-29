"""Tests for the SQLite repository layer (in-memory)."""

import pandas as pd
import pytest

from priceguard.db.repo import Repository, make_exception_id


@pytest.fixture
def repo():
    """In-memory repository with schema applied."""
    r = Repository(":memory:")
    yield r
    r.close()


def _seed_positions(repo: Repository) -> None:
    """Insert minimal instruments and positions."""
    repo.insert_dataframe(
        "instruments",
        pd.DataFrame(
            [
                {
                    "instrument_id": "EQ1",
                    "ticker": "EQ1",
                    "name": "Test Equity",
                    "asset_class": "equity",
                    "currency": "USD",
                    "fv_level": 1,
                    "ref_source": "yahoo",
                    "is_active": 1,
                }
            ]
        ),
    )
    repo.insert_dataframe(
        "positions",
        pd.DataFrame(
            [
                {
                    "position_id": "POS-EQ1",
                    "instrument_id": "EQ1",
                    "book": "Trading-A",
                    "quantity": 1000.0,
                    "currency": "USD",
                }
            ]
        ),
    )


def test_schema_created_and_versioned(repo):
    """Schema is created and version stamped."""
    assert repo.get_schema_version() == 2
    tables = repo.query("SELECT name FROM sqlite_master WHERE type='table'")[
        "name"
    ].tolist()
    for expected in [
        "instruments",
        "positions",
        "reference_prices",
        "internal_marks",
        "ground_truth",
        "validation_runs",
        "exceptions",
        "commentary",
        "audit_log",
    ]:
        assert expected in tables


def test_schema_creation_is_idempotent(repo):
    """Running create_schema twice does not fail."""
    repo.create_schema()
    assert repo.get_schema_version() == 2


def test_bulk_insert_and_query_join(repo):
    """Marks join with positions, instruments and references."""
    _seed_positions(repo)
    repo.insert_dataframe(
        "reference_prices",
        pd.DataFrame(
            [
                {
                    "instrument_id": "EQ1",
                    "price_date": "2024-01-02",
                    "price": 100.0,
                    "source": "yahoo",
                }
            ]
        ),
    )
    repo.insert_dataframe(
        "internal_marks",
        pd.DataFrame(
            [
                {
                    "position_id": "POS-EQ1",
                    "mark_date": "2024-01-02",
                    "mark": 100.5,
                    "mark_currency": "USD",
                }
            ]
        ),
    )
    df = repo.get_marks_with_references()
    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "EQ1"
    assert df.iloc[0]["reference_price"] == 100.0
    assert df.iloc[0]["quantity"] == 1000.0


def test_exception_id_is_deterministic():
    """Same inputs give the same exception ID."""
    a = make_exception_id("2024-01-02", "POS-EQ1", "PRICE_DEVIATION")
    b = make_exception_id("2024-01-02", "POS-EQ1", "PRICE_DEVIATION")
    c = make_exception_id("2024-01-03", "POS-EQ1", "PRICE_DEVIATION")
    assert a == b
    assert a != c


def test_upsert_exceptions_idempotent(repo):
    """Re-upserting the same exception does not duplicate or reset status."""
    _seed_positions(repo)
    repo.insert_validation_run("RUN1", "2024-01-02", "hash", 1, 1)
    row = {
        "exception_id": make_exception_id("2024-01-02", "POS-EQ1", "X"),
        "run_id": "RUN1",
        "position_id": "POS-EQ1",
        "mark_date": "2024-01-02",
        "check_name": "X",
        "severity": "WARN",
        "mark": 101.0,
        "reference_price": 100.0,
        "deviation_bps": 100.0,
        "mv_impact_usd": 1000.0,
        "suspected_cause": None,
        "opened_date": "2024-01-02",
        "is_primary": 1,
        "is_material": 0,
    }
    df = pd.DataFrame([row])
    repo.upsert_exceptions(df)
    repo.conn.execute(
        "UPDATE exceptions SET status='UNDER_REVIEW' WHERE exception_id=?",
        (row["exception_id"],),
    )
    repo.conn.commit()

    repo.upsert_exceptions(df)
    stored = repo.get_exceptions("2024-01-02")
    assert len(stored) == 1
    assert stored.iloc[0]["status"] == "UNDER_REVIEW"


def test_audit_log_append(repo):
    """Audit entries are appended with timestamps."""
    repo.write_audit("tester", "TEST_ACTION", "exception", "E1", None, "{}")
    log = repo.query("SELECT * FROM audit_log")
    assert len(log) == 1
    assert log.iloc[0]["action"] == "TEST_ACTION"


def test_ground_truth_roundtrip(repo):
    """Ground truth persists and is queryable (backtest only)."""
    _seed_positions(repo)
    repo.insert_dataframe(
        "ground_truth",
        pd.DataFrame(
            [
                {
                    "position_id": "POS-EQ1",
                    "mark_date": "2024-01-02",
                    "fault_type": "STALE",
                    "fault_params_json": "{}",
                }
            ]
        ),
    )
    gt = repo.get_ground_truth()
    assert len(gt) == 1
    assert gt.iloc[0]["fault_type"] == "STALE"
