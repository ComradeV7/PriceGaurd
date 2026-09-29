"""Tests for Excel and Power BI export schemas."""

import json

import pandas as pd

from priceguard.db.repo import Repository
from priceguard.export.excel_input import EXCEL_COLUMNS, export_daily_exceptions
from priceguard.export.powerbi import POWERBI_SCHEMA, export_powerbi
from tests.unit.test_workflow_backtest_commentary import seed_exception


def test_excel_export_columns_and_workbook(tmp_path):
    """Excel CSV/XLSX use the stable review columns."""
    with Repository(":memory:") as repo:
        seed_exception(repo)
        csv_path, xlsx_path = export_daily_exceptions(repo, tmp_path)
        frame = pd.read_csv(csv_path)
        assert list(frame.columns) == EXCEL_COLUMNS
        assert xlsx_path.exists()
        assert frame["exception_id"].notna().all()
        assert frame["status"].notna().all()


def test_powerbi_exports_have_dimensions_and_valid_foreign_keys(tmp_path):
    """Power BI facts and dimensions are emitted with stable keys."""
    with Repository(":memory:") as repo:
        seed_exception(repo)
        repo.insert_dataframe(
            "internal_marks",
            pd.DataFrame(
                [
                    {
                        "position_id": "P1",
                        "mark_date": "2024-01-02",
                        "mark": 101.0,
                        "mark_currency": "USD",
                    }
                ]
            ),
        )
        repo.insert_dataframe(
            "reference_prices",
            pd.DataFrame(
                [
                    {
                        "instrument_id": "I1",
                        "price_date": "2024-01-02",
                        "price": 100.0,
                        "source": "yahoo",
                    }
                ]
            ),
        )
        paths = export_powerbi(repo, tmp_path)
        assert set(POWERBI_SCHEMA).issubset({p.stem for p in paths.values()})
        schema = json.loads((tmp_path / "schema.json").read_text())
        assert "fact_exceptions" in schema
        fact = pd.read_csv(tmp_path / "fact_exceptions.csv")
        dim_instrument = pd.read_csv(tmp_path / "dim_instrument.csv")
        assert set(fact["position_id"]).issubset({"P1"})
        assert set(pd.read_csv(tmp_path / "dim_book.csv")["book"]) == {"Trading-A"}
        assert set(dim_instrument["instrument_id"]) == {"I1"}
