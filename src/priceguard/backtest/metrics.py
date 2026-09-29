"""Control-effectiveness metrics against synthetic ground truth.

This is the only module that reads ``ground_truth``. Matching is performed
at position-day level so multiple detecting checks count as one detection.
"""

from collections.abc import Iterable

import pandas as pd

PAIR_COLUMNS = ["position_id", "mark_date"]


def _pairs(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize and deduplicate position-day pairs."""
    if frame.empty:
        return pd.DataFrame(columns=PAIR_COLUMNS)
    result = frame[PAIR_COLUMNS].copy()
    result["mark_date"] = pd.to_datetime(result["mark_date"]).dt.date.astype(str)
    return result.drop_duplicates(PAIR_COLUMNS)


def calculate_metrics(
    ground_truth: pd.DataFrame,
    exceptions: pd.DataFrame,
    marks: pd.DataFrame | None = None,
) -> dict:
    """Calculate recall, precision, false-positive rate and detection lag."""
    truth = _pairs(ground_truth)
    detected = _pairs(exceptions)
    matched = truth.merge(detected, on=PAIR_COLUMNS, how="inner")
    tp = len(matched)
    fn = len(truth) - tp
    fp_pairs = detected.merge(truth, on=PAIR_COLUMNS, how="left", indicator=True)
    fp = int((fp_pairs["_merge"] == "left_only").sum())
    clean_denominator = max(
        1,
        (len(_pairs(marks)) - len(truth)) if marks is not None else len(truth) + fp,
    )

    per_fault = []
    if not ground_truth.empty:
        for fault_type, group in ground_truth.groupby("fault_type"):
            type_truth = _pairs(group)
            type_tp = len(type_truth.merge(detected, on=PAIR_COLUMNS, how="inner"))
            per_fault.append(
                {
                    "fault_type": fault_type,
                    "injected": len(type_truth),
                    "detected": type_tp,
                    "recall": type_tp / len(type_truth) if len(type_truth) else 0.0,
                }
            )

    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "injected": len(truth),
        "detected": len(detected),
        "recall": tp / len(truth) if len(truth) else 0.0,
        "precision": tp / len(detected) if len(detected) else 0.0,
        "false_positive_rate": fp / clean_denominator,
        "per_fault_type": pd.DataFrame(per_fault),
        "detection_lag": detection_lag(ground_truth, exceptions),
    }


def detection_lag(ground_truth: pd.DataFrame, exceptions: pd.DataFrame) -> pd.DataFrame:
    """Calculate first-detection lag for STALE and DRIFT fault episodes."""
    if ground_truth.empty:
        return pd.DataFrame(columns=["fault_type", "position_id", "lag_days"])
    detected = _pairs(exceptions)
    rows = []
    scoped = ground_truth[ground_truth["fault_type"].isin(["STALE", "DRIFT"])]
    for (fault_type, position_id), group in scoped.groupby(
        ["fault_type", "position_id"]
    ):
        injected_dates = pd.to_datetime(group["mark_date"])
        first_injected = injected_dates.min()
        candidates = detected[
            (detected["position_id"] == position_id)
            & (pd.to_datetime(detected["mark_date"]) >= first_injected)
        ]
        first_detected = (
            pd.to_datetime(candidates["mark_date"]).min()
            if not candidates.empty
            else pd.NaT
        )
        rows.append(
            {
                "fault_type": fault_type,
                "position_id": position_id,
                "lag_days": (
                    (first_detected - first_injected).days
                    if pd.notna(first_detected)
                    else None
                ),
            }
        )
    return pd.DataFrame(rows)


def threshold_sweep(
    observations: pd.DataFrame,
    ground_truth: pd.DataFrame,
    multipliers: Iterable[float] = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0),
    base_threshold_bps: float = 50.0,
) -> pd.DataFrame:
    """Return recall/FPR trade-offs for threshold multipliers.

    ``observations`` requires position_id, mark_date and deviation_bps.
    Smaller multipliers are tighter thresholds and therefore have
    monotonically non-increasing recall as the multiplier increases.
    """
    truth = _pairs(ground_truth)
    rows = []
    total_observations = max(1, len(_pairs(observations)))
    for multiplier in sorted(float(x) for x in multipliers):
        flagged = observations[
            observations["deviation_bps"].abs() >= base_threshold_bps * multiplier
        ]
        detected = _pairs(flagged)
        tp = len(truth.merge(detected, on=PAIR_COLUMNS, how="inner"))
        fp = len(
            detected.merge(truth, on=PAIR_COLUMNS, how="left", indicator=True).query(
                "_merge == 'left_only'"
            )
        )
        rows.append(
            {
                "multiplier": multiplier,
                "threshold_bps": base_threshold_bps * multiplier,
                "recall": tp / len(truth) if len(truth) else 0.0,
                "false_positive_rate": fp / max(1, total_observations - len(truth)),
            }
        )
    return pd.DataFrame(rows)


def metrics_from_repository(repo) -> dict:
    """Load repository data and calculate metrics for the current run."""
    ground_truth = repo.get_ground_truth()
    exceptions = repo.get_exceptions()
    marks = repo.query("SELECT position_id, mark_date FROM internal_marks")
    return calculate_metrics(ground_truth, exceptions, marks)
