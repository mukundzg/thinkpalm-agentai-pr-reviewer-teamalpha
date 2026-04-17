from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agents.fixer import fix_generator_agent
from backend.agents.reviewer import review_agent
from backend.agents.summarizer import summary_agent
from backend.agents.tester import test_agent
from backend.models import WorkflowState


def _should_retry(state: WorkflowState) -> str:
    if state.test_output and state.test_output.status == "fail" and state.attempts < state.max_attempts:
        return "retry"
    return "summarize"


def build_workflow():
    graph = StateGraph(WorkflowState)
    graph.add_node("reviewer", review_agent)
    graph.add_node("fixer", fix_generator_agent)
    graph.add_node("tester", test_agent)
    graph.add_node("summarizer", summary_agent)

    graph.add_edge(START, "reviewer")
    graph.add_edge("reviewer", "fixer")
    graph.add_edge("fixer", "tester")
    graph.add_conditional_edges("tester", _should_retry, {"retry": "fixer", "summarize": "summarizer"})
    graph.add_edge("summarizer", END)
    return graph.compile()
