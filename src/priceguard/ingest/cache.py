"""Parquet cache for reference data."""

from datetime import date
from pathlib import Path

import pandas as pd


class ReferenceDataCache:
    """Cache for reference price data using Parquet files."""

    def __init__(self, cache_dir: Path) -> None:
        """Initialize cache with directory path."""
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(
        self, source: str, symbol: str, start_date: date, end_date: date
    ) -> str:
        """Generate cache key from parameters."""
        return f"{source}_{symbol}_{start_date}_{end_date}.parquet"

    def _cache_path(
        self, source: str, symbol: str, start_date: date, end_date: date
    ) -> Path:
        """Generate cache file path."""
        key = self._cache_key(source, symbol, start_date, end_date)
        return self.cache_dir / key

    def get(
        self,
        source: str,
        symbol: str,
        start_date: date,
        end_date: date,
        force_refresh: bool = False,
    ) -> pd.DataFrame | None:
        """Retrieve cached data if available.

        Args:
            source: Data source identifier
            symbol: Instrument symbol
            start_date: Start date for data
            end_date: End date for data
            force_refresh: If True, ignore cache and fetch fresh data

        Returns:
            Cached DataFrame or None if not found/force_refresh
        """
        if force_refresh:
            return None

        cache_path = self._cache_path(source, symbol, start_date, end_date)
        if not cache_path.exists():
            return None

        try:
            df = pd.read_parquet(cache_path)
            return df
        except Exception:
            return None

    def put(
        self,
        source: str,
        symbol: str,
        start_date: date,
        end_date: date,
        df: pd.DataFrame,
    ) -> None:
        """Store data in cache.

        Args:
            source: Data source identifier
            symbol: Instrument symbol
            start_date: Start date for data
            end_date: End date for data
            df: DataFrame to cache
        """
        cache_path = self._cache_path(source, symbol, start_date, end_date)
        df.to_parquet(cache_path, index=False)

    def clear(self, source: str | None = None) -> None:
        """Clear cached data.

        Args:
            source: If provided, only clear cache for this source
        """
        if source is None:
            for cache_file in self.cache_dir.glob("*.parquet"):
                cache_file.unlink()
        else:
            for cache_file in self.cache_dir.glob(f"{source}_*.parquet"):
                cache_file.unlink()


def load_all_cached(cache_dir: Path) -> pd.DataFrame:
    """Load and concatenate every parquet file in a directory.

    Used for offline runs against data/sample and for reading the
    data/raw cache written by the ingest command.

    Returns:
        Combined tidy DataFrame (symbol, price_date, price, source),
        empty if no files exist.
    """
    frames = []
    for parquet_file in sorted(cache_dir.glob("*.parquet")):
        try:
            frames.append(pd.read_parquet(parquet_file))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=["symbol", "price_date", "price", "source"])
    return pd.concat(frames, ignore_index=True)
