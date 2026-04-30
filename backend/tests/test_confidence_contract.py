from backend.confidence import annotate_workflow_confidence
from backend.main import _should_fetch_full_tracker_context
from backend.models import ReviewInput, WorkflowState


def test_tracker_context_gate_skips_full_fetch_for_docs_only_changes():
    review_input = ReviewInput(
        pr_id="demo/repo#101",
        repo="demo/repo",
        pr_number=101,
        title="docs: update readme",
        diff="diff --git a/README.md b/README.md\n+update docs",
        changed_files=[{"filename": "README.md"}],
    )
    fetch_full, reason = _should_fetch_full_tracker_context(review_input)
    assert fetch_full is False
    assert reason == "docs_or_tests_only"


def test_confidence_requires_downstream_validation_for_contract_changes_without_tests():
    state = WorkflowState(
        review_input=ReviewInput(
            pr_id="demo/repo#202",
            repo="demo/repo",
            pr_number=202,
            title="Change API output payload",
            diff=(
                "diff --git a/src/service.py b/src/service.py\n"
                "@@\n"
                "-    return {'status': 'ok', 'data': data}\n"
                "+    return {'status': 'ok', 'result': data, 'version': 2}\n"
            ),
            changed_files=[{"filename": "src/service.py"}],
        )
    )
    annotate_workflow_confidence(state)
    assert state.metadata.get("requires_downstream_validation") is True
    assert state.metadata.get("semantic_risk") is True
