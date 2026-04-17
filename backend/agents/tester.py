from __future__ import annotations

from backend.models import WorkflowState
from backend.tools.sandbox import run_tests_in_sandbox


def test_agent(state: WorkflowState) -> WorkflowState:
    test_output = run_tests_in_sandbox(".")
    state.test_output = test_output
    return state
