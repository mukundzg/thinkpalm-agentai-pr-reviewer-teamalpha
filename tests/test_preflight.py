import os

import pytest

from backend import preflight


def test_verify_schema_passes_after_init(monkeypatch, tmp_path):
    db = tmp_path / "t.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db))
    from backend.sqlite_store import init_db

    init_db()
    ok, issues = preflight.verify_schema(str(db))
    assert ok is True
    assert issues == []


def test_reinit_recreates_schema(monkeypatch, tmp_path):
    db = tmp_path / "broken.db"
    db.write_text("not sqlite", encoding="utf-8")
    monkeypatch.setenv("SQLITE_DB_PATH", str(db))
    monkeypatch.setenv("PREFLIGHT_AUTO_REINIT_DB", "true")
    broken_ok, _ = preflight.verify_schema(str(db))
    assert broken_ok is False

    preflight.reinitialize_database_file()
    ok, issues = preflight.verify_schema(str(db))
    assert ok is True
    assert issues == []


def test_credential_status_reflects_projects(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("APP_SECRET_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "c.db"))
    from backend import secrets_crypto
    from backend.sqlite_store import init_db, insert_github_project

    init_db()
    tok = secrets_crypto.encrypt_secret("ghp_test")
    wh = secrets_crypto.encrypt_secret("whsec_test")
    insert_github_project(full_name="a/b", github_token_encrypted=tok, webhook_secret_encrypted=wh)
    st = preflight.credential_status()
    assert st["project_count"] == 1
    assert st["has_project_with_github_token"] is True
    assert st["has_project_with_webhook_secret"] is True
    assert st["credentials_ready"] is True
