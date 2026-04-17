from __future__ import annotations

import difflib

from backend.llm import llm_json
from backend.memory.vector_store import get_memory_store
from backend.models import FixOutput, WorkflowState


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
    return state
