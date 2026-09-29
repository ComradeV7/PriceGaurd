"""Backtest CSV and Markdown reporting."""

from pathlib import Path

import pandas as pd


def summary_frame(metrics: dict) -> pd.DataFrame:
    """Flatten headline metrics into a one-row DataFrame."""
    return pd.DataFrame(
        [
            {
                key: value
                for key, value in metrics.items()
                if not isinstance(value, pd.DataFrame)
            }
        ]
    )


def write_report(metrics: dict, output_dir: Path) -> tuple[Path, Path]:
    """Write backtest summary CSV and Markdown report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "backtest_summary.csv"
    report_path = output_dir / "backtest_report.md"
    headline = summary_frame(metrics)
    headline.to_csv(csv_path, index=False)
    per_fault = metrics.get("per_fault_type", pd.DataFrame())
    lag = metrics.get("detection_lag", pd.DataFrame())
    lines = [
        "# PriceGuard Backtest",
        "",
        "Results are based on synthetic injected faults, not real-world performance.",
        "",
        "## Headline Metrics",
        "",
        headline.to_string(index=False),
        "",
        "## Recall by Fault Type",
        "",
        per_fault.to_string(index=False) if not per_fault.empty else "No fault rows.",
        "",
        "## Detection Lag",
        "",
        lag.to_string(index=False) if not lag.empty else "No STALE/DRIFT rows.",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, report_path
