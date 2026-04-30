from __future__ import annotations

from backend.confidence import annotate_workflow_confidence
from backend.models import WorkflowState
from backend.sqlite_store import log_agent_decision
from backend.tools.sandbox import run_tests_in_sandbox


def test_agent(state: WorkflowState) -> WorkflowState:
    test_output = run_tests_in_sandbox(".")
    state.test_output = test_output
    score = annotate_workflow_confidence(state)
    confidence_pct = float(state.metadata.get("confidence_pct", 0.0))
    run_id = int(state.metadata.get("decision_run_id", 0) or 0)
    step_order = int(state.metadata.get("decision_step_order", 0) or 0) + 1
    state.metadata["decision_step_order"] = step_order
    if run_id:
        is_fail = test_output.status == "fail"
        retry_possible = is_fail and state.attempts < state.max_attempts
        log_agent_decision(
            run_id=run_id,
            step_order=step_order,
            agent_name="tester",
            decision_type="verification_result",
            severity="high" if is_fail else "low",
            confidence=score,
            decision_goal="Validate patch behavior by running tests.",
            selected_option="Run sandbox tests and branch workflow by outcome.",
            selection_reason=(
                f"Test status={test_output.status}; retry_possible={retry_possible}; "
                f"confidence={confidence_pct:.1f}%."
            ),
            expected_outcome="Clear pass/fail signal for retry or summarize path.",
            actual_outcome=f"Tests {test_output.status}; errors={len(test_output.errors)}.",
            next_action="Retry fixer step." if retry_possible else "Proceed to summarizer.",
            options=[
                {"option_key": "A", "option_text": "Retry when tests fail and budget remains", "was_selected": retry_possible},
                {"option_key": "B", "option_text": "Summarize current state", "was_selected": not retry_possible},
            ],
            signals=[
                {"signal_type": "test_status", "signal_value": test_output.status},
                {"signal_type": "error_count", "signal_value": len(test_output.errors)},
                {"signal_type": "command", "signal_value": test_output.command or ""},
                {"signal_type": "confidence_score", "signal_value": score},
                {"signal_type": "confidence_pct", "signal_value": confidence_pct},
                {
                    "signal_type": "requires_downstream_validation",
                    "signal_value": bool(state.metadata.get("requires_downstream_validation", False)),
                },
            ],
            policy_checks=[
                {"policy_name": "verification_loop", "result": "PASS", "notes": "Executed sandbox tests after fix."},
                {
                    "policy_name": "retry_budget",
                    "result": "PASS" if state.attempts <= state.max_attempts else "FAIL",
                    "notes": f"attempts={state.attempts}, max={state.max_attempts}",
                },
                {
                    "policy_name": "downstream_contract_validation",
                    "result": "WARN" if state.metadata.get("requires_downstream_validation", False) else "PASS",
                    "notes": (
                        "Output contract changed without downstream test evidence."
                        if state.metadata.get("requires_downstream_validation", False)
                        else "No downstream contract validation gap detected."
                    ),
                },
            ],
            retry_state={
                "attempts_used": state.attempts,
                "max_attempts": state.max_attempts,
                "within_budget": state.attempts <= state.max_attempts,
            },
        )
    return state
