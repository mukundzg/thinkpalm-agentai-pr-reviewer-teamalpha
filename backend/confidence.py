from __future__ import annotations

import re
from typing import Any

from backend.models import WorkflowState


def _count_diff_churn(diff: str) -> tuple[int, int]:
    added = 0
    removed = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _count_changed_files(diff: str, changed_files: list[dict[str, Any]]) -> int:
    if changed_files:
        return len(changed_files)
    files: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                files.add(parts[2])
    return len(files)


def _build_signals(state: WorkflowState) -> dict[str, Any]:
    issues = state.issues or []
    diff = state.review_input.diff or ""
    added, removed = _count_diff_churn(diff)
    return {
        "test_pass": bool(state.test_output and state.test_output.status == "pass"),
        "issue_count": len(issues),
        "high_count": sum(1 for i in issues if i.severity == "high"),
        "critical_count": sum(1 for i in issues if i.severity == "critical"),
        "lint_count": int(state.metadata.get("lint_issue_count", 0) or 0),
        "diff_lines_added": added,
        "diff_lines_removed": removed,
        "changed_files": _count_changed_files(diff, state.review_input.changed_files),
        "llm_ok": bool(state.metadata.get("review_model_raw")),
    }


def compute_confidence_from_signals(signals: dict[str, Any]) -> float:
    test_component = 1.0 if signals["test_pass"] else 0.0

    sev_penalty = min(1.0, 0.35 * float(signals["critical_count"]) + 0.2 * float(signals["high_count"]))
    severity_component = 1.0 - sev_penalty

    issue_component = max(0.0, 1.0 - min(1.0, float(signals["issue_count"]) / 8.0))
    lint_component = max(0.0, 1.0 - min(1.0, float(signals["lint_count"]) / 10.0))

    churn = float(signals["diff_lines_added"]) + float(signals["diff_lines_removed"])
    churn_component = max(0.0, 1.0 - min(1.0, churn / 500.0))

    files_component = max(0.0, 1.0 - min(1.0, float(signals["changed_files"]) / 20.0))

    score = (
        0.40 * test_component
        + 0.20 * severity_component
        + 0.15 * issue_component
        + 0.05 * lint_component
        + 0.10 * churn_component
        + 0.10 * files_component
    )
    return max(0.0, min(1.0, score))


def annotate_workflow_confidence(state: WorkflowState) -> float:
    signals = _build_signals(state)
    score = compute_confidence_from_signals(signals)
    state.metadata["confidence_signals"] = signals
    state.metadata["confidence_score"] = score
    state.metadata["confidence_pct"] = round(score * 100.0, 1)
    return score

