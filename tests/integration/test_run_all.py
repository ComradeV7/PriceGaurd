"""Integration test for run-all command."""

import subprocess
import sys
from pathlib import Path


def test_run_all_offline_completes_within_60_seconds():
    """Integration test: run-all --offline completes in under 60 seconds."""
    project_root = Path(__file__).parent.parent.parent

    # Clean up any existing database
    db_path = project_root / "data" / "priceguard.db"
    if db_path.exists():
        db_path.unlink()

    # Run the command
    result = subprocess.run(
        [sys.executable, "-m", "priceguard.cli", "run-all", "--offline"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=60,
    )

    # Check exit code
    assert result.returncode == 0, f"Command failed: {result.stderr}"

    # Check output contains expected steps
    assert "Pipeline Summary" in result.stdout
    assert "ingest" in result.stdout.lower()
    assert "generate" in result.stdout.lower()
    assert "validate" in result.stdout.lower()
    assert "backtest" in result.stdout.lower()
    assert "export" in result.stdout.lower()

    # Check that exports were created
    exports_dir = project_root / "exports"
    assert exports_dir.exists(), "exports/ directory not created"

    # Check for Power BI files
    powerbi_dir = exports_dir / "powerbi"
    assert powerbi_dir.exists(), "exports/powerbi/ directory not created"

    expected_files = [
        "dim_date.csv",
        "dim_instrument.csv",
        "dim_book.csv",
        "dim_severity.csv",
        "dim_status.csv",
        "fact_marks.csv",
        "fact_exceptions.csv",
        "fact_backtest.csv",
        "schema.json",
    ]

    for filename in expected_files:
        file_path = powerbi_dir / filename
        assert file_path.exists(), f"Missing file: {filename}"
        assert file_path.stat().st_size > 0, f"Empty file: {filename}"

    # Check for Excel exports
    excel_files = list(exports_dir.glob("daily_exceptions_*.csv"))
    assert len(excel_files) > 0, "No daily_exceptions CSV files created"

    xlsx_files = list(exports_dir.glob("daily_exceptions_*.xlsx"))
    assert len(xlsx_files) > 0, "No daily_exceptions XLSX files created"

    # Check for backtest reports
    backtest_csv = exports_dir / "backtest_summary.csv"
    assert backtest_csv.exists(), "backtest_summary.csv not created"

    backtest_md = exports_dir / "backtest_report.md"
    assert backtest_md.exists(), "backtest_report.md not created"

    # Check that database was created
    assert db_path.exists(), "Database not created"


def test_run_all_with_simulate_workflow():
    """Integration test: run-all with --simulate-workflow flag."""
    project_root = Path(__file__).parent.parent.parent

    # Clean up any existing database
    db_path = project_root / "data" / "priceguard.db"
    if db_path.exists():
        db_path.unlink()

    # Run the command with simulation
    result = subprocess.run(
        [
            sys.executable, "-m", "priceguard.cli", "run-all",
            "--offline", "--simulate-workflow"
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=60,
    )

    # Check exit code
    assert result.returncode == 0, f"Command failed: {result.stderr}"

    # Check that simulation ran
    assert "simulate" in result.stdout.lower() or "simulat" in result.stdout.lower()


def test_run_all_idempotent():
    """Integration test: run-all can be run multiple times without errors."""
    project_root = Path(__file__).parent.parent.parent

    # Clean up any existing database
    db_path = project_root / "data" / "priceguard.db"
    if db_path.exists():
        db_path.unlink()

    # Run twice
    for i in range(2):
        result = subprocess.run(
            [sys.executable, "-m", "priceguard.cli", "run-all", "--offline"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"Run {i+1} failed: {result.stderr}"

    # Both runs should succeed
