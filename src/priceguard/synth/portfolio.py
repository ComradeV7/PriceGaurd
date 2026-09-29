"""Synthetic portfolio generation."""

import numpy as np
import pandas as pd

from priceguard.config import Config


def generate_portfolio(config: Config, seed: int | None = None) -> pd.DataFrame:
    """Generate one position per instrument with seeded attributes.

    Args:
        config: Loaded configuration.
        seed: Optional seed override; defaults to settings.seed.

    Returns:
        DataFrame with columns position_id, instrument_id, book,
        quantity, currency.
    """
    rng = np.random.default_rng(config.settings.seed if seed is None else seed)
    books = config.settings.portfolio.books
    ranges = config.settings.portfolio.quantity_ranges

    records = []
    for instrument in config.universe.instruments:
        qty_range = ranges.get(instrument.asset_class)
        if qty_range is None:
            raise ValueError(
                f"No quantity range configured for asset class "
                f"'{instrument.asset_class}'"
            )
        quantity = float(rng.uniform(qty_range.min, qty_range.max))
        if instrument.asset_class == "l3":
            quantity = float(np.ceil(quantity))
        book = str(rng.choice(books))
        records.append(
            {
                "position_id": f"POS-{instrument.ticker}",
                "instrument_id": instrument.ticker,
                "book": book,
                "quantity": round(quantity, 2),
                "currency": instrument.currency,
            }
        )

    return pd.DataFrame(records)


def instruments_frame(config: Config) -> pd.DataFrame:
    """Convert the configured universe into an instruments DataFrame."""
    records = [
        {
            "instrument_id": i.ticker,
            "ticker": i.ticker,
            "name": i.name,
            "asset_class": i.asset_class,
            "currency": i.currency,
            "fv_level": i.fv_level,
            "ref_source": i.ref_source,
            "is_active": 1,
        }
        for i in config.universe.instruments
    ]
    return pd.DataFrame(records)


def l3_models_frame(config: Config) -> pd.DataFrame:
    """Build Level 3 model values and bands from the universe config."""
    records = []
    for i in config.universe.instruments:
        if i.asset_class != "l3":
            continue
        if i.model_value is None or i.model_band_pct is None:
            raise ValueError(
                f"L3 instrument {i.ticker} requires model_value and "
                f"model_band_pct in universe.yaml"
            )
        band = i.model_value * i.model_band_pct / 100.0
        records.append(
            {
                "instrument_id": i.ticker,
                "model_value": i.model_value,
                "band_min": i.model_value - band,
                "band_max": i.model_value + band,
            }
        )
    return pd.DataFrame(records)
