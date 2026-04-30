from __future__ import annotations

import requests

from backend.integrations.base import PullRequestData, ScmProvider
from backend.integrations.registry import provider_registry
from backend.tools.github import approve_pull_request, fetch_pr_file_patches, post_pr_comment


class GitHubScmProvider(ScmProvider):
    key = "github"

    def fetch_pull_request(self, *, repo: str, pr_number: int, token: str) -> PullRequestData:
        parsed = fetch_pr_file_patches(repo, pr_number, token=token)
        return PullRequestData(
            provider=self.key,
            repo=repo,
            pr_number=pr_number,
            title=str(parsed.get("title", "") or ""),
            diff=str(parsed.get("combined_diff", "") or ""),
            changed_files=list(parsed.get("files", []) or []),
            linked_ticket_ids=list(parsed.get("linked_ticket_ids", []) or []),
            branch_name=str(parsed.get("branch_name", "") or ""),
            metadata={"source": "github"},
        )

    def post_comment(self, *, repo: str, pr_number: int, body: str, token: str) -> None:
        post_pr_comment(repo, pr_number, body, token=token)

    def approve_pull_request(self, *, repo: str, pr_number: int, token: str) -> None:
        approve_pull_request(repo, pr_number, token=token)


class _HttpScmProvider(ScmProvider):
    api_base: str = ""

    def fetch_pull_request(self, *, repo: str, pr_number: int, token: str) -> PullRequestData:
        # Placeholder adapter to keep provider contract stable. Real API mapping can be expanded.
        _ = requests.Session()
        return PullRequestData(
            provider=self.key,
            repo=repo,
            pr_number=pr_number,
            title=f"{self.key} PR #{pr_number}",
            diff="",
            changed_files=[],
            metadata={"note": "stub_provider", "api_base": self.api_base},
        )

    def post_comment(self, *, repo: str, pr_number: int, body: str, token: str) -> None:
        return None

    def approve_pull_request(self, *, repo: str, pr_number: int, token: str) -> None:
        return None


class GitLabScmProvider(_HttpScmProvider):
    key = "gitlab"
    api_base = "https://gitlab.com/api/v4"


class BitbucketScmProvider(_HttpScmProvider):
    key = "bitbucket"
    api_base = "https://api.bitbucket.org/2.0"


def register_default_scm_providers() -> None:
    for provider in (GitHubScmProvider(), GitLabScmProvider(), BitbucketScmProvider()):
        provider_registry.register_scm(provider)
