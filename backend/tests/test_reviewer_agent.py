from backend.agents.reviewer import review_agent
from backend.models import ReviewInput, WorkflowState


def test_reviewer_detects_division_function_multiplication(monkeypatch):
    def fake_llm_json(*args, **kwargs):
        return {"issues": []}

    def fake_run_linter(*args, **kwargs):
        return []

    monkeypatch.setattr("backend.agents.reviewer.llm_json", fake_llm_json)
    monkeypatch.setattr("backend.agents.reviewer.run_linter", fake_run_linter)

    diff = """diff --git a/src/calculator-assessment b/src/calculator-assessment
+++ b/src/calculator-assessment
@@
+def div(n1, n2):
+    return n1 * n2
"""
    state = WorkflowState(
        review_input=ReviewInput(
            pr_id="demo/repo#42",
            repo="demo/repo",
            pr_number=42,
            diff=diff,
        )
    )

    updated = review_agent(state)
    assert any(
        issue.type == "bug" and "multiply instead of divide" in issue.message.lower() for issue in updated.issues
    )
