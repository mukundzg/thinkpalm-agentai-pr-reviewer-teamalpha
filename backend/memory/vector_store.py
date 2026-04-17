from __future__ import annotations

import logging
import os
from typing import Any

import chromadb

logger = logging.getLogger(__name__)


class ReviewMemory:
    def __init__(self, persist_dir: str = "./.chroma"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(name="review_history")

    def add_pattern(self, item_id: str, issue_text: str, fix_text: str, metadata: dict[str, Any] | None = None) -> None:
        meta = metadata or {}
        self.collection.upsert(
            ids=[item_id],
            documents=[f"Issue: {issue_text}\nFix: {fix_text}"],
            metadatas=[meta],
        )

    def find_similar(self, query: str, n_results: int = 3) -> list[str]:
        try:
            result = self.collection.query(query_texts=[query], n_results=n_results)
            docs = result.get("documents", [[]])
            return docs[0] if docs else []
        except Exception:
            # Memory lookup is best-effort and must not fail the review flow.
            logger.exception("Vector memory lookup failed; continuing without similar patterns.")
            return []


_memory_store: ReviewMemory | None = None


def get_memory_store() -> ReviewMemory:
    global _memory_store
    if _memory_store is None:
        _memory_store = ReviewMemory(os.getenv("CHROMA_PATH", "./.chroma"))
    return _memory_store
