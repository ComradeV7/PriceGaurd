"""Stable star-schema CSV exports for Power BI."""

import json
from pathlib import Path

import pandas as pd

POWERBI_SCHEMA = {
    "dim_date": {
        "date": "date",
        "year": "int",
        "month": "int",
        "week": "int",
        "is_business_day": "bool",
    },
    "dim_instrument": {
        "instrument_id": "string",
        "ticker": "string",
        "name": "string",
        "asset_class": "string",
        "fv_level": "int",
        "currency": "string",
    },
    "dim_book": {"book": "string"},
    "dim_severity": {"severity": "string", "sort_order": "int"},
    "dim_status": {"status": "string", "sort_order": "int", "is_open": "bool"},
    "fact_marks": {
        "date": "date",
        "position_id": "string",
        "mark": "float",
        "reference_price": "float",
        "deviation_bps": "float",
        "mv_usd": "float",
    },
    "fact_exceptions": {
        "exception_id": "string",
        "date": "date",
        "position_id": "string",
        "check_name": "string",
        "severity": "string",
        "status": "string",
        "deviation_bps": "float",
        "mv_impact_usd": "float",
        "opened_date": "date",
        "resolved_date": "date",
        "age_days": "int",
        "is_simulated": "bool",
    },
    "fact_backtest": {
        "fault_type": "string",
        "injected": "int",
        "detected": "int",
        "recall": "float",
    },
}


def _date_dimension(dates: pd.Series) -> pd.DataFrame:
    """Build the date dimension."""
    values = (
        pd.to_datetime(dates.dropna()).dt.normalize().drop_duplicates().sort_values()
    )
    return pd.DataFrame(
        {
            "date": values.dt.date.astype(str),
            "year": values.dt.year.astype("int64"),
            "month": values.dt.month.astype("int64"),
            "week": values.dt.isocalendar().week.astype("int64"),
            "is_business_day": (values.dt.weekday < 5).astype(bool),
        }
    )


def export_powerbi(
    repo, output_dir: str | Path, backtest_metrics: dict | None = None
) -> dict[str, Path]:
    """Write all Power BI dimensions/facts and schema.json."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    instruments = repo.query(
        "SELECT instrument_id,ticker,name,asset_class,fv_level,currency "
        "FROM instruments"
    )
    positions = repo.query("SELECT position_id,instrument_id,book FROM positions")
    marks = repo.query("SELECT position_id,mark_date,mark FROM internal_marks")
    refs = repo.query("SELECT instrument_id,price_date,price FROM reference_prices")
    exceptions = repo.query(
        "SELECT exception_id,mark_date,position_id,check_name,severity,status,"
        "deviation_bps,mv_impact_usd,opened_date,resolved_date,age_days,"
        "is_simulated FROM exceptions"
    )
    mark_context = marks.merge(positions, on="position_id", how="left").merge(
        refs.groupby(["instrument_id", "price_date"], as_index=False)["price"].mean(),
        left_on=["instrument_id", "mark_date"],
        right_on=["instrument_id", "price_date"],
        how="left",
    )
    mark_context["deviation_bps"] = (
        mark_context["mark"] / mark_context["price"] - 1
    ) * 10000
    mark_context["mv_usd"] = mark_context["deviation_bps"]
    frames = {
        "dim_date": _date_dimension(
            pd.concat([marks["mark_date"], exceptions["mark_date"]], ignore_index=True)
        ),
        "dim_instrument": instruments,
        "dim_book": positions[["book"]].drop_duplicates().sort_values("book"),
        "dim_severity": pd.DataFrame(
            {
                "severity": ["PASS", "WARN", "BREACH", "CRITICAL"],
                "sort_order": [0, 1, 2, 3],
            }
        ),
        "dim_status": pd.DataFrame(
            {
                "status": ["OPEN", "UNDER_REVIEW", "RESOLVED", "ADJUSTED", "ESCALATED"],
                "sort_order": [0, 1, 2, 3, 4],
                "is_open": [True, True, False, False, True],
            }
        ),
        "fact_marks": mark_context.rename(
            columns={"mark_date": "date", "price": "reference_price"}
        )[
            [
                "date",
                "position_id",
                "mark",
                "reference_price",
                "deviation_bps",
                "mv_usd",
            ]
        ],
        "fact_exceptions": exceptions.rename(columns={"mark_date": "date"}),
    }
    if backtest_metrics and isinstance(
        backtest_metrics.get("per_fault_type"), pd.DataFrame
    ):
        frames["fact_backtest"] = backtest_metrics["per_fault_type"].copy()
    else:
        frames["fact_backtest"] = pd.DataFrame(
            columns=list(POWERBI_SCHEMA["fact_backtest"])
        )
    paths = {}
    for name, frame in frames.items():
        path = output / f"{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = path
    schema_path = output / "schema.json"
    schema_path.write_text(
        json.dumps(POWERBI_SCHEMA, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    paths["schema"] = schema_path
    return paths
