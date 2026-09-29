"""Commentary provider interface."""

from typing import Any, Protocol


class CommentaryProvider(Protocol):
    """Provider that drafts text from structured facts only."""

    provider_name: str
    model_name: str

    def draft(self, facts: dict[str, Any]) -> str:
        """Return a human-review draft; never approve or close an item."""
        ...
