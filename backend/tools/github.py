from __future__ import annotations

import os
from typing import Any

from github import Github
import requests

from backend.models import ReviewInput


def get_github_client(token: str | None = None) -> Github:
    tok = (token if token is not None else os.getenv("GITHUB_TOKEN", "")).strip()
    if not tok:
        raise ValueError("GitHub token is required.")
    return Github(tok)


def fetch_pr_data(repo_name: str, pr_number: int, *, token: str | None = None) -> ReviewInput:
    gh = get_github_client(token)
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    auth_tok = (token if token is not None else os.getenv("GITHUB_TOKEN", "")).strip()
    headers = {
        "Accept": "application/vnd.github.v3.diff",
        "Authorization": f"Bearer {auth_tok}",
    }
    response = requests.get(pr.diff_url, headers=headers, timeout=20)
    response.raise_for_status()
    return ReviewInput(
        pr_id=f"{repo_name}#{pr_number}",
        repo=repo_name,
        pr_number=pr_number,
        title=pr.title or "",
        diff=response.text,
        base_sha=pr.base.sha if pr.base else None,
        head_sha=pr.head.sha if pr.head else None,
    )


def fetch_pr_file_patches(repo_name: str, pr_number: int, *, token: str | None = None) -> dict[str, Any]:
    gh = get_github_client(token)
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)

    files_payload: list[dict[str, Any]] = []
    patch_blocks: list[str] = []
    for f in pr.get_files():
        patch = f.patch or ""
        files_payload.append(
            {
                "filename": f.filename,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions,
                "changes": f.changes,
                "patch": patch,
            }
        )
        if patch:
            patch_blocks.append(f"diff --git a/{f.filename} b/{f.filename}\n{patch}")

    linked_ticket_ids: list[str] = []
    if pr.body:
        for token in str(pr.body).split():
            if token.startswith("#") and token[1:].isdigit():
                linked_ticket_ids.append(token)
    return {
        "files": files_payload,
        "combined_diff": "\n".join(patch_blocks),
        "title": pr.title or "",
        "branch_name": pr.head.ref if pr.head else "",
        "linked_ticket_ids": linked_ticket_ids,
    }
    


def fetch_open_prs(repo_name: str, limit: int = 20, *, token: str | None = None) -> list[dict[str, Any]]:
    gh = get_github_client(token)
    repo = gh.get_repo(repo_name)
    pulls = repo.get_pulls(state="open", sort="updated", direction="desc")
    output: list[dict[str, Any]] = []
    for idx, pr in enumerate(pulls):
        if idx >= limit:
            break
        output.append(
            {
                "id": pr.id,
                "number": pr.number,
                "title": pr.title or "",
                "repo": repo_name,
                "pr_id": f"{repo_name}#{pr.number}",
                "base_sha": pr.base.sha if pr.base else None,
                "head_sha": pr.head.sha if pr.head else None,
            }
        )
    return output


def post_pr_comment(repo_name: str, pr_number: int, body: str, *, token: str | None = None) -> None:
    gh = get_github_client(token)
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    pr.create_issue_comment(body)


def approve_pull_request(repo_name: str, pr_number: int, *, token: str | None = None) -> None:
    gh = get_github_client(token)
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    head_commit = repo.get_commit(pr.head.sha)
    pr.create_review(event="APPROVE", commit=head_commit)
