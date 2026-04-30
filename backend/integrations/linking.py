from __future__ import annotations

import re

TICKET_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
LINEAR_KEY_RE = re.compile(r"\b([A-Z]{2,10}-\d+)\b")
GITHUB_ISSUE_RE = re.compile(r"#(\d+)\b")


def extract_ticket_ids_from_text(*values: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value or ""
        for regex in (TICKET_KEY_RE, LINEAR_KEY_RE, GITHUB_ISSUE_RE):
            for match in regex.findall(text):
                token = f"#{match}" if regex is GITHUB_ISSUE_RE else str(match).upper()
                if token not in seen:
                    seen.add(token)
                    out.append(token)
    return out


def resolve_ticket_ids(*, linked_ids: list[str], pr_title: str, branch_name: str) -> tuple[list[str], dict[str, str]]:
    if linked_ids:
        uniq: list[str] = []
        seen: set[str] = set()
        for item in linked_ids:
            norm = item.strip()
            if norm and norm not in seen:
                seen.add(norm)
                uniq.append(norm)
        return uniq, {"strategy": "linked_issues"}
    extracted = extract_ticket_ids_from_text(pr_title, branch_name)
    return extracted, {"strategy": "key_extraction_fallback"}
