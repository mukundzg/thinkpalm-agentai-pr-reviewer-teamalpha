"""
Startup and runtime preflight: verify multi-project DB layout, encryption readiness,
and that at least one GitHub token + webhook signing material is available.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from backend.secrets_crypto import is_encryption_configured
from backend.sqlite_store import _db_path, init_db, list_projects_public

logger = logging.getLogger(__name__)

REQUIRED_TABLES = frozenset(
    {
        "review_results",
        "agent_runs",
        "github_projects",
        "pr_actions",
        "decision_steps",
        "decision_options",
        "decision_signals",
        "policy_checks",
        "retry_state",
    }
)

REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "github_projects": frozenset(
        {"id", "full_name", "github_token_encrypted", "webhook_secret_encrypted", "created_at", "updated_at"}
    ),
    "agent_runs": frozenset(
        {"id", "pr_id", "repo", "pr_number", "status", "started_at", "finished_at", "project_id"}
    ),
    "pr_actions": frozenset(
        {
            "id",
            "pr_id",
            "repo",
            "pr_number",
            "action_type",
            "action_status",
            "actor",
            "details",
            "run_id",
            "project_id",
            "created_at",
        }
    ),
    "review_results": frozenset({"pr_id", "result_json", "updated_at", "project_id"}),
}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {str(row[1]) for row in cur.fetchall()}


def verify_schema(path: str | Path | None = None) -> tuple[bool, list[str]]:
    """Return (ok, issues) for multi-project + onboarding layout."""
    issues: list[str] = []
    dbp = Path(path or _db_path()).resolve()
    if not dbp.is_file():
        issues.append(f"database file missing: {dbp}")
        return False, issues

    try:
        conn = sqlite3.connect(str(dbp))
    except sqlite3.Error as exc:
        issues.append(f"cannot open sqlite database: {exc}")
        return False, issues
    try:
        with conn:
            names = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            for t in REQUIRED_TABLES:
                if t not in names:
                    issues.append(f"missing table: {t}")
            if issues:
                return False, issues

            for table, cols in REQUIRED_COLUMNS.items():
                present = _table_columns(conn, table)
                missing = cols - present
                if missing:
                    issues.append(f"table {table} missing columns: {sorted(missing)}")
    except sqlite3.Error as exc:
        issues.append(f"sqlite error inspecting schema: {exc}")
        return False, issues

    return (len(issues) == 0), issues


def reinitialize_database_file() -> Path:
    """Delete the SQLite file and rebuild schema (destructive)."""
    dbp = Path(_db_path()).resolve()
    if dbp.is_file():
        try:
            dbp.unlink()
            logger.warning("Preflight removed incompatible database at %s", dbp)
        except OSError as exc:
            logger.error("Preflight could not remove %s: %s", dbp, exc)
            raise
    init_db()
    return dbp


def credential_status() -> dict[str, Any]:
    """Inventory projects + env fallbacks for webhook signing."""
    items = list_projects_public()
    has_tok = any(bool(p.get("has_github_token")) for p in items)
    has_wh_db = any(bool(p.get("has_webhook_secret")) for p in items)
    legacy_wh = bool(os.getenv("GITHUB_WEBHOOK_SECRET", "").strip())
    legacy_tok = bool(os.getenv("GITHUB_TOKEN", "").strip())

    credentials_ready = bool(has_tok and (has_wh_db or legacy_wh))

    return {
        "project_count": len(items),
        "has_project_with_github_token": has_tok,
        "has_project_with_webhook_secret": has_wh_db,
        "legacy_github_token_configured": legacy_tok,
        "legacy_webhook_secret_configured": legacy_wh,
        "credentials_ready": credentials_ready,
    }


def run_startup_preflight() -> dict[str, Any]:
    """
    Verify schema; optionally wipe and recreate DB if incompatible.
    Then record encryption + credential readiness.
    """
    auto_reset = os.getenv("PREFLIGHT_AUTO_REINIT_DB", "true").strip().lower() not in ("0", "false", "no")

    db_path = str(Path(_db_path()).resolve())
    report: dict[str, Any] = {
        "database_path": db_path,
        "schema_ok": False,
        "schema_issues": [],
        "db_reinitialized": False,
        "encryption_configured": is_encryption_configured(),
    }

    ok, issues = verify_schema()
    report["schema_ok"] = ok
    report["schema_issues"] = issues

    if not ok and auto_reset:
        logger.warning("Preflight: schema incompatible, reinitializing DB (%s)", issues)
        try:
            reinitialize_database_file()
            report["db_reinitialized"] = True
            ok2, issues2 = verify_schema()
            report["schema_ok"] = ok2
            report["schema_issues"] = issues2
            if not ok2:
                logger.error("Preflight: schema still invalid after reinit: %s", issues2)
        except OSError:
            report["schema_ok"] = False
    elif not ok:
        logger.error("Preflight: schema invalid and PREFLIGHT_AUTO_REINIT_DB is disabled: %s", issues)

    report.update(credential_status())
    report["structure_ready"] = bool(report["schema_ok"] and report["encryption_configured"])
    report["operations_ready"] = bool(report["structure_ready"] and report["credentials_ready"])

    if report["structure_ready"] and not report["credentials_ready"]:
        logger.warning(
            "Preflight: add at least one GitHub project with a PAT and webhook secret "
            "(or set GITHUB_WEBHOOK_SECRET for legacy webhook verification until projects have secrets)."
        )

    LAST_STARTUP_PREFLIGHT.clear()
    LAST_STARTUP_PREFLIGHT.update(report)
    return report


LAST_STARTUP_PREFLIGHT: dict[str, Any] = {}


def get_preflight_snapshot() -> dict[str, Any]:
    """Latest startup info merged with live credential + encryption flags."""
    snap: dict[str, Any] = dict(LAST_STARTUP_PREFLIGHT)
    snap.update(credential_status())
    snap["encryption_configured"] = is_encryption_configured()
    snap["structure_ready"] = bool(snap.get("schema_ok") and snap["encryption_configured"])
    snap["operations_ready"] = bool(snap["structure_ready"] and snap.get("credentials_ready"))
    return snap
