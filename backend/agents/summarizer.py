from __future__ import annotations

from backend.llm import llm_text
from backend.memory.vector_store import get_memory_store
from backend.models import WorkflowState


def summary_agent(state: WorkflowState) -> WorkflowState:
    issues = state.issues
    fixed = state.fix_output
    tested = state.test_output

    diff_snippet = fixed.patch if fixed and fixed.patch else "No patch generated."
    fallback_comment = "\n".join(
        [
            "### 🔍 Review Summary",
            f"- Found {len(issues)} issues",
            f"- Auto-fix attempts: {state.attempts}",
            "",
            "### ✅ Suggested Fix",
            "```diff",
            diff_snippet[:3000],
            "```",
            "",
            "### ⚠️ Notes",
            f"- Tests: {tested.status if tested else 'not run'}",
            f"- Errors: {', '.join(tested.errors) if tested and tested.errors else 'none'}",
            f"- Explanation: {fixed.changes_explained if fixed else 'no fix output'}",
        ]
    )
    prompt = f"""
Format a clean GitHub PR comment using this data:
- Issues: {[i.model_dump() for i in issues]}
- Auto-fix attempts: {state.attempts}
- Patch:
{diff_snippet[:3000]}
- Test status: {tested.status if tested else 'not run'}
- Test errors: {tested.errors if tested else []}
- Explanation: {fixed.changes_explained if fixed else 'no fix output'}
Use markdown headers and a diff block.
"""
    llm_comment = llm_text(prompt, system="You are a concise PR review summarizer.")
    state.final_comment = llm_comment.strip() or fallback_comment

    if issues and fixed:
        get_memory_store().add_pattern(
            item_id=state.review_input.pr_id,
            issue_text="; ".join(i.message for i in issues),
            fix_text=fixed.changes_explained,
            metadata={"repo": state.review_input.repo, "pr": state.review_input.pr_number},
        )

    return state
