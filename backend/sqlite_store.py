from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from fastapi.encoders import jsonable_encoder


def _db_path() -> str:
    return os.getenv("SQLITE_DB_PATH", "./review_results.db")


def init_db() -> None:
    with sqlite3.connect(_db_path()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS review_results (
                pr_id TEXT PRIMARY KEY,
                result_json TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def save_review_result(pr_id: str, result_payload: dict[str, Any]) -> None:
    serializable_payload = jsonable_encoder(result_payload)
    with sqlite3.connect(_db_path()) as conn:
        conn.execute(
            """
            INSERT INTO review_results (pr_id, result_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(pr_id) DO UPDATE SET
                result_json=excluded.result_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (pr_id, json.dumps(serializable_payload)),
        )
        conn.commit()


def get_review_result(pr_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(_db_path()) as conn:
        row = conn.execute(
            "SELECT result_json FROM review_results WHERE pr_id = ?",
            (pr_id,),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return {"raw_result": row[0]}
