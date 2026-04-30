from __future__ import annotations

from typing import Any

from backend.integrations.base import ScmProvider, TrackerProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._scm: dict[str, ScmProvider] = {}
        self._tracker: dict[str, TrackerProvider] = {}

    def register_scm(self, provider: ScmProvider) -> None:
        self._scm[provider.key] = provider

    def register_tracker(self, provider: TrackerProvider) -> None:
        self._tracker[provider.key] = provider

    def get_scm(self, key: str) -> ScmProvider:
        provider = self._scm.get(key.strip().lower())
        if not provider:
            raise KeyError(f"Unknown SCM provider '{key}'.")
        return provider

    def get_tracker(self, key: str) -> TrackerProvider:
        provider = self._tracker.get(key.strip().lower())
        if not provider:
            raise KeyError(f"Unknown tracker provider '{key}'.")
        return provider

    def available(self) -> dict[str, list[str]]:
        return {
            "scm": sorted(self._scm.keys()),
            "tracker": sorted(self._tracker.keys()),
        }


provider_registry = ProviderRegistry()
