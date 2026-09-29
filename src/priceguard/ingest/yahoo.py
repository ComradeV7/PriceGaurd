"""Yahoo Finance data ingestion."""

import logging
from datetime import date

import pandas as pd
import yfinance as yf

from priceguard.ingest.cache import ReferenceDataCache

logger = logging.getLogger(__name__)


def fetch_yahoo_prices(
    symbol: str,
    start_date: date,
    end_date: date,
    cache: ReferenceDataCache | None = None,
    force_refresh: bool = False,
    max_retries: int = 3,
) -> pd.DataFrame:
    """Fetch daily adjusted close prices from Yahoo Finance.

    Args:
        symbol: Yahoo Finance ticker symbol
        start_date: Start date for data
        end_date: End date for data
        cache: Optional cache instance
        force_refresh: If True, bypass cache
        max_retries: Number of retry attempts

    Returns:
        DataFrame with columns: symbol, price_date, price, source

    Raises:
        RuntimeError: If data cannot be fetched after retries
    """
    if cache is not None:
        cached = cache.get("yahoo", symbol, start_date, end_date, force_refresh)
        if cached is not None:
            return cached

    for attempt in range(max_retries):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start_date, end=end_date, auto_adjust=False)

            if df.empty:
                logger.warning(f"No data returned for {symbol}")
                return _empty_dataframe(symbol)

            result = pd.DataFrame(
                {
                    "symbol": symbol,
                    "price_date": df.index.date,
                    "price": df["Close"].values,
                    "source": "yahoo",
                }
            )

            result = result.dropna(subset=["price"])
            result["price_date"] = pd.to_datetime(result["price_date"])

            if cache is not None and not result.empty:
                cache.put("yahoo", symbol, start_date, end_date, result)

            return result

        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed for {symbol}: {e}")
            if attempt == max_retries - 1:
                logger.error(
                    f"Failed to fetch data for {symbol} after {max_retries} attempts"
                )
                raise RuntimeError(
                    f"Failed to fetch Yahoo data for {symbol}: {e}"
                ) from e

    return _empty_dataframe(symbol)


def _empty_dataframe(symbol: str) -> pd.DataFrame:
    """Create empty DataFrame with correct schema."""
    return pd.DataFrame(columns=["symbol", "price_date", "price", "source"])
