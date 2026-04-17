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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_id TEXT NOT NULL,
                repo TEXT NOT NULL,
                pr_number INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_pr_id ON agent_runs(pr_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                step_order INTEGER NOT NULL,
                agent_name TEXT NOT NULL,
                decision_type TEXT NOT NULL,
                severity TEXT,
                confidence REAL,
                decision_goal TEXT NOT NULL,
                selected_option TEXT NOT NULL,
                selection_reason TEXT NOT NULL,
                expected_outcome TEXT,
                actual_outcome TEXT,
                next_action TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES agent_runs(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_steps_run_id ON decision_steps(run_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                step_id INTEGER NOT NULL,
                option_key TEXT NOT NULL,
                option_text TEXT NOT NULL,
                was_selected INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(step_id) REFERENCES decision_steps(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_options_step_id ON decision_options(step_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                step_id INTEGER NOT NULL,
                signal_type TEXT NOT NULL,
                signal_value TEXT NOT NULL,
                FOREIGN KEY(step_id) REFERENCES decision_steps(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_signals_step_id ON decision_signals(step_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS policy_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                step_id INTEGER NOT NULL,
                policy_name TEXT NOT NULL,
                result TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY(step_id) REFERENCES decision_steps(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_policy_checks_step_id ON policy_checks(step_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS retry_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                step_id INTEGER NOT NULL UNIQUE,
                attempts_used INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL,
                within_budget INTEGER NOT NULL,
                FOREIGN KEY(step_id) REFERENCES decision_steps(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_retry_state_step_id ON retry_state(step_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pr_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_id TEXT NOT NULL,
                repo TEXT NOT NULL,
                pr_number INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                action_status TEXT NOT NULL DEFAULT 'success',
                actor TEXT NOT NULL DEFAULT 'system',
                details TEXT,
                run_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES agent_runs(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_actions_pr_id ON pr_actions(pr_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_actions_run_id ON pr_actions(run_id)")
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


def create_agent_run(pr_id: str, repo: str, pr_number: int) -> int:
    with sqlite3.connect(_db_path()) as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_runs (pr_id, repo, pr_number, status)
            VALUES (?, ?, ?, 'running')
            """,
            (pr_id, repo, pr_number),
        )
        conn.commit()
        return int(cur.lastrowid)


def complete_agent_run(run_id: int, status: str) -> None:
    with sqlite3.connect(_db_path()) as conn:
        conn.execute(
            """
            UPDATE agent_runs
            SET status = ?, finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, run_id),
        )
        conn.commit()


def log_agent_decision(
    *,
    run_id: int,
    step_order: int,
    agent_name: str,
    decision_type: str,
    decision_goal: str,
    selected_option: str,
    selection_reason: str,
    severity: str | None = None,
    confidence: float | None = None,
    expected_outcome: str | None = None,
    actual_outcome: str | None = None,
    next_action: str | None = None,
    options: list[dict[str, Any]] | None = None,
    signals: list[dict[str, Any]] | None = None,
    policy_checks: list[dict[str, Any]] | None = None,
    retry_state: dict[str, Any] | None = None,
) -> int:
    options = options or []
    signals = signals or []
    policy_checks = policy_checks or []
    with sqlite3.connect(_db_path()) as conn:
        cur = conn.execute(
            """
            INSERT INTO decision_steps (
                run_id, step_order, agent_name, decision_type, severity, confidence,
                decision_goal, selected_option, selection_reason, expected_outcome,
                actual_outcome, next_action
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                step_order,
                agent_name,
                decision_type,
                severity,
                confidence,
                decision_goal,
                selected_option,
                selection_reason,
                expected_outcome,
                actual_outcome,
                next_action,
            ),
        )
        step_id = int(cur.lastrowid)
        for item in options:
            conn.execute(
                """
                INSERT INTO decision_options (step_id, option_key, option_text, was_selected)
                VALUES (?, ?, ?, ?)
                """,
                (
                    step_id,
                    str(item.get("option_key", "")),
                    str(item.get("option_text", "")),
                    1 if bool(item.get("was_selected")) else 0,
                ),
            )
        for item in signals:
            raw_value = jsonable_encoder(item.get("signal_value"))
            if isinstance(raw_value, (dict, list)):
                stored_value = json.dumps(raw_value)
            else:
                stored_value = str(raw_value)
            conn.execute(
                """
                INSERT INTO decision_signals (step_id, signal_type, signal_value)
                VALUES (?, ?, ?)
                """,
                (
                    step_id,
                    str(item.get("signal_type", "unknown")),
                    stored_value,
                ),
            )
        for item in policy_checks:
            conn.execute(
                """
                INSERT INTO policy_checks (step_id, policy_name, result, notes)
                VALUES (?, ?, ?, ?)
                """,
                (
                    step_id,
                    str(item.get("policy_name", "")),
                    str(item.get("result", "NOT_TRIGGERED")),
                    str(item.get("notes", "")) or None,
                ),
            )
        if retry_state:
            conn.execute(
                """
                INSERT INTO retry_state (step_id, attempts_used, max_attempts, within_budget)
                VALUES (?, ?, ?, ?)
                """,
                (
                    step_id,
                    int(retry_state.get("attempts_used", 0)),
                    int(retry_state.get("max_attempts", 0)),
                    1 if bool(retry_state.get("within_budget")) else 0,
                ),
            )
        conn.commit()
        return step_id


def _get_decision_run_payload(run_id: int) -> dict[str, Any] | None:
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        run_row = conn.execute(
            """
            SELECT id, pr_id, repo, pr_number, status, started_at, finished_at
            FROM agent_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        if not run_row:
            return None
        run_id = int(run_row["id"])
        step_rows = conn.execute(
            """
            SELECT id, step_order, agent_name, decision_type, severity, confidence,
                   decision_goal, selected_option, selection_reason, expected_outcome,
                   actual_outcome, next_action, created_at
            FROM decision_steps
            WHERE run_id = ?
            ORDER BY step_order ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
        output_steps: list[dict[str, Any]] = []
        for step in step_rows:
            step_id = int(step["id"])
            option_rows = conn.execute(
                """
                SELECT option_key, option_text, was_selected
                FROM decision_options
                WHERE step_id = ?
                ORDER BY id ASC
                """,
                (step_id,),
            ).fetchall()
            signal_rows = conn.execute(
                """
                SELECT signal_type, signal_value
                FROM decision_signals
                WHERE step_id = ?
                ORDER BY id ASC
                """,
                (step_id,),
            ).fetchall()
            policy_rows = conn.execute(
                """
                SELECT policy_name, result, notes
                FROM policy_checks
                WHERE step_id = ?
                ORDER BY id ASC
                """,
                (step_id,),
            ).fetchall()
            retry_row = conn.execute(
                """
                SELECT attempts_used, max_attempts, within_budget
                FROM retry_state
                WHERE step_id = ?
                """,
                (step_id,),
            ).fetchone()
            output_steps.append(
                {
                    "id": step_id,
                    "step_order": step["step_order"],
                    "agent_name": step["agent_name"],
                    "decision_type": step["decision_type"],
                    "severity": step["severity"],
                    "confidence": step["confidence"],
                    "decision_goal": step["decision_goal"],
                    "selected_option": step["selected_option"],
                    "selection_reason": step["selection_reason"],
                    "expected_outcome": step["expected_outcome"],
                    "actual_outcome": step["actual_outcome"],
                    "next_action": step["next_action"],
                    "created_at": step["created_at"],
                    "options": [
                        {
                            "option_key": row["option_key"],
                            "option_text": row["option_text"],
                            "was_selected": bool(row["was_selected"]),
                        }
                        for row in option_rows
                    ],
                    "signals": [{"signal_type": row["signal_type"], "signal_value": row["signal_value"]} for row in signal_rows],
                    "policy_checks": [
                        {
                            "policy_name": row["policy_name"],
                            "result": row["result"],
                            "notes": row["notes"],
                        }
                        for row in policy_rows
                    ],
                    "retry_state": (
                        {
                            "attempts_used": retry_row["attempts_used"],
                            "max_attempts": retry_row["max_attempts"],
                            "within_budget": bool(retry_row["within_budget"]),
                        }
                        if retry_row
                        else None
                    ),
                }
            )
    return {
        "run": {
            "id": run_row["id"],
            "pr_id": run_row["pr_id"],
            "repo": run_row["repo"],
            "pr_number": run_row["pr_number"],
            "status": run_row["status"],
            "started_at": run_row["started_at"],
            "finished_at": run_row["finished_at"],
        },
        "steps": output_steps,
    }


def get_latest_decision_run(pr_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id
            FROM agent_runs
            WHERE pr_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (pr_id,),
        ).fetchone()
    if not row:
        return None
    return _get_decision_run_payload(int(row["id"]))


def get_decision_run_by_id(run_id: int) -> dict[str, Any] | None:
    return _get_decision_run_payload(run_id)


def get_pr_history_summary(limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 500))
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT ar.id, ar.pr_id, ar.repo, ar.pr_number, ar.status, ar.started_at, ar.finished_at
            FROM agent_runs ar
            INNER JOIN (
                SELECT pr_id, MAX(id) AS latest_id
                FROM agent_runs
                GROUP BY pr_id
            ) latest ON latest.latest_id = ar.id
            ORDER BY ar.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [
        {
            "run_id": row["id"],
            "pr_id": row["pr_id"],
            "repo": row["repo"],
            "pr_number": row["pr_number"],
            "status": row["status"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }
        for row in rows
    ]


def get_analysis_history(limit: int = 200) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 1000))
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, pr_id, repo, pr_number, status, started_at, finished_at
            FROM agent_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [
        {
            "run_id": row["id"],
            "pr_id": row["pr_id"],
            "repo": row["repo"],
            "pr_number": row["pr_number"],
            "status": row["status"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }
        for row in rows
    ]


def log_pr_action(
    *,
    pr_id: str,
    repo: str,
    pr_number: int,
    action_type: str,
    action_status: str = "success",
    actor: str = "system",
    details: str | None = None,
    run_id: int | None = None,
) -> int:
    with sqlite3.connect(_db_path()) as conn:
        cur = conn.execute(
            """
            INSERT INTO pr_actions (
                pr_id, repo, pr_number, action_type, action_status, actor, details, run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pr_id,
                repo,
                pr_number,
                action_type,
                action_status,
                actor,
                details,
                run_id,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_pr_actions(pr_id: str, limit: int = 200) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 1000))
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, pr_id, repo, pr_number, action_type, action_status, actor, details, run_id, created_at
            FROM pr_actions
            WHERE pr_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (pr_id, safe_limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "pr_id": row["pr_id"],
            "repo": row["repo"],
            "pr_number": row["pr_number"],
            "action_type": row["action_type"],
            "action_status": row["action_status"],
            "actor": row["actor"],
            "details": row["details"],
            "run_id": row["run_id"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
