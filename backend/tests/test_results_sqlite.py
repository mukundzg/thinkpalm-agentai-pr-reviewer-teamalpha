from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.main import app


def test_fetch_result_reads_from_sqlite(monkeypatch, tmp_path):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("APP_SECRET_KEY", key)
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "review_results.db"))

    import backend.main as main_module
    import backend.secrets_crypto as secrets_crypto
    import backend.sqlite_store as sqlite_store

    sqlite_store.init_db()
    tok_e = secrets_crypto.encrypt_secret("ghpat-test-token")
    pid = sqlite_store.insert_github_project(
        full_name="demo/repo",
        github_token_encrypted=tok_e,
        webhook_secret_encrypted="",
    )
    assert pid >= 1

    def fake_run(review_input, project_id=None):
        return {"pr_id": review_input.pr_id, "final_comment": "stored in sqlite"}

    monkeypatch.setattr(main_module, "_run_review", fake_run)

    client = TestClient(app)
    review_payload = {
        "project_id": pid,
        "pr_id": "demo/repo#77",
        "repo": "demo/repo",
        "pr_number": 77,
        "title": "demo",
        "diff": "diff --git a/a.py b/a.py",
    }
    res = client.post("/review", json=review_payload)
    assert res.status_code == 200
    sqlite_store.save_review_result("demo/repo#77", res.json()["result"], project_id=pid)

    fetched = client.get("/results/demo%2Frepo%2377")
    assert fetched.status_code == 200
    assert fetched.json()["final_comment"] == "stored in sqlite"
