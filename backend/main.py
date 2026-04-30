from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from typing import Any
from urllib.parse import parse_qs

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.dotenv_util import upsert_app_secret_key_line
from backend.integrations import provider_registry, register_default_providers, resolve_ticket_ids
from backend.preflight import get_preflight_snapshot, run_startup_preflight
from backend.graph.workflow import build_workflow
from backend.models import ReviewInput, WorkflowState
from backend.secrets_crypto import SecretKeyError, decrypt_secret, encrypt_secret, is_encryption_configured
from backend.sqlite_store import (
    complete_agent_run,
    create_agent_run,
    delete_github_project,
    get_integration_row_by_full_name,
    get_integration_row_by_id,
    get_analysis_history,
    get_decision_run_by_id,
    get_githubproject_row_by_full_name,
    get_githubproject_row_by_id,
    get_latest_decision_run,
    get_pr_actions,
    get_pr_history_summary,
    get_review_result,
    insert_github_project,
    init_db,
    insert_integration,
    list_projects_public,
    list_webhook_pr_events,
    log_webhook_pr_event,
    log_pr_action,
    save_review_result,
    update_github_project,
    update_webhook_pr_event_status,
)
from backend.tools.github import approve_pull_request, fetch_open_prs, fetch_pr_file_patches, post_pr_comment

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
register_default_providers()
run_startup_preflight()


@app.get("/health/preflight")
async def health_preflight():
    return get_preflight_snapshot()


class ManualReviewPayload(BaseModel):
    project_id: int = Field(..., description="Registered GitHub project id from /projects")
    pr_id: str
    repo: str
    pr_number: int
    title: str = ""
    diff: str
    scm_provider: str = "github"
    tracker_provider: str = ""


class PostCommentPayload(BaseModel):
    project_id: int
    repo: str
    pr_number: int
    body: str
    scm_provider: str = "github"


class ApprovePrPayload(BaseModel):
    project_id: int
    repo: str
    pr_number: int
    scm_provider: str = "github"


class PrActionPayload(BaseModel):
    project_id: int | None = None
    repo: str
    pr_number: int
    action_type: str
    action_status: str = "success"
    provider: str = "github"
    actor: str = "user"
    details: str = ""
    run_id: int | None = None


class CreateProjectPayload(BaseModel):
    full_name: str = Field(..., description="owner/repo")
    github_token: str
    webhook_secret: str = ""
    scm_provider: str = "github"
    tracker_provider: str = ""
    tracker_token: str = ""
    tracker_project_key: str = ""


class UpdateProjectPayload(BaseModel):
    github_token: str | None = None
    webhook_secret: str | None = None
    tracker_provider: str | None = None
    tracker_token: str | None = None
    tracker_project_key: str | None = None


def _token_for_repo_full_name(full_name: str) -> str:
    integration = get_integration_row_by_full_name(full_name, "github")
    if integration and (integration.get("scm_token_encrypted") or "").strip():
        try:
            return decrypt_secret(integration["scm_token_encrypted"])
        except SecretKeyError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    row = get_githubproject_row_by_full_name(full_name)
    if row and (row.get("github_token_encrypted") or "").strip():
        try:
            return decrypt_secret(row["github_token_encrypted"])
        except SecretKeyError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    legacy = os.getenv("GITHUB_TOKEN", "").strip()
    if legacy:
        return legacy
    raise HTTPException(
        status_code=500,
        detail="No GitHub token for this repository. Add the repo under Settings or set GITHUB_TOKEN in the environment.",
    )


def resolve_token_for_project_id(project_id: int) -> str:
    integration = get_integration_row_by_id(project_id)
    if integration and (integration.get("scm_token_encrypted") or "").strip():
        try:
            return decrypt_secret(integration["scm_token_encrypted"])
        except SecretKeyError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    row = get_githubproject_row_by_id(project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    enc = row.get("github_token_encrypted") or ""
    if not enc.strip():
        raise HTTPException(status_code=400, detail="No GitHub token stored for this project.")
    try:
        return decrypt_secret(enc)
    except SecretKeyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _webhook_secret_for_repo(full_name: str) -> str | None:
    integration = get_integration_row_by_full_name(full_name, "github")
    if integration and (integration.get("webhook_secret_encrypted") or "").strip():
        try:
            return decrypt_secret(integration["webhook_secret_encrypted"])
        except SecretKeyError:
            return None
    row = get_githubproject_row_by_full_name(full_name.strip())
    if row and (row.get("webhook_secret_encrypted") or "").strip():
        try:
            return decrypt_secret(row["webhook_secret_encrypted"])
        except SecretKeyError:
            return None
    legacy = os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()
    return legacy or None


def _verify_github_signature(raw_body: bytes, signature_header: str | None, secret: str) -> None:
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing signature header.")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")


def _run_review(review_input: ReviewInput, *, project_id: int | None = None) -> dict[str, Any]:
    run_id = create_agent_run(review_input.pr_id, review_input.repo, review_input.pr_number, project_id=project_id)
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
        save_review_result(review_input.pr_id, payload, project_id=project_id)
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


def _resolve_tracker_token(project_id: int | None) -> str:
    if project_id is None:
        return ""
    row = get_integration_row_by_id(project_id)
    if not row:
        return ""
    enc = row.get("tracker_token_encrypted") or ""
    if not enc.strip():
        return ""
    try:
        return decrypt_secret(enc)
    except SecretKeyError:
        return ""


def _should_fetch_full_tracker_context(review_input: ReviewInput) -> tuple[bool, str]:
    diff = (review_input.diff or "").lower()
    changed_files = [str(item.get("filename", "")).lower() for item in (review_input.changed_files or []) if isinstance(item, dict)]
    only_docs_or_tests = bool(changed_files) and all(
        ("/test" in p or p.startswith("test") or p.endswith(".md") or "/docs/" in p or p.startswith("docs/"))
        for p in changed_files
    )
    if only_docs_or_tests:
        return False, "docs_or_tests_only"
    high_impact_tokens = ("return ", "response", "schema", "payload", "api", "contract", "break", "fix")
    if any(token in diff for token in high_impact_tokens):
        return True, "behavior_or_contract_change"
    # Default to lightweight gating; full context only when behavior signals exist.
    return False, "low_impact_change"


def _enrich_review_input_with_requirements(review_input: ReviewInput, project_id: int | None) -> ReviewInput:
    ticket_ids, linking_meta = resolve_ticket_ids(
        linked_ids=list(review_input.linked_ticket_ids or []),
        pr_title=review_input.title,
        branch_name=str(review_input.scm_context.get("branch_name", "")),
    )
    review_input.linking_metadata = linking_meta
    review_input.linked_ticket_ids = ticket_ids

    if not review_input.tracker_provider or not ticket_ids:
        return review_input
    fetch_full, reason = _should_fetch_full_tracker_context(review_input)
    review_input.linking_metadata["context_mode"] = "full" if fetch_full else "light"
    review_input.linking_metadata["context_gate_reason"] = reason
    if not fetch_full:
        # Keep ticket IDs for traceability, but avoid pulling heavy ticket context for low-impact changes.
        return review_input

    tracker = provider_registry.get_tracker(review_input.tracker_provider)
    tracker_token = _resolve_tracker_token(project_id)
    requirements: list[str] = []
    ticket_context: list[dict[str, Any]] = []
    for ticket_id in ticket_ids:
        ticket = tracker.fetch_ticket(
            ticket_id=ticket_id,
            token=tracker_token,
            project_hint=str(review_input.scm_context.get("repo", review_input.repo)),
        )
        if not ticket:
            continue
        ticket_context.append(
            {
                "provider": ticket.provider,
                "ticket_id": ticket.ticket_id,
                "title": ticket.title,
                "description": ticket.description,
                "acceptance_criteria": ticket.acceptance_criteria,
                "metadata": ticket.metadata,
            }
        )
        requirements.extend(ticket.acceptance_criteria)
    review_input.ticket_context = ticket_context
    review_input.requirements = requirements
    return review_input


@app.get("/settings/crypto-status")
async def crypto_status():
    return {
        "encryption_configured": is_encryption_configured(),
        "hint": (
            "Set APP_SECRET_KEY in the server environment to enable storing GitHub tokens and webhook secrets "
            'in the database (Fernet key: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())").'
        ),
    }


@app.get("/settings/onboarding-status")
async def onboarding_status():
    items = list_projects_public()
    enc = is_encryption_configured()
    n = len(items)
    return {
        "encryption_configured": enc,
        "project_count": n,
        "needs_encryption": not enc,
        "needs_first_project": enc and n == 0,
        "onboarding_complete": enc and n > 0,
    }


@app.post("/settings/generate-app-secret")
async def generate_app_secret():
    """Create a Fernet key, write APP_SECRET_KEY to .env, and load it into this process."""
    if is_encryption_configured():
        raise HTTPException(
            status_code=400,
            detail="APP_SECRET_KEY is already set. Remove it from the environment and .env only if you must regenerate.",
        )
    allow = os.getenv("ALLOW_DOTENV_WRITE", "true").strip().lower()
    if allow in ("0", "false", "no"):
        raise HTTPException(
            status_code=503,
            detail="Writing to .env is disabled (ALLOW_DOTENV_WRITE=false). Set APP_SECRET_KEY in the environment instead.",
        )
    key = Fernet.generate_key().decode("ascii")
    try:
        path = upsert_app_secret_key_line(key)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not write .env file: {exc!s}") from exc
    os.environ["APP_SECRET_KEY"] = key
    load_dotenv(override=True)
    return {
        "status": "ok",
        "env_file": str(path),
        "message": "Encryption key saved. The running server has loaded it; restart is optional.",
    }


@app.get("/projects")
async def list_projects():
    return {"items": list_projects_public()}


@app.post("/projects")
async def create_project(payload: CreateProjectPayload):
    if not is_encryption_configured():
        raise HTTPException(
            status_code=503,
            detail="Server APP_SECRET_KEY is not set; cannot encrypt credentials. See GET /settings/crypto-status.",
        )
    fn = payload.full_name.strip()
    if not fn or "/" not in fn:
        raise HTTPException(status_code=400, detail="full_name must be owner/repo.")
    if not payload.github_token.strip():
        raise HTTPException(status_code=400, detail="github_token is required.")
    try:
        tok_e = encrypt_secret(payload.github_token.strip())
        wh_e = encrypt_secret(payload.webhook_secret.strip()) if payload.webhook_secret.strip() else ""
        tracker_tok_e = encrypt_secret(payload.tracker_token.strip()) if payload.tracker_token.strip() else ""
    except SecretKeyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        pid = insert_github_project(full_name=fn, github_token_encrypted=tok_e, webhook_secret_encrypted=wh_e)
        try:
            insert_integration(
                full_name=fn,
                scm_provider=payload.scm_provider.strip().lower() or "github",
                scm_token_encrypted=tok_e,
                webhook_secret_encrypted=wh_e,
                tracker_provider=payload.tracker_provider.strip().lower(),
                tracker_token_encrypted=tracker_tok_e,
                tracker_project_key=payload.tracker_project_key.strip(),
            )
        except sqlite3.IntegrityError:
            pass
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A project with this full_name already exists.") from exc
    return {"status": "ok", "id": pid, "full_name": fn}


@app.patch("/projects/{project_id}")
async def patch_project(project_id: int, payload: UpdateProjectPayload):
    if not is_encryption_configured():
        raise HTTPException(status_code=503, detail="APP_SECRET_KEY is not set on the server.")
    row = get_githubproject_row_by_id(project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    raw = payload.model_dump(exclude_unset=True)
    try:
        if "github_token" in raw:
            if not str(raw["github_token"]).strip():
                raise HTTPException(status_code=400, detail="github_token cannot be empty.")
            update_github_project(project_id, github_token_encrypted=encrypt_secret(str(raw["github_token"]).strip()))
        if "webhook_secret" in raw:
            wh = str(raw["webhook_secret"] or "").strip()
            if wh:
                update_github_project(project_id, webhook_secret_encrypted=encrypt_secret(wh))
            else:
                update_github_project(project_id, unset_webhook_secret=True)
    except SecretKeyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok"}


@app.delete("/projects/{project_id}")
async def remove_project_endpoint(project_id: int):
    row = get_githubproject_row_by_id(project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    delete_github_project(project_id)
    return {"status": "ok"}


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
):
    raw_body = await request.body()
    event = _parse_github_event(raw_body, request.headers.get("content-type"))

    repository = event.get("repository") or {}
    full_name = str(repository.get("full_name") or "").strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="Missing repository.full_name in webhook payload.")

    secret = _webhook_secret_for_repo(full_name)
    if not secret:
        raise HTTPException(
            status_code=401,
            detail="No webhook secret configured for this repository (add it in app Settings for this project or set GITHUB_WEBHOOK_SECRET).",
        )
    _verify_github_signature(raw_body, x_hub_signature_256, secret)

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
        scm_provider="github",
    )
    proj_row = get_githubproject_row_by_full_name(review_input.repo)
    project_id = int(proj_row["id"]) if proj_row else None
    integration_row = get_integration_row_by_full_name(review_input.repo, "github")
    if integration_row and integration_row.get("tracker_provider"):
        review_input.tracker_provider = str(integration_row.get("tracker_provider") or "")
    event_id = log_webhook_pr_event(
        delivery_id=x_github_delivery,
        project_id=project_id,
        provider=review_input.scm_provider,
        repo=review_input.repo,
        pr_number=review_input.pr_number,
        pr_id=review_input.pr_id,
        title=review_input.title,
        action=str(action),
        sender_login=str((event.get("sender") or {}).get("login") or ""),
        event_json=event,
        processed_status="received",
    )
    token = _token_for_repo_full_name(review_input.repo)
    try:
        scm = provider_registry.get_scm(review_input.scm_provider)
        parsed = scm.fetch_pull_request(repo=review_input.repo, pr_number=review_input.pr_number, token=token)
        review_input.diff = parsed.diff or ""
        review_input.changed_files = parsed.changed_files
        review_input.title = parsed.title or review_input.title
        review_input.scm_context = {"repo": parsed.repo, "branch_name": parsed.branch_name}
        review_input.linked_ticket_ids = parsed.linked_ticket_ids
    except Exception:
        review_input.diff = pull_request.get("body", "") or ""
    review_input = _enrich_review_input_with_requirements(review_input, project_id)
    try:
        output = _run_review(review_input, project_id=project_id)
        update_webhook_pr_event_status(event_id, "processed")
    except Exception:
        update_webhook_pr_event_status(event_id, "failed")
        raise
    try:
        provider_registry.get_scm(review_input.scm_provider).post_comment(
            repo=review_input.repo,
            pr_number=review_input.pr_number,
            body=output.get("final_comment", ""),
            token=token,
        )
        log_pr_action(
            pr_id=review_input.pr_id,
            repo=review_input.repo,
            pr_number=review_input.pr_number,
            provider=review_input.scm_provider,
            action_type="comment_added",
            action_status="success",
            actor="system",
            details="Auto-posted final comment after webhook-triggered analysis.",
            project_id=project_id,
        )
    except Exception:
        log_pr_action(
            pr_id=review_input.pr_id,
            repo=review_input.repo,
            pr_number=review_input.pr_number,
            provider=review_input.scm_provider,
            action_type="comment_added",
            action_status="failed",
            actor="system",
            details="Auto-comment failed after webhook-triggered analysis.",
            project_id=project_id,
        )
    return {"status": "ok", "pr_id": review_input.pr_id}


@app.get("/webhook/inbox")
async def webhook_inbox(limit: int = 100, project_id: int | None = None):
    return {"items": list_webhook_pr_events(limit=limit, project_id=project_id)}


@app.post("/review")
async def manual_review(payload: ManualReviewPayload):
    row = get_githubproject_row_by_id(payload.project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    data = payload.model_dump()
    data.pop("project_id", None)
    review_input = ReviewInput(**data)
    review_input.scm_provider = payload.scm_provider.strip().lower() or "github"
    review_input.tracker_provider = payload.tracker_provider.strip().lower()
    integration_row = get_integration_row_by_id(payload.project_id)
    if integration_row and not review_input.tracker_provider:
        review_input.tracker_provider = str(integration_row.get("tracker_provider") or "")
    if review_input.repo != row["full_name"]:
        raise HTTPException(status_code=400, detail="repo must match the selected project's full name.")
    resolve_token_for_project_id(payload.project_id)
    review_input = _enrich_review_input_with_requirements(review_input, payload.project_id)
    output = _run_review(review_input, project_id=payload.project_id)
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

    row = get_githubproject_row_by_id(payload.project_id)
    if not row or row["full_name"] != repo_name:
        raise HTTPException(status_code=400, detail="repo does not match the selected project.")

    token = resolve_token_for_project_id(payload.project_id)
    scm_provider = payload.scm_provider.strip().lower() or "github"
    provider_registry.get_scm(scm_provider).post_comment(repo=repo_name, pr_number=payload.pr_number, body=comment_body, token=token)
    log_pr_action(
        pr_id=f"{repo_name}#{payload.pr_number}",
        repo=repo_name,
        pr_number=payload.pr_number,
        provider=scm_provider,
        action_type="comment_added",
        action_status="success",
        actor="user",
        details="Manual comment posted from UI action.",
        project_id=payload.project_id,
    )
    return {"status": "ok", "message": f"Comment posted to {repo_name}#{payload.pr_number}"}


@app.post("/github/approve-pr")
async def approve_pr(payload: ApprovePrPayload):
    repo_name = payload.repo.strip()
    if not repo_name:
        raise HTTPException(status_code=400, detail="Repository is required.")
    if payload.pr_number <= 0:
        raise HTTPException(status_code=400, detail="PR number must be greater than zero.")

    row = get_githubproject_row_by_id(payload.project_id)
    if not row or row["full_name"] != repo_name:
        raise HTTPException(status_code=400, detail="repo does not match the selected project.")

    token = resolve_token_for_project_id(payload.project_id)
    scm_provider = payload.scm_provider.strip().lower() or "github"
    try:
        provider_registry.get_scm(scm_provider).approve_pull_request(
            repo=repo_name,
            pr_number=payload.pr_number,
            token=token,
        )
    except Exception as exc:
        log_pr_action(
            pr_id=f"{repo_name}#{payload.pr_number}",
            repo=repo_name,
            pr_number=payload.pr_number,
            provider=scm_provider,
            action_type="pr_approved",
            action_status="failed",
            actor="user",
            details=f"Approve failed: {exc!s}",
            project_id=payload.project_id,
        )
        raise HTTPException(status_code=502, detail=f"Could not approve pull request: {exc!s}") from exc

    log_pr_action(
        pr_id=f"{repo_name}#{payload.pr_number}",
        repo=repo_name,
        pr_number=payload.pr_number,
        provider=scm_provider,
        action_type="pr_approved",
        action_status="success",
        actor="user",
        details="Pull request approved from UI action.",
        project_id=payload.project_id,
    )
    return {"status": "ok", "message": f"Approved {repo_name}#{payload.pr_number}"}


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
        provider=payload.provider.strip().lower() or "github",
        action_type=action_type,
        action_status=action_status,
        actor=payload.actor.strip() or "user",
        details=payload.details.strip() or None,
        run_id=payload.run_id,
        project_id=payload.project_id,
    )
    return {"status": "ok", "action_id": action_id}


@app.get("/results/{pr_id:path}")
async def get_results(pr_id: str):
    result = get_review_result(pr_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No results for this PR.")
    return result


@app.get("/decisions/history/prs")
async def get_pr_history(limit: int = 100, project_id: int | None = None):
    return {"items": get_pr_history_summary(limit=limit, project_id=project_id)}


@app.get("/decisions/history/runs")
async def get_all_analysis_history(limit: int = 200, project_id: int | None = None):
    return {"items": get_analysis_history(limit=limit, project_id=project_id)}


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
async def get_default_pr(project_id: int):
    row = get_githubproject_row_by_id(project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")

    repo_name = row["full_name"]
    token = resolve_token_for_project_id(project_id)
    prs = fetch_open_prs(repo_name, limit=1, token=token)
    if not prs:
        return {
            "pr_id": "",
            "repo": repo_name,
            "pr_number": None,
            "title": "",
            "diff": "",
            "project_id": project_id,
            "no_open_prs": True,
        }

    selected = prs[0]
    parsed = fetch_pr_file_patches(repo_name, selected["number"], token=token)
    return {
        "pr_id": selected["pr_id"],
        "repo": repo_name,
        "pr_number": selected["number"],
        "title": parsed.get("title", selected["title"]),
        "diff": parsed.get("combined_diff", ""),
        "project_id": project_id,
        "no_open_prs": False,
    }


@app.get("/github/open-prs")
async def get_open_prs_endpoint(project_id: int):
    row = get_githubproject_row_by_id(project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    repo_name = row["full_name"]
    token = resolve_token_for_project_id(project_id)
    prs = fetch_open_prs(repo_name, limit=100, token=token)
    return {"repo": repo_name, "pull_requests": prs, "project_id": project_id}


@app.get("/github/pr/{pr_number}")
async def get_pr_details(pr_number: int, project_id: int):
    row = get_githubproject_row_by_id(project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    repo_name = row["full_name"]
    token = resolve_token_for_project_id(project_id)
    parsed = fetch_pr_file_patches(repo_name, pr_number, token=token)
    return {
        "pr_id": f"{repo_name}#{pr_number}",
        "repo": repo_name,
        "pr_number": pr_number,
        "title": parsed.get("title", ""),
        "diff": parsed.get("combined_diff", ""),
        "project_id": project_id,
    }
