"""FRED data ingestion for Treasury yields."""

import logging
import os
from datetime import date

import pandas as pd
import requests

from priceguard.ingest.cache import ReferenceDataCache

logger = logging.getLogger(__name__)

FRED_SERIES = {
    "DGS2": "2-Year Treasury Yield",
    "DGS5": "5-Year Treasury Yield",
    "DGS10": "10-Year Treasury Yield",
    "DGS30": "30-Year Treasury Yield",
}

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def fetch_fred_series(
    series_id: str,
    start_date: date,
    end_date: date,
    cache: ReferenceDataCache | None = None,
    force_refresh: bool = False,
    max_retries: int = 3,
) -> pd.DataFrame:
    """Fetch a single FRED series from CSV endpoint.

    Args:
        series_id: FRED series identifier (e.g., DGS2, DGS10)
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
        cached = cache.get("fred", series_id, start_date, end_date, force_refresh)
        if cached is not None:
            return cached

    api_key = os.environ.get("FRED_API_KEY")

    for attempt in range(max_retries):
        try:
            params = {
                "bgcolor": "e1e9f0",
                "chart_type": "line",
                "drp": "0",
                "fo": "open%20price",
                "fgst": "",
                "log": "",
                "mode": "",
                "recession_bars": "on",
                "txt_color": "000000",
                "ts": "12",
                "tts": "12",
                "width": "1168",
                "height": "525",
                "ntb": "ntb",
                "ntbs": "ntbs",
                "chrth": "",
                "id": series_id,
                "cosd": start_date.strftime("%Y-%m-%d"),
                "coed": end_date.strftime("%Y-%m-%d"),
                "line_color": "4572a7",
                "line_style": "solid",
                "lw": "2",
                "scale": "left",
                "qcu": "qcu",
                "fml": "a",
                "fq": "Daily",
                "fac": "avg",
                "vintage_date": "",
                "revision_date": "",
                "nd": "",
            }

            if api_key:
                params["api_key"] = api_key

            response = requests.get(FRED_CSV_URL, params=params, timeout=30)
            response.raise_for_status()

            df = pd.read_csv(pd.io.common.StringIO(response.text))

            if df.empty:
                logger.warning(f"No data returned for {series_id}")
                return _empty_fred_dataframe(series_id)

            df.columns = ["DATE", "value"]
            df["DATE"] = pd.to_datetime(df["DATE"])
            df = df[df["value"] != "."]
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df = df.dropna(subset=["value"])

            result = pd.DataFrame(
                {
                    "symbol": series_id,
                    "price_date": df["DATE"],
                    "price": df["value"],
                    "source": "fred",
                }
            )

            if cache is not None and not result.empty:
                cache.put("fred", series_id, start_date, end_date, result)

            return result

        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed for {series_id}: {e}")
            if attempt == max_retries - 1:
                logger.error(
                    f"Failed to fetch FRED data for {series_id} "
                    f"after {max_retries} attempts"
                )
                raise RuntimeError(
                    f"Failed to fetch FRED data for {series_id}: {e}"
                ) from e

    return _empty_fred_dataframe(series_id)


def fetch_all_fred_series(
    start_date: date,
    end_date: date,
    cache: ReferenceDataCache | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Fetch all FRED Treasury yield series.

    Args:
        start_date: Start date for data
        end_date: End date for data
        cache: Optional cache instance
        force_refresh: If True, bypass cache

    Returns:
        Combined DataFrame with all FRED series
    """
    all_data = []
    for series_id in FRED_SERIES.keys():
        try:
            df = fetch_fred_series(
                series_id, start_date, end_date, cache, force_refresh
            )
            all_data.append(df)
        except Exception as e:
            logger.error(f"Failed to fetch {series_id}: {e}")

    if not all_data:
        return pd.DataFrame(columns=["symbol", "price_date", "price", "source"])

    return pd.concat(all_data, ignore_index=True)


def _empty_fred_dataframe(symbol: str) -> pd.DataFrame:
    """Create empty DataFrame with correct schema."""
    return pd.DataFrame(columns=["symbol", "price_date", "price", "source"])
