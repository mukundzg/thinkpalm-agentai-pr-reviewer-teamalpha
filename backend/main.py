from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any
from urllib.parse import parse_qs

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.graph.workflow import build_workflow
from backend.models import ReviewInput, WorkflowState
from backend.sqlite_store import (
    complete_agent_run,
    create_agent_run,
    get_analysis_history,
    get_pr_actions,
    get_decision_run_by_id,
    get_latest_decision_run,
    get_pr_history_summary,
    get_review_result,
    init_db,
    log_pr_action,
    save_review_result,
)
from backend.tools.github import fetch_open_prs, fetch_pr_file_patches, post_pr_comment

load_dotenv()

app = FastAPI(title="PR Review Multi-Agent Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

workflow = build_workflow()
processed_deliveries: set[str] = set()
init_db()


class ManualReviewPayload(BaseModel):
    pr_id: str
    repo: str
    pr_number: int
    title: str = ""
    diff: str


class PostCommentPayload(BaseModel):
    repo: str
    pr_number: int
    body: str


class PrActionPayload(BaseModel):
    repo: str
    pr_number: int
    action_type: str
    action_status: str = "success"
    actor: str = "user"
    details: str = ""
    run_id: int | None = None


def _verify_github_signature(raw_body: bytes, signature_header: str | None) -> None:
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=500, detail="Missing GITHUB_WEBHOOK_SECRET.")
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing signature header.")

    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")


def _run_review(review_input: ReviewInput) -> dict[str, Any]:
    run_id = create_agent_run(review_input.pr_id, review_input.repo, review_input.pr_number)
    initial_state = WorkflowState(review_input=review_input)
    initial_state.metadata["decision_run_id"] = run_id
    initial_state.metadata["decision_step_order"] = 0
    try:
        final_state = workflow.invoke(initial_state)
        if isinstance(final_state, WorkflowState):
            payload = final_state.model_dump()
        elif isinstance(final_state, dict):
            payload = final_state
        else:
            payload = {"result": str(final_state)}
        save_review_result(review_input.pr_id, payload)
        complete_agent_run(run_id, "completed")
        return payload
    except Exception:
        complete_agent_run(run_id, "failed")
        raise


def _parse_github_event(raw_body: bytes, content_type: str | None) -> dict[str, Any]:
    if not raw_body:
        raise HTTPException(status_code=400, detail="Webhook body is empty.")

    body_text = raw_body.decode("utf-8", errors="replace")
    normalized_type = (content_type or "").split(";")[0].strip().lower()

    try:
        if normalized_type == "application/x-www-form-urlencoded":
            form_data = parse_qs(body_text, keep_blank_values=True)
            payload = form_data.get("payload", [""])[0]
            if not payload:
                raise HTTPException(status_code=400, detail="Missing 'payload' in form-encoded webhook body.")
            return json.loads(payload)
        return json.loads(body_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid webhook JSON payload: {exc.msg}") from exc


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
):
    raw_body = await request.body()
    _verify_github_signature(raw_body, x_hub_signature_256)
    event = _parse_github_event(raw_body, request.headers.get("content-type"))

    if x_github_delivery and x_github_delivery in processed_deliveries:
        return {"status": "ignored", "reason": "duplicate delivery"}
    if x_github_delivery:
        processed_deliveries.add(x_github_delivery)

    action = event.get("action")
    pull_request = event.get("pull_request", {})
    repository = event.get("repository", {})
    if action not in {"opened", "synchronize", "reopened"} or not pull_request:
        return {"status": "ignored", "reason": "unsupported action"}

    review_input = ReviewInput(
        pr_id=f"{repository.get('full_name')}#{pull_request.get('number')}",
        repo=repository.get("full_name", ""),
        pr_number=pull_request.get("number", 0),
        title=pull_request.get("title", ""),
        diff="",
        changed_files=[],
        base_sha=pull_request.get("base", {}).get("sha"),
        head_sha=pull_request.get("head", {}).get("sha"),
    )
    try:
        parsed = fetch_pr_file_patches(review_input.repo, review_input.pr_number)
        review_input.diff = parsed.get("combined_diff", "") or ""
        review_input.changed_files = parsed.get("files", []) or []
        review_input.title = parsed.get("title", review_input.title)
    except Exception:
        review_input.diff = pull_request.get("body", "") or ""
    output = _run_review(review_input)
    try:
        post_pr_comment(review_input.repo, review_input.pr_number, output.get("final_comment", ""))
        log_pr_action(
            pr_id=review_input.pr_id,
            repo=review_input.repo,
            pr_number=review_input.pr_number,
            action_type="comment_added",
            action_status="success",
            actor="system",
            details="Auto-posted final comment after webhook-triggered analysis.",
        )
    except Exception:
        log_pr_action(
            pr_id=review_input.pr_id,
            repo=review_input.repo,
            pr_number=review_input.pr_number,
            action_type="comment_added",
            action_status="failed",
            actor="system",
            details="Auto-comment failed after webhook-triggered analysis.",
        )
    return {"status": "ok", "pr_id": review_input.pr_id}


@app.post("/review")
async def manual_review(payload: ManualReviewPayload):
    review_input = ReviewInput(**payload.model_dump())
    output = _run_review(review_input)
    return {"status": "ok", "result": output}


@app.post("/github/post-comment")
async def publish_pr_comment(payload: PostCommentPayload):
    repo_name = payload.repo.strip()
    comment_body = payload.body.strip()
    if not repo_name:
        raise HTTPException(status_code=400, detail="Repository is required.")
    if payload.pr_number <= 0:
        raise HTTPException(status_code=400, detail="PR number must be greater than zero.")
    if not comment_body:
        raise HTTPException(status_code=400, detail="Comment body is required.")

    post_pr_comment(repo_name, payload.pr_number, comment_body)
    log_pr_action(
        pr_id=f"{repo_name}#{payload.pr_number}",
        repo=repo_name,
        pr_number=payload.pr_number,
        action_type="comment_added",
        action_status="success",
        actor="user",
        details="Manual comment posted from UI action.",
    )
    return {"status": "ok", "message": f"Comment posted to {repo_name}#{payload.pr_number}"}


@app.post("/actions/log")
async def record_pr_action(payload: PrActionPayload):
    repo_name = payload.repo.strip()
    if not repo_name:
        raise HTTPException(status_code=400, detail="Repository is required.")
    if payload.pr_number <= 0:
        raise HTTPException(status_code=400, detail="PR number must be greater than zero.")
    action_type = payload.action_type.strip().lower()
    if not action_type:
        raise HTTPException(status_code=400, detail="Action type is required.")
    action_status = payload.action_status.strip().lower() or "success"
    action_id = log_pr_action(
        pr_id=f"{repo_name}#{payload.pr_number}",
        repo=repo_name,
        pr_number=payload.pr_number,
        action_type=action_type,
        action_status=action_status,
        actor=payload.actor.strip() or "user",
        details=payload.details.strip() or None,
        run_id=payload.run_id,
    )
    return {"status": "ok", "action_id": action_id}


@app.get("/results/{pr_id:path}")
async def get_results(pr_id: str):
    result = get_review_result(pr_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No results for this PR.")
    return result


@app.get("/decisions/history/prs")
async def get_pr_history(limit: int = 100):
    return {"items": get_pr_history_summary(limit=limit)}


@app.get("/decisions/history/runs")
async def get_all_analysis_history(limit: int = 200):
    return {"items": get_analysis_history(limit=limit)}


@app.get("/actions/{pr_id:path}")
async def get_actions_for_pr(pr_id: str, limit: int = 200):
    return {"items": get_pr_actions(pr_id, limit=limit)}


@app.get("/decisions/pr/{pr_id:path}")
async def get_decision_history(pr_id: str):
    history = get_latest_decision_run(pr_id)
    if history is None:
        raise HTTPException(status_code=404, detail="No decision history found for this PR.")
    return history


@app.get("/decisions/run/{run_id}")
async def get_decision_history_by_run(run_id: int):
    history = get_decision_run_by_id(run_id)
    if history is None:
        raise HTTPException(status_code=404, detail="No decision history found for this run.")
    return history


@app.get("/github/default-pr")
async def get_default_pr():
    repo_name = os.getenv("GITHUB_REPO", "").strip()
    if not repo_name:
        raise HTTPException(status_code=400, detail="Set GITHUB_REPO in .env as owner/repo.")

    prs = fetch_open_prs(repo_name, limit=1)
    if not prs:
        raise HTTPException(status_code=404, detail=f"No open PRs found for {repo_name}.")

    selected = prs[0]
    parsed = fetch_pr_file_patches(repo_name, selected["number"])
    return {
        "pr_id": selected["pr_id"],
        "repo": repo_name,
        "pr_number": selected["number"],
        "title": parsed.get("title", selected["title"]),
        "diff": parsed.get("combined_diff", ""),
    }


@app.get("/github/open-prs")
async def get_open_prs():
    repo_name = os.getenv("GITHUB_REPO", "").strip()
    if not repo_name:
        raise HTTPException(status_code=400, detail="Set GITHUB_REPO in .env as owner/repo.")

    prs = fetch_open_prs(repo_name, limit=100)
    return {"repo": repo_name, "pull_requests": prs}


@app.get("/github/pr/{pr_number}")
async def get_pr_details(pr_number: int):
    repo_name = os.getenv("GITHUB_REPO", "").strip()
    if not repo_name:
        raise HTTPException(status_code=400, detail="Set GITHUB_REPO in .env as owner/repo.")

    parsed = fetch_pr_file_patches(repo_name, pr_number)
    return {
        "pr_id": f"{repo_name}#{pr_number}",
        "repo": repo_name,
        "pr_number": pr_number,
        "title": parsed.get("title", ""),
        "diff": parsed.get("combined_diff", ""),
    }
