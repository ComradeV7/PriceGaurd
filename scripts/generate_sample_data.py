"""Generate sample data for offline testing."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


def generate_sample_data(output_dir: Path, seed: int = 42) -> None:
    """Generate sample reference data for offline testing.

    Args:
        output_dir: Directory to write sample parquet files
        seed: Random seed for reproducibility
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    end_date = date(2024, 12, 31)
    start_date = end_date - timedelta(days=90)
    dates = pd.date_range(start_date, end_date, freq="B")

    symbols_yahoo = [
        "RELIANCE.NS", "TCS.NS", "AAPL", "MSFT", "JPM",
        "SHY", "IEF", "TLT", "LQD", "HYG", "AGG",
    ]

    for symbol in symbols_yahoo:
        base_price = rng.uniform(50, 500)
        prices = base_price * (1 + rng.normal(0, 0.02, len(dates))).cumsum()
        prices = np.maximum(prices, 1.0)

        df = pd.DataFrame({
            "symbol": symbol,
            "price_date": dates,
            "price": prices,
            "source": "yahoo",
        })
        df.to_parquet(output_dir / f"yahoo_{symbol}.parquet", index=False)

    fx_pairs = ["EURUSD", "GBPUSD", "USDINR", "USDJPY", "USDCHF"]
    fx_base_prices = {
        "EURUSD": 1.10, "GBPUSD": 1.25, "USDINR": 83.5,
        "USDJPY": 145.0, "USDCHF": 0.88,
    }

    for pair in fx_pairs:
        base_price = fx_base_prices[pair]
        prices = base_price * (1 + rng.normal(0, 0.005, len(dates))).cumsum()

        df = pd.DataFrame({
            "symbol": pair,
            "price_date": dates,
            "price": prices,
            "source": "frankfurter",
        })
        df.to_parquet(output_dir / f"fx_{pair}.parquet", index=False)

    fred_series = ["DGS2", "DGS5", "DGS10", "DGS30"]
    fred_base_yields = {"DGS2": 4.5, "DGS5": 4.2, "DGS10": 4.3, "DGS30": 4.4}

    for series in fred_series:
        base_yield = fred_base_yields[series]
        yields = base_yield + rng.normal(0, 0.1, len(dates)).cumsum()
        yields = np.clip(yields, 0.1, 10.0)

        df = pd.DataFrame({
            "symbol": series,
            "price_date": dates,
            "price": yields,
            "source": "fred",
        })
        df.to_parquet(output_dir / f"fred_{series}.parquet", index=False)


if __name__ == "__main__":
    generate_sample_data(Path("data/sample"))
    print("Sample data generated in data/sample/")
