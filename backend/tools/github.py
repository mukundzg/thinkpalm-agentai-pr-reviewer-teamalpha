from __future__ import annotations

import os
from typing import Any

from github import Github
import requests

from backend.models import ReviewInput


def get_github_client() -> Github:
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise ValueError("GITHUB_TOKEN is required.")
    return Github(token)


def fetch_pr_data(repo_name: str, pr_number: int) -> ReviewInput:
    gh = get_github_client()
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github.v3.diff",
        "Authorization": f"Bearer {token}",
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


def fetch_pr_file_patches(repo_name: str, pr_number: int) -> dict[str, Any]:
    gh = get_github_client()
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

    return {"files": files_payload, "combined_diff": "\n".join(patch_blocks), "title": pr.title or ""}


def fetch_open_prs(repo_name: str, limit: int = 20) -> list[dict[str, Any]]:
    gh = get_github_client()
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


def post_pr_comment(repo_name: str, pr_number: int, body: str) -> None:
    gh = get_github_client()
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    pr.create_issue_comment(body)
