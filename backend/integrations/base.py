from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PullRequestData:
    provider: str
    repo: str
    pr_number: int
    title: str
    diff: str
    changed_files: list[dict[str, Any]] = field(default_factory=list)
    base_sha: str | None = None
    head_sha: str | None = None
    branch_name: str = ""
    linked_ticket_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TicketData:
    provider: str
    ticket_id: str
    title: str
    description: str
    acceptance_criteria: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ScmProvider(ABC):
    key: str

    @abstractmethod
    def fetch_pull_request(self, *, repo: str, pr_number: int, token: str) -> PullRequestData:
        raise NotImplementedError

    @abstractmethod
    def post_comment(self, *, repo: str, pr_number: int, body: str, token: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def approve_pull_request(self, *, repo: str, pr_number: int, token: str) -> None:
        raise NotImplementedError


class TrackerProvider(ABC):
    key: str

    @abstractmethod
    def fetch_ticket(self, *, ticket_id: str, token: str, project_hint: str = "") -> TicketData | None:
        raise NotImplementedError
