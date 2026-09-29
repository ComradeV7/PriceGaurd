"""Validation engine: runs checks and persists exceptions.

The engine builds the validation context from the repository (marks
joined with positions, instruments and reference prices). It must never
import or query the ground_truth table.
"""

from datetime import date, datetime, timezone

import pandas as pd

from priceguard.config import Config, compute_config_hash
from priceguard.db.repo import Repository, make_exception_id, make_run_id
from priceguard.validation.base import SEVERITY_ORDER, Finding
from priceguard.validation.checks import ALL_CHECKS


def build_context(
    repo: Repository,
    config: Config,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """Build the validation context panel.

    Joins marks with positions, instruments and reference prices, adds
    Level 3 model bands and per-row FX rate columns for currency checks.
    """
    context = repo.get_marks_with_references(start_date, end_date)
    if context.empty:
        return context

    l3_models = repo.query("SELECT * FROM l3_models")
    if not l3_models.empty:
        context = context.merge(
            l3_models[["instrument_id", "model_value", "band_min", "band_max"]],
            on="instrument_id",
            how="left",
        )

    fx = repo.query(
        "SELECT instrument_id, price_date, price FROM reference_prices "
        "WHERE instrument_id IN "
        "('EURUSD','GBPUSD','USDINR','USDJPY','USDCHF','AUDUSD',"
        "'USDSGD','USDCAD')"
    )
    if not fx.empty:
        pivoted = fx.pivot_table(
            index="price_date",
            columns="instrument_id",
            values="price",
            aggfunc="last",
        )
        pivoted = pivoted.rename(columns={c: f"fx_{c}" for c in pivoted.columns})
        context["mark_date"] = pd.to_datetime(context["mark_date"])
        pivoted.index = pd.to_datetime(pivoted.index)
        context = context.merge(
            pivoted, left_on="mark_date", right_index=True, how="left"
        )
    return context


def run_validation(
    repo: Repository,
    config: Config,
    config_dir,
    mark_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    checks: list | None = None,
) -> pd.DataFrame:
    """Run all registered checks and persist exceptions idempotently.

    Args:
        repo: Database repository.
        config: Loaded configuration.
        config_dir: Configuration directory (for the config hash).
        mark_date: Single date to validate; overrides start/end.
        start_date: Range start (inclusive).
        end_date: Range end (inclusive).
        checks: Optional explicit check list; defaults to ALL_CHECKS.

    Returns:
        DataFrame of exceptions written for the run.
    """
    if mark_date is not None:
        start_date, end_date = mark_date, mark_date

    context = build_context(repo, config, start_date, end_date)
    run_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    config_hash = compute_config_hash(config_dir)

    if context.empty:
        run_id = make_run_id(str(start_date), config_hash, run_ts)
        repo.insert_validation_run(run_id, str(start_date), config_hash, 0, 0)
        return pd.DataFrame()

    active_checks = checks if checks is not None else ALL_CHECKS
    findings: list[Finding] = []
    for check in active_checks:
        findings.extend(check.run(context, config))

    if not findings:
        run_id = make_run_id(str(start_date), config_hash, run_ts)
        n_positions = int(context["position_id"].nunique())
        repo.insert_validation_run(run_id, str(start_date), config_hash, n_positions, 0)
        return pd.DataFrame()

    rows = []
    for f in findings:
        exception_id = make_exception_id(
            f.mark_date.date().isoformat(), f.position_id, f.check_name
        )
        rows.append(
            {
                "exception_id": exception_id,
                "position_id": f.position_id,
                "mark_date": f.mark_date.date().isoformat(),
                "check_name": f.check_name,
                "severity": f.severity,
                "mark": f.mark,
                "reference_price": f.reference_price,
                "deviation_bps": f.deviation_bps,
                "mv_impact_usd": f.mv_impact_usd,
                "suspected_cause": f.suspected_cause,
                "opened_date": f.mark_date.date().isoformat(),
                "is_material": 1 if f.is_material else 0,
            }
        )
    exceptions = pd.DataFrame(rows)

    primary_idx = (
        exceptions.assign(sev_rank=exceptions["severity"].map(SEVERITY_ORDER).fillna(0))
        .sort_values(
            ["position_id", "mark_date", "sev_rank"],
            ascending=[True, True, False],
        )
        .groupby(["position_id", "mark_date"], as_index=False)
        .head(1)
        .index
    )
    exceptions["is_primary"] = 0
    exceptions.loc[primary_idx, "is_primary"] = 1

    run_id = make_run_id(str(start_date), config_hash, run_ts)
    n_positions = int(context["position_id"].nunique())
    repo.insert_validation_run(
        run_id, str(start_date), config_hash, n_positions, len(exceptions)
    )
    exceptions["run_id"] = run_id
    repo.upsert_exceptions(exceptions)
    return exceptions
