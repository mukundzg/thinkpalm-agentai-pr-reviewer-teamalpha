from fastapi.testclient import TestClient

from backend.main import app


def test_fetch_result_reads_from_sqlite(monkeypatch, tmp_path):
    db_path = tmp_path / "review_results.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_path))

    import backend.main as main_module
    import backend.sqlite_store as sqlite_store

    sqlite_store.init_db()

    def fake_run(review_input):
        return {"pr_id": review_input.pr_id, "final_comment": "stored in sqlite"}

    monkeypatch.setattr(main_module, "_run_review", fake_run)

    client = TestClient(app)
    review_payload = {
        "pr_id": "demo/repo#77",
        "repo": "demo/repo",
        "pr_number": 77,
        "title": "demo",
        "diff": "diff --git a/a.py b/a.py",
    }
    # Manual run API returns result. We also persist explicitly for deterministic test.
    res = client.post("/review", json=review_payload)
    assert res.status_code == 200
    sqlite_store.save_review_result("demo/repo#77", res.json()["result"])

    fetched = client.get("/results/demo%2Frepo%2377")
    assert fetched.status_code == 200
    assert fetched.json()["final_comment"] == "stored in sqlite"
