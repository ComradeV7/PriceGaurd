"""Foreign exchange data ingestion via Frankfurter API."""

import logging
from datetime import date

import pandas as pd
import requests
import yfinance as yf

from priceguard.ingest.cache import ReferenceDataCache

logger = logging.getLogger(__name__)

FRANKFURTER_API_URL = "https://api.frankfurter.app"

FX_PAIRS = {
    "EURUSD": {"base": "EUR", "quote": "USD"},
    "GBPUSD": {"base": "GBP", "quote": "USD"},
    "USDINR": {"base": "USD", "quote": "INR"},
    "USDJPY": {"base": "USD", "quote": "JPY"},
    "USDCHF": {"base": "USD", "quote": "CHF"},
    "AUDUSD": {"base": "AUD", "quote": "USD"},
    "USDSGD": {"base": "USD", "quote": "SGD"},
    "USDCAD": {"base": "USD", "quote": "CAD"},
}


def fetch_fx_prices(
    pair: str,
    start_date: date,
    end_date: date,
    cache: ReferenceDataCache | None = None,
    force_refresh: bool = False,
    max_retries: int = 3,
) -> pd.DataFrame:
    """Fetch FX spot prices from Frankfurter API with yfinance fallback.

    Args:
        pair: FX pair symbol (e.g., EURUSD)
        start_date: Start date for data
        end_date: End date for data
        cache: Optional cache instance
        force_refresh: If True, bypass cache
        max_retries: Number of retry attempts

    Returns:
        DataFrame with columns: symbol, price_date, price, source

    Raises:
        RuntimeError: If data cannot be fetched from any source
    """
    if cache is not None:
        cached = cache.get("fx", pair, start_date, end_date, force_refresh)
        if cached is not None:
            return cached

    if pair not in FX_PAIRS:
        raise ValueError(f"Unknown FX pair: {pair}")

    try:
        result = _fetch_from_frankfurter(pair, start_date, end_date, max_retries)
    except Exception as e:
        logger.warning(
            f"Frankfurter API failed for {pair}: {e}, trying yfinance fallback"
        )
        try:
            result = _fetch_from_yfinance(pair, start_date, end_date, max_retries)
        except Exception as e2:
            logger.error(f"Both Frankfurter and yfinance failed for {pair}")
            raise RuntimeError(f"Failed to fetch FX data for {pair}: {e2}") from e2

    if cache is not None and not result.empty:
        cache.put("fx", pair, start_date, end_date, result)

    return result


def _fetch_from_frankfurter(
    pair: str, start_date: date, end_date: date, max_retries: int
) -> pd.DataFrame:
    """Fetch FX data from Frankfurter API."""
    base = FX_PAIRS[pair]["base"]
    quote = FX_PAIRS[pair]["quote"]

    for attempt in range(max_retries):
        try:
            url = f"{FRANKFURTER_API_URL}/{start_date}..{end_date}"
            params = {"from": base, "to": quote}

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            rates = data.get("rates", {})

            if not rates:
                return _empty_fx_dataframe(pair)

            records = []
            for date_str, rate_dict in rates.items():
                if quote in rate_dict:
                    records.append(
                        {
                            "symbol": pair,
                            "price_date": pd.to_datetime(date_str),
                            "price": rate_dict[quote],
                            "source": "frankfurter",
                        }
                    )

            return pd.DataFrame(records) if records else _empty_fx_dataframe(pair)

        except Exception as e:
            logger.warning(f"Frankfurter attempt {attempt + 1} failed for {pair}: {e}")
            if attempt == max_retries - 1:
                raise

    return _empty_fx_dataframe(pair)


def _fetch_from_yfinance(
    pair: str, start_date: date, end_date: date, max_retries: int
) -> pd.DataFrame:
    """Fetch FX data from yfinance as fallback."""
    yf_symbol = f"{pair}=X"

    for attempt in range(max_retries):
        try:
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(start=start_date, end=end_date)

            if df.empty:
                return _empty_fx_dataframe(pair)

            result = pd.DataFrame(
                {
                    "symbol": pair,
                    "price_date": df.index.date,
                    "price": df["Close"].values,
                    "source": "yfinance",
                }
            )

            result["price_date"] = pd.to_datetime(result["price_date"])
            return result.dropna(subset=["price"])

        except Exception as e:
            logger.warning(f"yfinance attempt {attempt + 1} failed for {pair}: {e}")
            if attempt == max_retries - 1:
                raise

    return _empty_fx_dataframe(pair)


def fetch_all_fx_pairs(
    start_date: date,
    end_date: date,
    cache: ReferenceDataCache | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Fetch all FX pairs.

    Args:
        start_date: Start date for data
        end_date: End date for data
        cache: Optional cache instance
        force_refresh: If True, bypass cache

    Returns:
        Combined DataFrame with all FX pairs
    """
    all_data = []
    for pair in FX_PAIRS.keys():
        try:
            df = fetch_fx_prices(pair, start_date, end_date, cache, force_refresh)
            all_data.append(df)
        except Exception as e:
            logger.error(f"Failed to fetch {pair}: {e}")

    if not all_data:
        return pd.DataFrame(columns=["symbol", "price_date", "price", "source"])

    return pd.concat(all_data, ignore_index=True)


def _empty_fx_dataframe(symbol: str) -> pd.DataFrame:
    """Create empty DataFrame with correct schema."""
    return pd.DataFrame(columns=["symbol", "price_date", "price", "source"])
