from __future__ import annotations

import json

from backend.llm import llm_json
from backend.models import Issue, WorkflowState
from backend.sqlite_store import log_agent_decision
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
    run_id = int(state.metadata.get("decision_run_id", 0) or 0)
    step_order = int(state.metadata.get("decision_step_order", 0) or 0) + 1
    state.metadata["decision_step_order"] = step_order
    if run_id:
        high_severity_count = sum(1 for issue in issues if issue.severity in {"high", "critical"})
        log_agent_decision(
            run_id=run_id,
            step_order=step_order,
            agent_name="reviewer",
            decision_type="issue_assessment",
            severity="high" if high_severity_count else ("medium" if issues else "low"),
            confidence=0.8 if issues else 0.65,
            decision_goal="Identify actionable issues in PR diff.",
            selected_option="Report detected issues and pass context to fixer.",
            selection_reason=f"Detected {len(issues)} issue(s) using model + lint signals.",
            expected_outcome="Downstream fixer receives actionable issue list.",
            actual_outcome=f"{len(issues)} issue(s) stored in workflow state.",
            next_action="Invoke fixer with current issue set.",
            options=[
                {"option_key": "A", "option_text": "Report issues and continue", "was_selected": True},
                {"option_key": "B", "option_text": "Stop due to no issues", "was_selected": False},
            ],
            signals=[
                {"signal_type": "issue_count", "signal_value": len(issues)},
                {"signal_type": "lint_issue_count", "signal_value": len(lint_issues)},
                {"signal_type": "changed_files_count", "signal_value": len(state.review_input.changed_files)},
            ],
            policy_checks=[
                {
                    "policy_name": "severity_first_prioritization",
                    "result": "PASS",
                    "notes": f"High/critical count={high_severity_count}",
                },
                {"policy_name": "evidence_gated_action", "result": "PASS", "notes": "Model and linter signals used."},
            ],
        )
    return state
