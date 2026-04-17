from __future__ import annotations

import json

from backend.llm import llm_json
from backend.models import Issue, WorkflowState
from backend.tools.linter import run_linter


def _normalize_issue_type(issue_type: str | None) -> str:
    allowed = {"bug", "style", "security", "performance", "test", "other"}
    if issue_type in allowed:
        return issue_type
    return "other"


def _is_parser_noise(item: dict) -> bool:
    message = str(item.get("message", "")).lower()
    symbol = str(item.get("symbol", "")).lower()
    return (
        symbol == "syntax-error"
        or "parsing failed" in message
        or "invalid syntax" in message
        or '"message-id": "e0001"' in message
    )


def review_agent(state: WorkflowState) -> WorkflowState:
    diff = state.review_input.diff
    lint_issues = run_linter(diff, language="python")
    issues: list[Issue] = []

    prompt = f"""
Review this git diff and return JSON with key "issues".
Each issue item must include:
- type: bug|style|security|performance|test|other
- file: string
- line: integer or null
- message: concise text
- severity: low|medium|high|critical

Diff:
{diff[:12000]}

Changed files:
{state.review_input.changed_files[:30]}
"""
    model_response = llm_json(prompt)
    llm_issues = model_response.get("issues", []) if isinstance(model_response, dict) else []
    for item in llm_issues:
        if isinstance(item, dict) and _is_parser_noise(item):
            continue
        try:
            issues.append(Issue(**item))
        except Exception:
            continue

    for item in lint_issues:
        if _is_parser_noise(item):
            continue
        issues.append(
            Issue(
                type=_normalize_issue_type(item.get("type")),
                file="diff_input",
                line=item.get("line"),
                message=item.get("message", "Potential issue found."),
                severity="medium",
            )
        )

    if not issues and "TODO" in diff:
        issues.append(
            Issue(
                type="style",
                file="diff_input",
                line=None,
                message="TODO markers present in changes.",
                severity="low",
            )
        )

    # Keep deterministic metadata for downstream debugging.
    state.metadata["review_model_raw"] = json.dumps(model_response)[:2000] if model_response else ""
    state.issues = issues
    return state
