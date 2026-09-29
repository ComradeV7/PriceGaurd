"""Exception lifecycle and business-day ageing."""

from datetime import date, timedelta

from priceguard.db.repo import Repository
from priceguard.review.audit import log_event

ALLOWED_TRANSITIONS = {
    "OPEN": {"UNDER_REVIEW"},
    "UNDER_REVIEW": {"RESOLVED", "ADJUSTED", "ESCALATED"},
    "ESCALATED": {"UNDER_REVIEW", "RESOLVED", "ADJUSTED"},
    "RESOLVED": set(),
    "ADJUSTED": set(),
}
CLOSED_STATUSES = {"RESOLVED", "ADJUSTED"}


def business_days_between(start: date, end: date) -> int:
    """Count weekdays from start through end, excluding the start date."""
    if end <= start:
        return 0
    return sum(
        1
        for offset in range(1, (end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() < 5
    )


def validate_transition(
    old_status: str,
    new_status: str,
    reviewer: str | None = None,
    note: str | None = None,
) -> None:
    """Validate a lifecycle transition and closure requirements."""
    if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
        raise ValueError(f"Illegal transition: {old_status} -> {new_status}")
    if new_status in CLOSED_STATUSES and (not reviewer or not note):
        raise ValueError("Resolved or adjusted items require reviewer and note")


def calculate_age_days(opened_date: date, as_of: date | None = None) -> int:
    """Calculate open age in business days."""
    return business_days_between(opened_date, as_of or date.today())


def transition_exception(
    repo: Repository,
    exception_id: str,
    new_status: str,
    reviewer: str,
    note: str | None = None,
    event_date: date | None = None,
) -> dict:
    """Apply a validated transition and write its audit event."""
    if not reviewer or not reviewer.strip():
        raise ValueError("A reviewer is required for every transition")
    rows = repo.query(
        "SELECT * FROM exceptions WHERE exception_id = ?", (exception_id,)
    )
    if rows.empty:
        raise ValueError(f"Exception not found: {exception_id}")
    before = rows.iloc[0].to_dict()
    old_status = str(before["status"])
    validate_transition(old_status, new_status, reviewer, note)
    now = event_date or date.today()
    resolved_date = (
        now.isoformat() if new_status in CLOSED_STATUSES else before["resolved_date"]
    )
    age_days = calculate_age_days(date.fromisoformat(str(before["opened_date"])), now)
    repo.conn.execute(
        "UPDATE exceptions SET status=?, resolved_date=?, age_days=?, "
        "assigned_to=?, resolution_note=? WHERE exception_id=?",
        (new_status, resolved_date, age_days, reviewer, note, exception_id),
    )
    repo.conn.commit()
    after = (
        repo.query("SELECT * FROM exceptions WHERE exception_id = ?", (exception_id,))
        .iloc[0]
        .to_dict()
    )
    log_event(
        repo, reviewer, "STATUS_TRANSITION", "exception", exception_id, before, after
    )
    return after


def refresh_ages(repo: Repository, as_of: date | None = None) -> int:
    """Refresh age_days for all open exceptions."""
    rows = repo.query("SELECT exception_id, opened_date, status FROM exceptions")
    changed = 0
    for row in rows.itertuples(index=False):
        if row.status in CLOSED_STATUSES:
            continue
        age = calculate_age_days(date.fromisoformat(row.opened_date), as_of)
        repo.conn.execute(
            "UPDATE exceptions SET age_days=? WHERE exception_id=?",
            (age, row.exception_id),
        )
        changed += 1
    repo.conn.commit()
    return changed
