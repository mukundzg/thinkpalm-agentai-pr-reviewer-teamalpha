from __future__ import annotations

from backend.llm import llm_text
from backend.memory.vector_store import get_memory_store
from backend.models import WorkflowState
from backend.sqlite_store import log_agent_decision


def summary_agent(state: WorkflowState) -> WorkflowState:
    issues = state.issues
    fixed = state.fix_output

    diff_snippet = fixed.patch if fixed and fixed.patch else "No patch generated."
    fallback_comment = "\n".join(
        [
            "### 🔍 Review Summary",
            f"- Found {len(issues)} issues",
            f"- Auto-fix attempts: {state.attempts}",
            f"- Requirement coverage: {float(state.metadata.get('requirement_coverage', 1.0) or 0.0):.2f}",
            "",
            "### ✅ Suggested Fix",
            "```diff",
            diff_snippet[:3000],
            "```",
            "",
            "### ⚠️ Notes",
            f"- Explanation: {fixed.changes_explained if fixed else 'no fix output'}",
        ]
    )
    prompt = f"""
Format a clean GitHub PR comment using this data:
- Issues: {[i.model_dump() for i in issues]}
- Auto-fix attempts: {state.attempts}
- Requirement coverage: {state.metadata.get("requirement_coverage", 1.0)}
- Unmet requirements: {state.metadata.get("unmet_requirements", [])}
- Patch:
{diff_snippet[:3000]}
- Explanation: {fixed.changes_explained if fixed else 'no fix output'}
Use markdown headers and a diff block.
"""
    llm_comment = llm_text(prompt, system="You are a concise PR review summarizer.")
    state.final_comment = llm_comment.strip() or fallback_comment
    run_id = int(state.metadata.get("decision_run_id", 0) or 0)
    step_order = int(state.metadata.get("decision_step_order", 0) or 0) + 1
    state.metadata["decision_step_order"] = step_order
    if run_id:
        log_agent_decision(
            run_id=run_id,
            step_order=step_order,
            agent_name="summarizer",
            decision_type="final_summary",
            severity="medium" if state.issues else "low",
            confidence=0.9,
            decision_goal="Produce concise, actionable PR summary for publication.",
            selected_option="Generate markdown final comment from workflow artifacts.",
            selection_reason=f"Used issues={len(state.issues)}, attempts={state.attempts}, patch_present={bool(fixed and fixed.patch)}.",
            expected_outcome="Readable final comment suitable for PR posting.",
            actual_outcome=f"Final comment length={len(state.final_comment)} characters.",
            next_action="Persist results and optionally publish comment to GitHub.",
            options=[
                {"option_key": "A", "option_text": "Generate final markdown summary", "was_selected": True},
                {"option_key": "B", "option_text": "Skip summary output", "was_selected": False},
            ],
            signals=[
                {"signal_type": "issue_count", "signal_value": len(state.issues)},
                {"signal_type": "attempts", "signal_value": state.attempts},
                {"signal_type": "patch_present", "signal_value": bool(fixed and fixed.patch)},
            ],
            policy_checks=[
                {"policy_name": "escalation_rule", "result": "NOT_TRIGGERED", "notes": "Summary produced without manual escalation."},
            ],
        )

    if issues and fixed:
        get_memory_store().add_pattern(
            item_id=state.review_input.pr_id,
            issue_text="; ".join(i.message for i in issues),
            fix_text=fixed.changes_explained,
            metadata={"repo": state.review_input.repo, "pr": state.review_input.pr_number},
        )

    return state
