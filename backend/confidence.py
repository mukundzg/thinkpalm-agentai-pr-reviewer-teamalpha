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


def _extract_changed_paths(diff: str, changed_files: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    if changed_files:
        for item in changed_files:
            if isinstance(item, dict):
                name = str(item.get("filename", "")).strip()
                if name:
                    paths.append(name)
        if paths:
            return paths
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                raw = parts[3]
                if raw.startswith("b/"):
                    raw = raw[2:]
                paths.append(raw)
    return paths


def _is_business_logic_file(path: str) -> bool:
    p = path.lower()
    if any(token in p for token in ("test", "spec", "fixture", "docs/", "readme", ".md")):
        return False
    code_like = p.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rb", ".php"))
    return code_like


def _detect_semantic_risk(diff: str) -> dict[str, bool]:
    operator_mutation = False
    arithmetic_mutation = False
    control_flow_mutation = False
    conditional_flip = False

    removed_ops: list[str] = []
    added_ops: list[str] = []
    for line in diff.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("-"):
            removed_ops.extend(re.findall(r"(==|!=|<=|>=|\+|-|\*|/|//|%)", line))
            if re.search(r"\b(if|elif|while|for)\b", line):
                control_flow_mutation = True
            if re.search(r"\b(and|or|not)\b", line):
                conditional_flip = True
        elif line.startswith("+"):
            added_ops.extend(re.findall(r"(==|!=|<=|>=|\+|-|\*|/|//|%)", line))
            if re.search(r"\b(if|elif|while|for)\b", line):
                control_flow_mutation = True
            if re.search(r"\b(and|or|not)\b", line):
                conditional_flip = True

    if removed_ops and added_ops and removed_ops != added_ops:
        operator_mutation = True
    if any(op in removed_ops + added_ops for op in ("+", "-", "*", "/", "//", "%")):
        arithmetic_mutation = bool(removed_ops or added_ops)

    return {
        "operator_mutation": operator_mutation,
        "arithmetic_mutation": arithmetic_mutation,
        "control_flow_mutation": control_flow_mutation,
        "conditional_flip": conditional_flip,
    }


def _detect_output_contract_change(diff: str) -> bool:
    added = [line.lower() for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    removed = [line.lower() for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")]
    contract_tokens = ("return ", "response", "json", "payload", "schema", "dict(", "{", "status")
    added_hit = any(any(token in line for token in contract_tokens) for line in added)
    removed_hit = any(any(token in line for token in contract_tokens) for line in removed)
    return added_hit and removed_hit


def _has_downstream_test_evidence(paths: list[str]) -> bool:
    lower = [p.lower() for p in paths]
    return any(("/test" in p or p.startswith("test") or p.endswith("_test.py") or p.endswith(".spec.ts")) for p in lower)


def _build_signals(state: WorkflowState) -> dict[str, Any]:
    issues = state.issues or []
    diff = state.review_input.diff or ""
    added, removed = _count_diff_churn(diff)
    paths = _extract_changed_paths(diff, state.review_input.changed_files)
    semantic = _detect_semantic_risk(diff)
    business_logic_change = any(_is_business_logic_file(path) for path in paths)
    output_contract_change = _detect_output_contract_change(diff)
    downstream_test_evidence = _has_downstream_test_evidence(paths)
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
        "business_logic_change": business_logic_change,
        "output_contract_change": output_contract_change,
        "downstream_test_evidence": downstream_test_evidence,
        "operator_mutation": semantic["operator_mutation"],
        "arithmetic_mutation": semantic["arithmetic_mutation"],
        "control_flow_mutation": semantic["control_flow_mutation"],
        "conditional_flip": semantic["conditional_flip"],
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
    if signals.get("output_contract_change") and not signals.get("downstream_test_evidence"):
        score -= 0.15
    return max(0.0, min(1.0, score))


def annotate_workflow_confidence(state: WorkflowState) -> float:
    signals = _build_signals(state)
    score = compute_confidence_from_signals(signals)
    semantic_risk = bool(
        signals["operator_mutation"] or signals["arithmetic_mutation"] or signals["control_flow_mutation"] or signals["conditional_flip"]
    )
    if signals["output_contract_change"] and not signals["downstream_test_evidence"]:
        semantic_risk = True
    # Keep this adaptive threshold explicit for router logic.
    threshold = 0.4 if (signals["arithmetic_mutation"] or signals["control_flow_mutation"]) else 0.5
    if signals["output_contract_change"] and not signals["downstream_test_evidence"]:
        threshold = min(0.6, threshold + 0.1)
    state.metadata["confidence_signals"] = signals
    state.metadata["confidence_score"] = score
    state.metadata["confidence_pct"] = round(score * 100.0, 1)
    state.metadata["semantic_risk"] = semantic_risk
    state.metadata["business_logic_change"] = bool(signals["business_logic_change"])
    state.metadata["requires_downstream_validation"] = bool(
        signals["output_contract_change"] and not signals["downstream_test_evidence"]
    )
    state.metadata["confidence_threshold"] = threshold
    return score

