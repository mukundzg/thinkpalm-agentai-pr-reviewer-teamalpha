from __future__ import annotations

import re
import requests

from backend.integrations.base import TicketData, TrackerProvider
from backend.integrations.registry import provider_registry


def _criteria_from_text(text: str) -> list[str]:
    items: list[str] = []
    for line in (text or "").splitlines():
        value = line.strip().lstrip("-").strip()
        if value.lower().startswith(("acceptance criteria", "ac:", "must", "should", "given", "when", "then")):
            items.append(value)
    return items


class JiraTrackerProvider(TrackerProvider):
    key = "jira"

    def fetch_ticket(self, *, ticket_id: str, token: str, project_hint: str = "") -> TicketData | None:
        _ = requests.Session()
        description = f"Jira ticket {ticket_id} requirements placeholder."
        return TicketData(
            provider=self.key,
            ticket_id=ticket_id,
            title=f"{ticket_id} story",
            description=description,
            acceptance_criteria=_criteria_from_text(description),
            metadata={"stub_provider": True, "project_hint": project_hint},
        )


class LinearTrackerProvider(TrackerProvider):
    key = "linear"

    def fetch_ticket(self, *, ticket_id: str, token: str, project_hint: str = "") -> TicketData | None:
        _ = requests.Session()
        description = f"Linear issue {ticket_id} requirements placeholder."
        return TicketData(
            provider=self.key,
            ticket_id=ticket_id,
            title=f"{ticket_id} task",
            description=description,
            acceptance_criteria=_criteria_from_text(description),
            metadata={"stub_provider": True, "project_hint": project_hint},
        )


class GitHubIssuesTrackerProvider(TrackerProvider):
    key = "github_issues"
    _issue_re = re.compile(r"#(\d+)$")

    def fetch_ticket(self, *, ticket_id: str, token: str, project_hint: str = "") -> TicketData | None:
        _ = requests.Session()
        if not self._issue_re.search(ticket_id):
            return None
        description = f"GitHub issue {ticket_id} requirements placeholder."
        return TicketData(
            provider=self.key,
            ticket_id=ticket_id,
            title=f"Issue {ticket_id}",
            description=description,
            acceptance_criteria=_criteria_from_text(description),
            metadata={"stub_provider": True, "project_hint": project_hint},
        )


def register_default_tracker_providers() -> None:
    for provider in (JiraTrackerProvider(), LinearTrackerProvider(), GitHubIssuesTrackerProvider()):
        provider_registry.register_tracker(provider)
