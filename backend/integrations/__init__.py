from backend.integrations.linking import resolve_ticket_ids
from backend.integrations.registry import provider_registry
from backend.integrations.scm_providers import register_default_scm_providers
from backend.integrations.tracker_providers import register_default_tracker_providers


def register_default_providers() -> None:
    register_default_scm_providers()
    register_default_tracker_providers()


__all__ = ["provider_registry", "register_default_providers", "resolve_ticket_ids"]
