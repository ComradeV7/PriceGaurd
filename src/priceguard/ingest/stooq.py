"""Stooq data ingestion for equities and bond ETFs."""

import logging
from datetime import date

import pandas as pd
import requests

from priceguard.ingest.cache import ReferenceDataCache

logger = logging.getLogger(__name__)

STOOQ_CSV_URL = "https://stooq.com/q/d/l/"


def fetch_stooq_prices(
    symbol: str,
    stooq_symbol: str,
    start_date: date,
    end_date: date,
    cache: ReferenceDataCache | None = None,
    force_refresh: bool = False,
    max_retries: int = 3,
) -> pd.DataFrame:
    """Fetch daily prices from Stooq CSV endpoint.

    Args:
        symbol: Original ticker symbol
        stooq_symbol: Stooq symbol mapping (e.g., aapl.us)
        start_date: Start date for data
        end_date: End date for data
        cache: Optional cache instance
        force_refresh: If True, bypass cache
        max_retries: Number of retry attempts

    Returns:
        DataFrame with columns: symbol, price_date, price, source
        Empty DataFrame if Stooq is unavailable
    """
    if cache is not None:
        cached = cache.get("stooq", symbol, start_date, end_date, force_refresh)
        if cached is not None:
            return cached

    for attempt in range(max_retries):
        try:
            params = {
                "s": stooq_symbol,
                "d1": start_date.strftime("%Y%m%d"),
                "d2": end_date.strftime("%Y%m%d"),
                "i": "d",
            }

            response = requests.get(STOOQ_CSV_URL, params=params, timeout=30)
            response.raise_for_status()

            if "No data" in response.text or response.text.strip() == "":
                logger.warning(f"No data available from Stooq for {stooq_symbol}")
                return _empty_stooq_dataframe(symbol)

            df = pd.read_csv(pd.io.common.StringIO(response.text))

            if df.empty:
                logger.warning(f"Empty response from Stooq for {stooq_symbol}")
                return _empty_stooq_dataframe(symbol)

            result = pd.DataFrame(
                {
                    "symbol": symbol,
                    "price_date": pd.to_datetime(df["Date"]),
                    "price": df["Close"].values,
                    "source": "stooq",
                }
            )

            result = result.dropna(subset=["price"])

            if cache is not None and not result.empty:
                cache.put("stooq", symbol, start_date, end_date, result)

            return result

        except Exception as e:
            logger.warning(
                f"Stooq attempt {attempt + 1} failed for {stooq_symbol}: {e}"
            )
            if attempt == max_retries - 1:
                logger.warning(f"Stooq unavailable for {stooq_symbol}, skipping")
                return _empty_stooq_dataframe(symbol)

    return _empty_stooq_dataframe(symbol)


def _empty_stooq_dataframe(symbol: str) -> pd.DataFrame:
    """Create empty DataFrame with correct schema."""
    return pd.DataFrame(columns=["symbol", "price_date", "price", "source"])
