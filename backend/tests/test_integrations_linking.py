from backend.integrations.linking import resolve_ticket_ids


def test_linked_ids_take_precedence():
    ids, meta = resolve_ticket_ids(
        linked_ids=["ABC-123", "#44"],
        pr_title="PROJ-999 implement feature",
        branch_name="feature/PROJ-999",
    )
    assert ids == ["ABC-123", "#44"]
    assert meta["strategy"] == "linked_issues"


def test_key_extraction_fallback_is_used():
    ids, meta = resolve_ticket_ids(
        linked_ids=[],
        pr_title="PROJ-321 add endpoint",
        branch_name="feature/proj-321-api",
    )
    assert "PROJ-321" in ids
    assert meta["strategy"] == "key_extraction_fallback"
