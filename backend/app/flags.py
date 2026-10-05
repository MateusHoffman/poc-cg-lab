from __future__ import annotations

from openfeature import api
from openfeature.provider.in_memory_provider import InMemoryFlag, InMemoryProvider

DEFAULTS = {
    "finance-sandbox": True,
    "rag-cache": True,
}


class FlagClient:
    """OpenFeature com provider em memória para rollout local.

    Em produção o provider troca para o backend de flags sem mudar a chamada.
    """

    def __init__(self) -> None:
        self._values = dict(DEFAULTS)
        self._apply()

    def _apply(self) -> None:
        flags = {
            key: InMemoryFlag(
                "on" if enabled else "off",
                {"on": True, "off": False},
            )
            for key, enabled in self._values.items()
        }
        api.set_provider(InMemoryProvider(flags))
        self._client = api.get_client("cg-autoagent")

    def enabled(self, key: str) -> bool:
        return bool(self._client.get_boolean_value(key, self._values.get(key, False)))

    def set(self, key: str, enabled: bool) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        self._values[key] = enabled
        self._apply()

    def snapshot(self) -> dict[str, bool]:
        return {key: self.enabled(key) for key in DEFAULTS}
