"""Synthetic fault injection with ground truth (Section 4.5).

Every injected fault is written to the ground_truth table. The
validation engine never reads ground_truth; only the backtest module
does. Faults never overlap on the same position-day.
"""

import json
from datetime import date

import numpy as np
import pandas as pd

from priceguard.config import Config

FAULT_TYPES = ["STALE", "FAT_FINGER", "MISSING", "DRIFT", "CURRENCY_MISMATCH"]


def _warn_bps_for(asset_class: str, fv_level: int, config: Config) -> float | None:
    """Return the warn threshold in bps for an instrument, if any."""
    t = config.tolerances
    if fv_level == 3:
        return None
    mapping = {
        ("equity", 1): t.equity_l1,
        ("bond_etf", 1): t.bond_etf_l1,
        ("fx", 1): t.fx_l1,
        ("bond_l2", 2): t.bond_l2,
    }
    entry = mapping.get((asset_class, fv_level))
    return entry.warn_bps if entry is not None else None


def _transpose_digits(value: float, rng: np.random.Generator) -> float:
    """Swap two adjacent digits of the value's decimal representation."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    digits = [i for i, ch in enumerate(text) if ch.isdigit()]
    if len(digits) < 2:
        return value * 10.0
    idx = int(rng.integers(0, len(digits) - 1))
    a, b = digits[idx], digits[idx + 1]
    chars = list(text)
    chars[a], chars[b] = chars[b], chars[a]
    try:
        return float("".join(chars))
    except ValueError:
        return value * 10.0


def inject_faults(
    marks: pd.DataFrame,
    positions: pd.DataFrame,
    instruments: pd.DataFrame,
    fx_rates: pd.DataFrame,
    config: Config,
    seed: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Inject seeded faults into clean marks and record ground truth.

    Args:
        marks: Clean internal marks
            (position_id, mark_date, mark, mark_currency), sorted.
        positions: Portfolio positions.
        instruments: Instrument metadata (asset_class, fv_level, currency).
        fx_rates: Tidy USDINR reference rates
            (symbol, price_date, price, source) used for currency faults.
        config: Loaded configuration.
        seed: Optional seed override; defaults to settings.seed.

    Returns:
        Tuple of (faulty marks DataFrame with the same schema, ground
        truth DataFrame with position_id, mark_date, fault_type,
        fault_params_json).
    """
    rng = np.random.default_rng(config.settings.seed if seed is None else seed)
    fi = config.fault_injection

    faulty = marks.copy().reset_index(drop=True)
    faulty["mark_date"] = pd.to_datetime(faulty["mark_date"])

    pos_info = positions.set_index("position_id")
    inst_info = instruments.set_index("instrument_id")

    usdinr = fx_rates[fx_rates["symbol"] == "USDINR"].copy()
    usdinr["price_date"] = pd.to_datetime(usdinr["price_date"])
    usdinr_map = dict(zip(usdinr["price_date"], usdinr["price"]))

    groups = {
        pid: g.sort_values("mark_date")
        for pid, g in faulty.groupby("position_id", sort=True)
    }
    position_ids = sorted(groups.keys())
    if not position_ids:
        return faulty, _empty_ground_truth()

    total_days = len(faulty)
    target_fault_days = int(round(fi.injection_rate * total_days))

    used: set[tuple[str, pd.Timestamp]] = set()
    ground_truth_rows: list[dict] = []
    injected_days = 0
    attempts = 0
    max_attempts = target_fault_days * 20 + 100

    weights = np.array([fi.fault_type_weights[t] for t in FAULT_TYPES], dtype=float)
    weights = weights / weights.sum()

    while injected_days < target_fault_days and attempts < max_attempts:
        attempts += 1
        subtle = bool(rng.random() < fi.subtle_fraction)
        if subtle:
            fault_type = "DRIFT"
        else:
            fault_type = str(rng.choice(FAULT_TYPES, p=weights))

        pid = str(rng.choice(position_ids))
        group = groups[pid]
        n = len(group)
        if n == 0:
            continue
        position = pos_info.loc[pid]
        instrument = inst_info.loc[position["instrument_id"]]
        asset_class = str(instrument["asset_class"])
        fv_level = int(instrument["fv_level"])

        params = _fault_params(fault_type, rng, config, asset_class, fv_level, subtle)
        duration = int(params["duration_days"])
        start_idx = int(rng.integers(0, max(1, n - duration + 1)))

        affected_dates = (
            group["mark_date"].iloc[start_idx : start_idx + duration].tolist()
        )
        if any((pid, d) in used for d in affected_dates):
            continue
        if fault_type == "STALE" and start_idx == 0:
            continue

        for d in affected_dates:
            used.add((pid, d))
        injected_days += len(affected_dates)

        _apply_fault(
            faulty=faulty,
            group=group,
            start_idx=start_idx,
            fault_type=fault_type,
            params=params,
            usdinr_map=usdinr_map,
            position=position,
            instrument=instrument,
            rng=rng,
        )

        params_record = dict(params)
        params_record["start_date"] = str(affected_dates[0].date())
        params_record["end_date"] = str(affected_dates[-1].date())
        for d in affected_dates:
            ground_truth_rows.append(
                {
                    "position_id": pid,
                    "mark_date": d,
                    "fault_type": fault_type,
                    "fault_params_json": json.dumps(params_record, sort_keys=True),
                }
            )

    ground_truth = pd.DataFrame(
        ground_truth_rows,
        columns=["position_id", "mark_date", "fault_type", "fault_params_json"],
    )
    faulty["mark_date"] = pd.to_datetime(faulty["mark_date"])
    return faulty, ground_truth


def _fault_params(
    fault_type: str,
    rng: np.random.Generator,
    config: Config,
    asset_class: str,
    fv_level: int,
    subtle: bool,
) -> dict:
    """Draw parameters for a fault event."""
    fp = config.fault_injection.fault_parameters[fault_type]
    params: dict = {"subtle": subtle}

    if fault_type == "STALE":
        lo = int(fp.min_consecutive_days or 2)
        hi = int(fp.max_consecutive_days or 5)
        params["duration_days"] = int(rng.integers(lo, hi + 1))
    elif fault_type == "FAT_FINGER":
        params["duration_days"] = 1
        use_transposition = (
            fp.transposition_probability is not None
            and rng.random() < fp.transposition_probability
        )
        if use_transposition:
            params["mode"] = "transposition"
        else:
            multipliers = fp.multipliers or [10.0, 0.1]
            params["mode"] = "multiplier"
            params["multiplier"] = float(rng.choice(np.array(multipliers)))
    elif fault_type == "MISSING":
        params["duration_days"] = 1
    elif fault_type == "DRIFT":
        lo = int(fp.min_days or 10)
        hi = int(fp.max_days or 20)
        duration = int(rng.integers(lo, hi + 1))
        params["duration_days"] = duration
        if subtle:
            warn = _warn_bps_for(asset_class, fv_level, config)
            if warn is None:
                warn = float(fp.bps_per_day_min or 5) * duration * 1.1
            target_final_bps = warn * 1.1
            params["bps_per_day"] = target_final_bps / duration
        else:
            lo_bps = float(fp.bps_per_day_min or 5)
            hi_bps = float(fp.bps_per_day_max or 15)
            params["bps_per_day"] = float(rng.uniform(lo_bps, hi_bps))
        params["direction"] = float(rng.choice([-1.0, 1.0]))
    elif fault_type == "CURRENCY_MISMATCH":
        params["duration_days"] = 1
        params["fx_pair"] = "USDINR"
    return params


def _apply_fault(
    faulty: pd.DataFrame,
    group: pd.DataFrame,
    start_idx: int,
    fault_type: str,
    params: dict,
    usdinr_map: dict,
    position: pd.Series,
    instrument: pd.Series,
    rng: np.random.Generator,
) -> None:
    """Apply a fault event in place to the faulty marks frame."""
    pid = group["position_id"].iloc[0]
    dates = group["mark_date"].iloc[start_idx : start_idx + params["duration_days"]]
    mask = faulty["position_id"].eq(pid) & faulty["mark_date"].isin(dates)
    idx = faulty.index[mask]

    if fault_type == "STALE":
        prev_idx = group.index[start_idx - 1]
        stale_value = float(faulty.loc[prev_idx, "mark"])
        faulty.loc[idx, "mark"] = stale_value

    elif fault_type == "FAT_FINGER":
        target = idx[0]
        clean = float(faulty.loc[target, "mark"])
        if params["mode"] == "transposition":
            faulty.loc[target, "mark"] = _transpose_digits(clean, rng)
        else:
            faulty.loc[target, "mark"] = clean * params["multiplier"]

    elif fault_type == "MISSING":
        faulty.loc[idx[0], "mark"] = None

    elif fault_type == "DRIFT":
        direction = float(params["direction"])
        bps_per_day = float(params["bps_per_day"])
        for k, target in enumerate(idx):
            clean = group["mark"].iloc[start_idx + k]
            if pd.isna(clean):
                continue
            deviation = direction * bps_per_day * (k + 1) / 10_000.0
            faulty.loc[target, "mark"] = float(clean) * (1.0 + deviation)

    elif fault_type == "CURRENCY_MISMATCH":
        target = idx[0]
        d = faulty.loc[target, "mark_date"]
        rate = usdinr_map.get(d)
        if rate is None or pd.isna(rate):
            return
        clean = float(faulty.loc[target, "mark"])
        currency = str(instrument["currency"])
        if currency == "INR":
            faulty.loc[target, "mark"] = clean / float(rate)
        else:
            faulty.loc[target, "mark"] = clean * float(rate)


def _empty_ground_truth() -> pd.DataFrame:
    """Empty ground-truth frame with the correct schema."""
    return pd.DataFrame(
        columns=["position_id", "mark_date", "fault_type", "fault_params_json"]
    )


def ground_truth_for_date(ground_truth: pd.DataFrame, mark_date: date) -> pd.DataFrame:
    """Filter ground truth to a single mark date (backtest helper)."""
    df = ground_truth.copy()
    df["mark_date"] = pd.to_datetime(df["mark_date"])
    return df[df["mark_date"] == pd.Timestamp(mark_date)]
