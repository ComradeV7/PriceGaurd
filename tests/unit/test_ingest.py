"""Tests for ingest modules with mocked HTTP responses."""

import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from priceguard.ingest.cache import ReferenceDataCache
from priceguard.ingest.fred import fetch_fred_series
from priceguard.ingest.fx import fetch_fx_prices
from priceguard.ingest.stooq import fetch_stooq_prices
from priceguard.ingest.yahoo import fetch_yahoo_prices


@pytest.fixture
def temp_cache_dir():
    """Create temporary cache directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def cache(temp_cache_dir):
    """Create cache instance."""
    return ReferenceDataCache(temp_cache_dir)


def test_cache_put_and_get(cache):
    """Cache stores and retrieves data correctly."""
    df = pd.DataFrame(
        {
            "symbol": ["AAPL"],
            "price_date": [pd.Timestamp("2024-01-01")],
            "price": [150.0],
            "source": ["yahoo"],
        }
    )

    cache.put("yahoo", "AAPL", date(2024, 1, 1), date(2024, 1, 31), df)
    retrieved = cache.get("yahoo", "AAPL", date(2024, 1, 1), date(2024, 1, 31))

    assert retrieved is not None
    assert len(retrieved) == 1
    assert retrieved.iloc[0]["symbol"] == "AAPL"


def test_cache_force_refresh(cache):
    """Cache returns None when force_refresh is True."""
    df = pd.DataFrame(
        {
            "symbol": ["AAPL"],
            "price_date": [pd.Timestamp("2024-01-01")],
            "price": [150.0],
            "source": ["yahoo"],
        }
    )

    cache.put("yahoo", "AAPL", date(2024, 1, 1), date(2024, 1, 31), df)
    retrieved = cache.get(
        "yahoo", "AAPL", date(2024, 1, 1), date(2024, 1, 31), force_refresh=True
    )

    assert retrieved is None


def test_cache_clear(cache):
    """Cache clears data correctly."""
    df = pd.DataFrame(
        {
            "symbol": ["AAPL"],
            "price_date": [pd.Timestamp("2024-01-01")],
            "price": [150.0],
            "source": ["yahoo"],
        }
    )

    cache.put("yahoo", "AAPL", date(2024, 1, 1), date(2024, 1, 31), df)
    cache.clear("yahoo")

    retrieved = cache.get("yahoo", "AAPL", date(2024, 1, 1), date(2024, 1, 31))
    assert retrieved is None


@patch("priceguard.ingest.yahoo.yf.Ticker")
def test_fetch_yahoo_prices(mock_ticker, cache):
    """Yahoo Finance fetch returns correct schema."""
    mock_df = pd.DataFrame(
        {
            "Close": [150.0, 151.0, 152.0],
        },
        index=pd.date_range("2024-01-01", periods=3),
    )

    mock_instance = MagicMock()
    mock_instance.history.return_value = mock_df
    mock_ticker.return_value = mock_instance

    result = fetch_yahoo_prices(
        "AAPL",
        date(2024, 1, 1),
        date(2024, 1, 3),
        cache,
    )

    assert len(result) == 3
    assert "symbol" in result.columns
    assert "price_date" in result.columns
    assert "price" in result.columns
    assert "source" in result.columns
    assert result.iloc[0]["symbol"] == "AAPL"
    assert result.iloc[0]["source"] == "yahoo"


@patch("priceguard.ingest.fred.requests.get")
def test_fetch_fred_series(mock_get, cache):
    """FRED fetch returns correct schema."""
    mock_response = MagicMock()
    mock_response.text = "DATE,value\n2024-01-01,4.5\n2024-01-02,4.6\n"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    result = fetch_fred_series(
        "DGS10",
        date(2024, 1, 1),
        date(2024, 1, 31),
        cache,
    )

    assert len(result) == 2
    assert "symbol" in result.columns
    assert "price_date" in result.columns
    assert "price" in result.columns
    assert "source" in result.columns
    assert result.iloc[0]["symbol"] == "DGS10"
    assert result.iloc[0]["source"] == "fred"


@patch("priceguard.ingest.fx.requests.get")
def test_fetch_fx_prices(mock_get, cache):
    """FX fetch returns correct schema."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "rates": {
            "2024-01-01": {"USD": 1.10},
            "2024-01-02": {"USD": 1.11},
        }
    }
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    result = fetch_fx_prices(
        "EURUSD",
        date(2024, 1, 1),
        date(2024, 1, 31),
        cache,
    )

    assert len(result) == 2
    assert "symbol" in result.columns
    assert "price_date" in result.columns
    assert "price" in result.columns
    assert "source" in result.columns
    assert result.iloc[0]["symbol"] == "EURUSD"


@patch("priceguard.ingest.stooq.requests.get")
def test_fetch_stooq_prices(mock_get, cache):
    """Stooq fetch returns correct schema."""
    mock_response = MagicMock()
    mock_response.text = (
        "Date,Open,High,Low,Close,Volume\n2024-01-01,150,151,149,150,1000\n"
    )
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    result = fetch_stooq_prices(
        "AAPL",
        "aapl.us",
        date(2024, 1, 1),
        date(2024, 1, 31),
        cache,
    )

    assert len(result) == 1
    assert "symbol" in result.columns
    assert "price_date" in result.columns
    assert "price" in result.columns
    assert "source" in result.columns
    assert result.iloc[0]["symbol"] == "AAPL"
    assert result.iloc[0]["source"] == "stooq"


@patch("priceguard.ingest.stooq.requests.get")
def test_fetch_stooq_prices_no_data(mock_get, cache):
    """Stooq fetch returns empty DataFrame when no data."""
    mock_response = MagicMock()
    mock_response.text = "No data"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    result = fetch_stooq_prices(
        "INVALID",
        "invalid.us",
        date(2024, 1, 1),
        date(2024, 1, 31),
        cache,
    )

    assert len(result) == 0
    assert "symbol" in result.columns
    assert "price_date" in result.columns
    assert "price" in result.columns
    assert "source" in result.columns


@patch("priceguard.ingest.stooq.requests.get")
def test_fetch_stooq_prices_failure_graceful(mock_get, cache):
    """Stooq fetch handles failure gracefully."""
    mock_get.side_effect = Exception("Network error")

    result = fetch_stooq_prices(
        "AAPL",
        "aapl.us",
        date(2024, 1, 1),
        date(2024, 1, 31),
        cache,
    )

    assert len(result) == 0
    assert "symbol" in result.columns
