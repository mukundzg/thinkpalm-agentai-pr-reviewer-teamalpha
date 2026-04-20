from backend.graph.workflow import build_workflow
from backend.models import FixOutput, Issue, ReviewInput, WorkflowState


def test_workflow_retries_then_summarizes(monkeypatch):
    import backend.graph.workflow as workflow_module

    call_count = {"n": 0}

    def fake_test_agent(state):
        call_count["n"] += 1
        if call_count["n"] == 1:
            state.test_output = {"status": "fail", "errors": ["first run failed"], "command": None}
            state.metadata["confidence_score"] = 0.2
        else:
            state.test_output = {"status": "pass", "errors": [], "command": None}
            state.metadata["confidence_score"] = 0.9
        return state

    def fake_review_fast_agent(state):
        state.issues = [Issue(type="bug", file="a.py", line=1, message="fast issue", severity="high")]
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

    monkeypatch.setattr(workflow_module, "review_fast_agent", fake_review_fast_agent)
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
    assert end_state["attempts"] >= 1
    assert end_state["test_output"] is not None
    status = (
        end_state["test_output"]["status"]
        if isinstance(end_state["test_output"], dict)
        else end_state["test_output"].status
    )
    assert status == "pass"
    assert call_count["n"] == 2
    assert "Review Summary" in end_state["final_comment"] or end_state["final_comment"]


def test_workflow_short_circuits_when_fast_confidence_is_high(monkeypatch):
    import backend.graph.workflow as workflow_module

    call_log = {"reviewer_llm_called": False, "fixer_called": False}

    def fake_test_agent(state):
        state.test_output = {"status": "pass", "errors": [], "command": None}
        state.metadata["confidence_score"] = 0.92
        return state

    def fake_review_fast_agent(state):
        state.issues = []
        return state

    def fake_review_agent(state):
        state.metadata["review_mode"] = "llm_escalated"
        call_log["reviewer_llm_called"] = True
        return state

    def fake_fix_agent(state):
        call_log["fixer_called"] = True
        state.fix_output = FixOutput(fixed_code="print('ok')", patch="--- a\n+++ b", changes_explained="mock fix")
        return state

    def fake_summary_agent(state):
        state.final_comment = "summary-only"
        return state

    monkeypatch.setattr(workflow_module, "review_fast_agent", fake_review_fast_agent)
    monkeypatch.setattr(workflow_module, "review_agent", fake_review_agent)
    monkeypatch.setattr(workflow_module, "fix_generator_agent", fake_fix_agent)
    monkeypatch.setattr(workflow_module, "test_agent", fake_test_agent)
    monkeypatch.setattr(workflow_module, "summary_agent", fake_summary_agent)

    graph = build_workflow()
    start_state = WorkflowState(
        review_input=ReviewInput(
            pr_id="demo/repo#2",
            repo="demo/repo",
            pr_number=2,
            title="demo",
            diff="print('hello')",
        ),
        max_attempts=2,
    )
    end_state = graph.invoke(start_state)
    assert end_state["final_comment"] == "summary-only"
    assert not call_log["reviewer_llm_called"]
    assert not call_log["fixer_called"]


def test_workflow_escalates_on_semantic_risk_even_with_high_confidence(monkeypatch):
    import backend.graph.workflow as workflow_module

    call_log = {"reviewer_llm_called": False}

    def fake_test_agent(state):
        state.test_output = {"status": "pass", "errors": [], "command": None}
        state.metadata["confidence_score"] = 0.95
        state.metadata["confidence_threshold"] = 0.5
        state.metadata["semantic_risk"] = True
        state.metadata["business_logic_change"] = False
        return state

    def fake_review_fast_agent(state):
        return state

    def fake_review_agent(state):
        state.metadata["review_mode"] = "llm_escalated"
        call_log["reviewer_llm_called"] = True
        return state

    def fake_fix_agent(state):
        state.attempts += 1
        state.fix_output = FixOutput(fixed_code="ok", patch="--- a\n+++ b", changes_explained="fix")
        return state

    def fake_summary_agent(state):
        state.final_comment = "semantic-escalation"
        return state

    monkeypatch.setattr(workflow_module, "review_fast_agent", fake_review_fast_agent)
    monkeypatch.setattr(workflow_module, "review_agent", fake_review_agent)
    monkeypatch.setattr(workflow_module, "fix_generator_agent", fake_fix_agent)
    monkeypatch.setattr(workflow_module, "test_agent", fake_test_agent)
    monkeypatch.setattr(workflow_module, "summary_agent", fake_summary_agent)

    graph = build_workflow()
    start_state = WorkflowState(
        review_input=ReviewInput(pr_id="demo/repo#3", repo="demo/repo", pr_number=3, title="demo", diff="x"),
        max_attempts=1,
    )
    graph.invoke(start_state)
    assert call_log["reviewer_llm_called"]


def test_workflow_escalates_on_business_logic_change_even_with_high_confidence(monkeypatch):
    import backend.graph.workflow as workflow_module

    call_log = {"reviewer_llm_called": False}

    def fake_test_agent(state):
        state.test_output = {"status": "pass", "errors": [], "command": None}
        state.metadata["confidence_score"] = 0.91
        state.metadata["confidence_threshold"] = 0.5
        state.metadata["semantic_risk"] = False
        state.metadata["business_logic_change"] = True
        return state

    def fake_review_fast_agent(state):
        return state

    def fake_review_agent(state):
        state.metadata["review_mode"] = "llm_escalated"
        call_log["reviewer_llm_called"] = True
        return state

    def fake_fix_agent(state):
        state.attempts += 1
        return state

    def fake_summary_agent(state):
        state.final_comment = "business-logic-escalation"
        return state

    monkeypatch.setattr(workflow_module, "review_fast_agent", fake_review_fast_agent)
    monkeypatch.setattr(workflow_module, "review_agent", fake_review_agent)
    monkeypatch.setattr(workflow_module, "fix_generator_agent", fake_fix_agent)
    monkeypatch.setattr(workflow_module, "test_agent", fake_test_agent)
    monkeypatch.setattr(workflow_module, "summary_agent", fake_summary_agent)

    graph = build_workflow()
    start_state = WorkflowState(
        review_input=ReviewInput(pr_id="demo/repo#4", repo="demo/repo", pr_number=4, title="demo", diff="x"),
        max_attempts=1,
    )
    graph.invoke(start_state)
    assert call_log["reviewer_llm_called"]


def test_workflow_uses_adaptive_threshold(monkeypatch):
    import backend.graph.workflow as workflow_module

    call_log = {"reviewer_llm_called": False}

    def fake_test_agent(state):
        state.test_output = {"status": "pass", "errors": [], "command": None}
        state.metadata["confidence_score"] = 0.45
        state.metadata["confidence_threshold"] = 0.4
        state.metadata["semantic_risk"] = False
        state.metadata["business_logic_change"] = False
        return state

    def fake_review_fast_agent(state):
        return state

    def fake_review_agent(state):
        call_log["reviewer_llm_called"] = True
        return state

    def fake_fix_agent(state):
        state.attempts += 1
        return state

    def fake_summary_agent(state):
        state.final_comment = "threshold-summary"
        return state

    monkeypatch.setattr(workflow_module, "review_fast_agent", fake_review_fast_agent)
    monkeypatch.setattr(workflow_module, "review_agent", fake_review_agent)
    monkeypatch.setattr(workflow_module, "fix_generator_agent", fake_fix_agent)
    monkeypatch.setattr(workflow_module, "test_agent", fake_test_agent)
    monkeypatch.setattr(workflow_module, "summary_agent", fake_summary_agent)

    graph = build_workflow()
    start_state = WorkflowState(
        review_input=ReviewInput(pr_id="demo/repo#5", repo="demo/repo", pr_number=5, title="demo", diff="x"),
        max_attempts=1,
    )
    end_state = graph.invoke(start_state)
    assert end_state["final_comment"] == "threshold-summary"
    assert not call_log["reviewer_llm_called"]
