from backend.agents.requirements_validator import requirements_validator_agent
from backend.models import ReviewInput, WorkflowState


def test_requirements_validator_surfaces_unmet_requirements():
    state = WorkflowState(
        review_input=ReviewInput(
            pr_id="demo/repo#10",
            repo="demo/repo",
            pr_number=10,
            title="feat",
            diff="add auth middleware and timeout handling",
            requirements=["Add audit logging for admin actions", "Add auth middleware for private routes"],
        )
    )
    result = requirements_validator_agent(state)
    unmet = result.metadata.get("unmet_requirements", [])
    assert len(unmet) == 1
    assert "audit logging" in unmet[0].lower()
    assert result.metadata.get("requirement_coverage", 0) < 1.0
