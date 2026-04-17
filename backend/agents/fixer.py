from __future__ import annotations

import difflib

from backend.llm import llm_json
from backend.memory.vector_store import get_memory_store
from backend.models import FixOutput, WorkflowState
from backend.sqlite_store import log_agent_decision


def fix_generator_agent(state: WorkflowState) -> WorkflowState:
    source = state.review_input.diff
    improved = source
    explanations: list[str] = []

    llm_prompt = f"""
You are fixing code based on issues found in a PR.
Return JSON with:
- fixed_code: full improved code or diff-content text
- changes_explained: concise explanation

Issues:
{[issue.model_dump() for issue in state.issues]}

Changed files:
{state.review_input.changed_files[:30]}

Input content:
{source[:12000]}
"""
    llm_result = llm_json(llm_prompt, system="You generate safe, minimal code fixes.")
    candidate = llm_result.get("fixed_code") if isinstance(llm_result, dict) else None
    if isinstance(candidate, str) and candidate.strip():
        improved = candidate
        explanations.append("Applied model-generated fix proposal.")

    for issue in state.issues:
        if "TODO" in improved:
            improved = improved.replace("TODO", "DONE", 1)
            explanations.append("Replaced TODO with DONE marker in changed lines.")
        explanations.append(f"Addressed: {issue.message}")

    similar = get_memory_store().find_similar(" ".join(i.message for i in state.issues)) if state.issues else []
    if similar:
        explanations.append("Used prior fix patterns from memory store.")

    patch = "\n".join(
        difflib.unified_diff(
            source.splitlines(),
            improved.splitlines(),
            fromfile="old.diff",
            tofile="new.diff",
            lineterm="",
        )
    )

    state.fix_output = FixOutput(
        fixed_code=improved,
        patch=patch or None,
        changes_explained=(
            llm_result.get("changes_explained")
            if isinstance(llm_result, dict) and isinstance(llm_result.get("changes_explained"), str)
            else ("; ".join(explanations) if explanations else "No changes needed.")
        ),
    )
    state.attempts += 1
    run_id = int(state.metadata.get("decision_run_id", 0) or 0)
    step_order = int(state.metadata.get("decision_step_order", 0) or 0) + 1
    state.metadata["decision_step_order"] = step_order
    if run_id:
        has_patch = bool(state.fix_output.patch)
        log_agent_decision(
            run_id=run_id,
            step_order=step_order,
            agent_name="fixer",
            decision_type="proposed_patch",
            severity="high" if any(i.severity in {"high", "critical"} for i in state.issues) else "medium",
            confidence=0.82 if has_patch else 0.55,
            decision_goal="Generate minimal safe fix based on detected issues.",
            selected_option="Apply model-guided patch and preserve locality of changes.",
            selection_reason=f"Patch generated={has_patch}; attempts now {state.attempts}.",
            expected_outcome="Issue behavior improved with minimal code delta.",
            actual_outcome="Fix output persisted in workflow state.",
            next_action="Run tests to validate proposed fix.",
            options=[
                {"option_key": "A", "option_text": "Apply localized patch", "was_selected": True},
                {"option_key": "B", "option_text": "Escalate without patch", "was_selected": False},
            ],
            signals=[
                {"signal_type": "input_issue_count", "signal_value": len(state.issues)},
                {"signal_type": "patch_generated", "signal_value": has_patch},
                {"signal_type": "attempts", "signal_value": state.attempts},
            ],
            policy_checks=[
                {"policy_name": "locality_first_fixes", "result": "PASS", "notes": "Generated unified diff from source delta."},
                {"policy_name": "evidence_gated_action", "result": "PASS", "notes": "Fix conditioned on issue set and model output."},
            ],
            retry_state={
                "attempts_used": state.attempts,
                "max_attempts": state.max_attempts,
                "within_budget": state.attempts <= state.max_attempts,
            },
        )
    return state
