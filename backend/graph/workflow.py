from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agents.fixer import fix_generator_agent
from backend.agents.requirements_validator import requirements_validator_agent
from backend.agents.reviewer import review_agent, review_fast_agent
from backend.agents.summarizer import summary_agent
from backend.agents.tester import test_agent
from backend.models import WorkflowState


def _route_after_tester(state: WorkflowState) -> str:
    mode = str(state.metadata.get("review_mode", "fast"))
    if mode == "fast":
        score = float(state.metadata.get("confidence_score", 0.0) or 0.0)
        threshold = float(state.metadata.get("confidence_threshold", 0.5) or 0.5)
        business_logic_change = bool(state.metadata.get("business_logic_change", False))
        semantic_risk = bool(state.metadata.get("semantic_risk", False))
        if business_logic_change or semantic_risk or score < threshold:
            return "escalate"
        return "summarize"
    if state.test_output and state.test_output.status == "fail" and state.attempts < state.max_attempts:
        return "retry"
    return "summarize"


def build_workflow():
    graph = StateGraph(WorkflowState)
    graph.add_node("reviewer_fast", review_fast_agent)
    graph.add_node("reviewer", review_agent)
    graph.add_node("fixer", fix_generator_agent)
    graph.add_node("tester", test_agent)
    graph.add_node("requirements_validator", requirements_validator_agent)
    graph.add_node("summarizer", summary_agent)

    graph.add_edge(START, "reviewer_fast")
    graph.add_edge("reviewer_fast", "requirements_validator")
    graph.add_edge("requirements_validator", "tester")
    graph.add_edge("reviewer", "fixer")
    graph.add_edge("fixer", "tester")
    graph.add_conditional_edges(
        "tester",
        _route_after_tester,
        {"escalate": "reviewer", "retry": "fixer", "summarize": "summarizer"},
    )
    graph.add_edge("summarizer", END)
    return graph.compile()
