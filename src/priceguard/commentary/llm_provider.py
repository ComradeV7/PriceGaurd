"""Optional, injectable LLM commentary provider."""

import json
import os
from typing import Any, Callable

SYSTEM_PROMPT = (
    "Draft short factual commentary using only the supplied JSON facts. "
    "Never invent facts or numbers. Say unknown when the cause is unclear. "
    "Do not approve, adjust, close, or recommend changing a mark."
)


class LLMProvider:
    """LLM provider with temperature zero and a swappable client.

    The client callable receives ``system_prompt``, ``user_json``,
    ``model`` and ``temperature``. This avoids making a provider-specific
    SDK a runtime dependency and makes tests fully mockable.
    """

    provider_name = "llm"

    def __init__(
        self,
        client: Callable[..., str] | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
    ) -> None:
        """Configure an injected client or environment-backed provider."""
        self.api_key = api_key or os.getenv("PRICEGUARD_LLM_API_KEY")
        self.model_name = model_name or os.getenv("PRICEGUARD_LLM_MODEL", "gpt-4o-mini")
        self.client = client

    def draft(self, facts: dict[str, Any]) -> str:
        """Draft text using the injected client."""
        if self.client is None:
            raise RuntimeError(
                "No LLM client configured; inject a client or configure the provider"
            )
        return self.client(
            system_prompt=SYSTEM_PROMPT,
            user_json=json.dumps(facts, sort_keys=True, default=str),
            model=self.model_name,
            temperature=0,
            api_key=self.api_key,
        )
