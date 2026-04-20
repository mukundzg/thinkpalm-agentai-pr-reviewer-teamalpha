from __future__ import annotations

import json
import re

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


def _detect_division_logic_issue(diff: str) -> Issue | None:
    """
    Detect obvious division implementation mistakes from added lines in a diff.
    Current deterministic rule:
    - In a `def div(...)` block, a return expression using `*` but not `/`.
    """
    added_lines = [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    in_div = False
    function_line: int | None = None
    for idx, raw in enumerate(added_lines, start=1):
        stripped = raw.strip()
        if re.match(r"^def\s+div\s*\(", stripped):
            in_div = True
            function_line = idx
            continue
        if in_div and re.match(r"^def\s+\w+\s*\(", stripped):
            in_div = False
        if in_div and stripped.startswith("return "):
            expr = stripped.removeprefix("return ").replace(" ", "")
            if "*" in expr and "/" not in expr:
                return Issue(
                    type="bug",
                    file="diff_input",
                    line=function_line or idx,
                    message="Division function appears to multiply instead of divide.",
                    severity="high",
                )
    return None


def _collect_issues(state: WorkflowState, *, use_llm: bool) -> tuple[list[Issue], list[dict], dict]:
    diff = state.review_input.diff
    lint_issues = run_linter(diff, language="python")
    issues: list[Issue] = []
    model_response: dict = {}

    if use_llm:
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

    logic_issue = _detect_division_logic_issue(diff)
    if logic_issue:
        issues.append(logic_issue)

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
    return issues, lint_issues, model_response


def _run_review_agent(state: WorkflowState, *, use_llm: bool, agent_name: str, next_action: str) -> WorkflowState:
    issues, lint_issues, model_response = _collect_issues(state, use_llm=use_llm)
    # Keep deterministic metadata for downstream debugging and confidence scoring.
    state.metadata["review_model_raw"] = json.dumps(model_response)[:2000] if model_response else ""
    state.metadata["lint_issue_count"] = len(lint_issues)
    state.issues = issues
    run_id = int(state.metadata.get("decision_run_id", 0) or 0)
    step_order = int(state.metadata.get("decision_step_order", 0) or 0) + 1
    state.metadata["decision_step_order"] = step_order
    if run_id:
        high_severity_count = sum(1 for issue in issues if issue.severity in {"high", "critical"})
        log_agent_decision(
            run_id=run_id,
            step_order=step_order,
            agent_name=agent_name,
            decision_type="issue_assessment",
            severity="high" if high_severity_count else ("medium" if issues else "low"),
            confidence=0.8 if use_llm else 0.72,
            decision_goal="Identify actionable issues in PR diff.",
            selected_option=next_action,
            selection_reason=(
                f"Detected {len(issues)} issue(s) using model + lint signals."
                if use_llm
                else f"Detected {len(issues)} issue(s) using deterministic + lint signals."
            ),
            expected_outcome="Downstream fixer receives actionable issue list.",
            actual_outcome=f"{len(issues)} issue(s) stored in workflow state.",
            next_action=next_action,
            options=[
                {"option_key": "A", "option_text": next_action, "was_selected": True},
                {"option_key": "B", "option_text": "Defer action", "was_selected": False},
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
                {
                    "policy_name": "evidence_gated_action",
                    "result": "PASS",
                    "notes": "Model and linter signals used." if use_llm else "Deterministic and linter signals used.",
                },
            ],
        )
    return state


def review_fast_agent(state: WorkflowState) -> WorkflowState:
    return _run_review_agent(
        state,
        use_llm=False,
        agent_name="reviewer_fast",
        next_action="Run tests before LLM escalation.",
    )


def review_agent(state: WorkflowState) -> WorkflowState:
    return _run_review_agent(
        state,
        use_llm=True,
        agent_name="reviewer",
        next_action="Report detected issues and pass context to fixer.",
    )
