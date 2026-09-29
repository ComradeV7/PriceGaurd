"""Seeded simulated exception workflow progression."""

import logging
from datetime import date

import numpy as np

from priceguard.db.repo import Repository
from priceguard.workflow.lifecycle import transition_exception

logger = logging.getLogger(__name__)


def simulate_workflow(
    repo: Repository,
    seed: int = 42,
    fraction: float = 0.35,
    as_of: date | None = None,
) -> int:
    """Advance a seeded fraction of open exceptions through lifecycle.

    All updates are explicitly marked ``is_simulated=1`` and a warning is
    emitted because this data is not human review activity.
    """
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be between 0 and 1")
    logger.warning("Simulating workflow transitions; rows are marked simulated")
    rows = repo.query("SELECT exception_id, status FROM exceptions WHERE status='OPEN'")
    if rows.empty:
        return 0
    rng = np.random.default_rng(seed)
    selected = rows[rng.random(len(rows)) < fraction]
    changed = 0
    for row in selected.itertuples(index=False):
        transition_exception(
            repo,
            row.exception_id,
            "UNDER_REVIEW",
            "SIMULATOR",
            "Simulated review",
            as_of,
        )
        repo.conn.execute(
            "UPDATE exceptions SET is_simulated=1 WHERE exception_id=?",
            (row.exception_id,),
        )
        repo.conn.commit()
        changed += 1
    return changed
