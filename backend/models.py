from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


IssueType = Literal["bug", "style", "security", "performance", "test", "other"]


class Issue(BaseModel):
    type: IssueType
    file: str
    line: int | None = None
    message: str
    severity: Literal["low", "medium", "high", "critical"] = "medium"


class ReviewInput(BaseModel):
    pr_id: str
    repo: str
    pr_number: int
    title: str = ""
    diff: str
    changed_files: list[dict[str, Any]] = Field(default_factory=list)
    base_sha: str | None = None
    head_sha: str | None = None
    scm_provider: str = "github"
    tracker_provider: str = ""
    linked_ticket_ids: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    ticket_context: list[dict[str, Any]] = Field(default_factory=list)
    linking_metadata: dict[str, Any] = Field(default_factory=dict)
    scm_context: dict[str, Any] = Field(default_factory=dict)


class FixOutput(BaseModel):
    fixed_code: str | None = None
    patch: str | None = None
    changes_explained: str


class TestOutput(BaseModel):
    status: Literal["pass", "fail"]
    errors: list[str] = Field(default_factory=list)
    command: str | None = None


class WorkflowState(BaseModel):
    review_input: ReviewInput
    issues: list[Issue] = Field(default_factory=list)
    fix_output: FixOutput | None = None
    test_output: TestOutput | None = None
    attempts: int = 0
    max_attempts: int = 2
    final_comment: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

