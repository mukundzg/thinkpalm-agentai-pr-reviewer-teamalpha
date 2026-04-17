from backend.graph.workflow import build_workflow
from backend.models import FixOutput, Issue, ReviewInput, WorkflowState


def test_workflow_retries_then_summarizes(monkeypatch):
    import backend.graph.workflow as workflow_module

    call_count = {"n": 0}

    def fake_test_agent(state):
        call_count["n"] += 1
        if call_count["n"] == 1:
            state.test_output = {"status": "fail", "errors": ["first run failed"], "command": None}
        else:
            state.test_output = {"status": "pass", "errors": [], "command": None}
        return state

    def fake_review_agent(state):
        state.issues = [Issue(type="bug", file="a.py", line=1, message="mock issue", severity="high")]
        return state

    def fake_fix_agent(state):
        state.attempts += 1
        state.fix_output = FixOutput(fixed_code="print('ok')", patch="--- a\n+++ b", changes_explained="mock fix")
        return state

    def fake_summary_agent(state):
        state.final_comment = "### 🔍 Review Summary\n- mocked"
        return state

    monkeypatch.setattr(workflow_module, "review_agent", fake_review_agent)
    monkeypatch.setattr(workflow_module, "fix_generator_agent", fake_fix_agent)
    monkeypatch.setattr(workflow_module, "test_agent", fake_test_agent)
    monkeypatch.setattr(workflow_module, "summary_agent", fake_summary_agent)

    graph = build_workflow()
    start_state = WorkflowState(
        review_input=ReviewInput(
            pr_id="demo/repo#1",
            repo="demo/repo",
            pr_number=1,
            title="demo",
            diff="print('hello') # TODO",
        ),
        max_attempts=2,
    )
    end_state = graph.invoke(start_state)
    assert end_state["attempts"] >= 2
    assert end_state["test_output"] is not None
    status = (
        end_state["test_output"]["status"]
        if isinstance(end_state["test_output"], dict)
        else end_state["test_output"].status
    )
    assert status == "pass"
    assert "Review Summary" in end_state["final_comment"] or end_state["final_comment"]
