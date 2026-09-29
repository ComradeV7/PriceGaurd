"""Synthetic internal mark generation (clean baseline)."""

import numpy as np
import pandas as pd

from priceguard.config import Config

SIGMA_FIELDS = {
    "equity": "equity",
    "bond_etf": "bond_etf",
    "fx": "fx",
    "bond_l2": "bond_l2",
}


def business_days(reference_prices: pd.DataFrame) -> pd.DatetimeIndex:
    """Derive business days from available reference data.

    Simple approach: all dates present in the reference price panel.
    Per-instrument coverage is handled when generating marks (days
    without a reference for an instrument simply get no mark row,
    which the MISSING_MARK check can flag).
    """
    if reference_prices.empty:
        return pd.DatetimeIndex([])
    dates = pd.to_datetime(reference_prices["price_date"]).unique()
    return pd.DatetimeIndex(sorted(dates))


def _sigma_for(asset_class: str, config: Config) -> float:
    """Return the configured mark noise sigma for an asset class."""
    field = SIGMA_FIELDS.get(asset_class)
    if field is None:
        raise ValueError(f"No mark sigma configured for '{asset_class}'")
    return float(getattr(config.settings.mark_noise, field))


def generate_clean_marks(
    positions: pd.DataFrame,
    instruments: pd.DataFrame,
    reference_prices: pd.DataFrame,
    l3_models: pd.DataFrame,
    config: Config,
    seed: int | None = None,
) -> pd.DataFrame:
    """Generate clean internal marks for all positions over the window.

    internal_mark = reference_price * (1 + Normal(0, sigma_class)).

    Level 3 instruments have no reference price; their marks are a slow
    seeded random walk around the fixed model value.

    Args:
        positions: Portfolio positions (position_id, instrument_id, ...).
        instruments: Instrument metadata including asset_class.
        reference_prices: Tidy reference prices
            (symbol/instrument_id, price_date, price, source).
        l3_models: Level 3 model values (instrument_id, model_value).
        config: Loaded configuration.
        seed: Optional seed override; defaults to settings.seed.

    Returns:
        DataFrame with columns position_id, mark_date, mark,
        mark_currency.
    """
    rng = np.random.default_rng(config.settings.seed if seed is None else seed)

    inst_by_id = instruments.set_index("instrument_id")

    ref = reference_prices.copy()
    if ref.empty:
        ref_panel = pd.DataFrame(columns=["instrument_id", "price_date", "price"])
    else:
        id_col = "instrument_id" if "instrument_id" in ref.columns else "symbol"
        ref_panel = ref.rename(columns={id_col: "instrument_id"})[
            ["instrument_id", "price_date", "price"]
        ].copy()
        ref_panel["price_date"] = pd.to_datetime(ref_panel["price_date"])
        ref_panel = ref_panel.drop_duplicates(
            subset=["instrument_id", "price_date"], keep="last"
        )

    days = business_days(ref_panel) if not ref_panel.empty else pd.DatetimeIndex([])
    l3_by_id = (
        l3_models.set_index("instrument_id")
        if not l3_models.empty
        else pd.DataFrame(columns=["model_value"]).rename_axis("instrument_id")
    )

    records = []
    for pos in positions.itertuples(index=False):
        instrument = inst_by_id.loc[pos.instrument_id]
        asset_class = str(instrument["asset_class"])

        if asset_class == "l3":
            if pos.instrument_id not in l3_by_id.index:
                raise ValueError(
                    f"L3 instrument {pos.instrument_id} has no model value"
                )
            model_value = float(l3_by_id.loc[pos.instrument_id, "model_value"])
            sigma_walk = config.settings.mark_noise.l3_daily_walk
            n_days = (
                len(days) if len(days) > 0 else config.settings.lookback_business_days
            )
            if len(days) == 0:
                day_index = pd.bdate_range(
                    end=pd.Timestamp.today().normalize(), periods=n_days
                )
            else:
                day_index = days
            steps = rng.normal(0.0, sigma_walk, size=len(day_index))
            walk = model_value * np.exp(np.cumsum(steps) - np.mean(np.cumsum(steps)))
            for d, mark in zip(day_index, walk):
                records.append(
                    {
                        "position_id": pos.position_id,
                        "mark_date": d,
                        "mark": round(float(mark), 6),
                        "mark_currency": pos.currency,
                    }
                )
            continue

        sigma = _sigma_for(asset_class, config)
        inst_refs = ref_panel[ref_panel["instrument_id"] == pos.instrument_id]
        if inst_refs.empty:
            continue
        noise = rng.normal(0.0, sigma, size=len(inst_refs))
        marks = inst_refs["price"].to_numpy(dtype=float) * (1.0 + noise)
        for d, mark in zip(inst_refs["price_date"], marks):
            records.append(
                {
                    "position_id": pos.position_id,
                    "mark_date": d,
                    "mark": round(float(mark), 6),
                    "mark_currency": pos.currency,
                }
            )

    result = pd.DataFrame(
        records, columns=["position_id", "mark_date", "mark", "mark_currency"]
    )
    if not result.empty:
        result = result.sort_values(["mark_date", "position_id"]).reset_index(drop=True)
    return result
