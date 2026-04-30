from __future__ import annotations

from backend.models import Issue, WorkflowState
from backend.sqlite_store import log_agent_decision


def requirements_validator_agent(state: WorkflowState) -> WorkflowState:
    requirements = list(state.review_input.requirements or [])
    diff = (state.review_input.diff or "").lower()
    unmet: list[str] = []
    for requirement in requirements:
        key_tokens = [token for token in requirement.lower().split() if len(token) > 4][:3]
        if key_tokens and not any(token in diff for token in key_tokens):
            unmet.append(requirement)

    if unmet:
        for req in unmet:
            state.issues.append(
                Issue(
                    type="other",
                    file="requirements",
                    line=None,
                    message=f"Potentially unmet requirement: {req}",
                    severity="medium",
                )
            )
    coverage = 1.0 if not requirements else max(0.0, (len(requirements) - len(unmet)) / float(len(requirements)))
    state.metadata["requirement_coverage"] = coverage
    state.metadata["unmet_requirements"] = unmet

    run_id = int(state.metadata.get("decision_run_id", 0) or 0)
    step_order = int(state.metadata.get("decision_step_order", 0) or 0) + 1
    state.metadata["decision_step_order"] = step_order
    if run_id:
        log_agent_decision(
            run_id=run_id,
            step_order=step_order,
            agent_name="requirements_validator",
            decision_type="requirement_validation",
            severity="medium" if unmet else "low",
            confidence=0.7,
            decision_goal="Validate PR changes against ticket requirements.",
            selected_option="Match requirement keywords against PR diff context.",
            selection_reason=f"requirements={len(requirements)}, unmet={len(unmet)}",
            expected_outcome="Surface unmet requirements before final summary.",
            actual_outcome=f"coverage={coverage:.2f}",
            next_action="Continue workflow routing with enriched metadata.",
        )
    return state
