import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from backend.main import app


def _signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_webhook_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")
    client = TestClient(app)

    payload = {
        "action": "opened",
        "repository": {"full_name": "demo/repo"},
        "pull_request": {"number": 1, "title": "demo", "base": {"sha": "a"}, "head": {"sha": "b"}},
    }
    body = json.dumps(payload).encode("utf-8")
    res = client.post(
        "/webhook/github",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=bad", "Content-Type": "application/json"},
    )
    assert res.status_code == 401


def test_webhook_accepts_valid_signature_and_dedupes(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")

    import backend.main as main_module

    def fake_fetch(repo, pr):
        return {"files": [{"filename": "a.py", "patch": "@@ -1 +1 @@\n-print(1)\n+print(2)"}], "combined_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-print(1)\n+print(2)", "title": "demo"}

    def fake_run(review_input):
        return {"final_comment": "ok", "review_input": review_input.model_dump()}

    monkeypatch.setattr(main_module, "fetch_pr_file_patches", fake_fetch)
    monkeypatch.setattr(main_module, "_run_review", fake_run)
    monkeypatch.setattr(main_module, "post_pr_comment", lambda *args, **kwargs: None)
    main_module.processed_deliveries.clear()

    client = TestClient(app)
    payload = {
        "action": "opened",
        "repository": {"full_name": "demo/repo"},
        "pull_request": {"number": 1, "title": "demo", "base": {"sha": "a"}, "head": {"sha": "b"}},
    }
    body = json.dumps(payload).encode("utf-8")
    sig = _signature(body, "test-secret")
    headers = {
        "X-Hub-Signature-256": sig,
        "X-GitHub-Delivery": "delivery-1",
        "Content-Type": "application/json",
    }
    first = client.post("/webhook/github", content=body, headers=headers)
    second = client.post("/webhook/github", content=body, headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "ok"
    assert second.status_code == 200
    assert second.json()["status"] == "ignored"


def test_webhook_accepts_form_encoded_payload(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")
    import backend.main as main_module

    def fake_fetch(repo, pr):
        return {"files": [], "combined_diff": "", "title": "demo"}

    def fake_run(review_input):
        return {"final_comment": "ok", "review_input": review_input.model_dump()}

    monkeypatch.setattr(main_module, "fetch_pr_file_patches", fake_fetch)
    monkeypatch.setattr(main_module, "_run_review", fake_run)
    monkeypatch.setattr(main_module, "post_pr_comment", lambda *args, **kwargs: None)

    client = TestClient(app)
    payload = {
        "action": "opened",
        "repository": {"full_name": "demo/repo"},
        "pull_request": {"number": 2, "title": "form-encoded", "base": {"sha": "a"}, "head": {"sha": "b"}},
    }
    body = f"payload={json.dumps(payload)}".encode("utf-8")
    sig = _signature(body, "test-secret")

    res = client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
