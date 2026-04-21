# PR Review Multi-Agent System

## Problem Statement

Engineering teams lose significant time in pull request review cycles due to repetitive manual checks, inconsistent review quality, and delayed feedback on regressions. Traditional pipelines often validate syntax and tests but still miss semantic logic errors, while fully manual review does not scale across multiple repositories and contributors. This project addresses that gap by combining deterministic analysis, confidence-gated escalation, LLM-assisted reasoning, and automated test verification to deliver faster, more reliable, and actionable PR feedback.

This project implements a GitHub pull request review pipeline:

GitHub PR → webhook or manual UI → FastAPI backend → LangGraph multi-agent workflow → tools + memory → PR comments, approvals, and a React dashboard.



## Implemented stack

- **Runtime:** Python `3.11` (`backend/Dockerfile`), Node.js `20` (`frontend/Dockerfile`)
- **Orchestration:** LangGraph (dependency declared in `backend/requirements.txt`, currently unpinned)
- **Backend:** FastAPI + Uvicorn (dependencies declared in `backend/requirements.txt`, currently unpinned)
- **Tools:** GitHub API via PyGithub (declared, unpinned), linter wrapper, sandbox test runner, diff generation
- **Memory:** ChromaDB vector store (declared in backend requirements, currently unpinned)
- **UI:** React `^18.3.1` + Vite `^5.4.10` dashboard (project picker, onboarding, settings)
- **Testing/UI Tooling:** Jest `^30.3.0`, `@vitejs/plugin-react` `^4.3.1`
- **LLM:** OpenAI SDK (declared in backend requirements, currently unpinned); model/provider configured via `OPENAI_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL`

## Features

- **Multiple GitHub repositories:** Register each repo in the app with its own PAT and optional webhook secret. Credentials are stored encrypted (Fernet) when `APP_SECRET_KEY` is set.
- **Onboarding:** First launch can generate an encryption key (written to `.env`), then collect the first `owner/repo`, token, and optional webhook secret.
- **Settings:** Add or remove repositories after setup; PR history and actions are scoped per project where applicable.
- **Preflight:** On startup the backend checks that the SQLite schema matches the multi-project layout; optionally recreates the DB file if it is incompatible (`PREFLIGHT_AUTO_REINIT_DB`). See `GET /health/preflight` for live status (encryption, credentials, schema).
- **Webhooks:** `POST /webhook/github` verifies the signature using the webhook secret stored for that repository, or falls back to `GITHUB_WEBHOOK_SECRET` in the environment.

## Project structure

```text
backend/
  main.py
  models.py
  agents/
  tools/
  memory/
  graph/
  sqlite_store.py
  secrets_crypto.py
  preflight.py
frontend/
  src/
README.md
.env.example
```

## Screenshots

- UI and workflow screenshots are available in `docs/screenshots/`.

## Configuration

Copy `.env.example` to `.env` and adjust.

### Encryption (required for storing tokens in the database)

- **`APP_SECRET_KEY`** — Fernet key (44-character URL-safe base64). Used to encrypt GitHub PATs and webhook secrets in SQLite.
- Generate locally:  
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- The UI can also generate a key and append it to `.env` via **Settings** / onboarding (server must be allowed to write that file, or set `DOTENV_FILE` to a writable path).

### Preflight / database

- **`SQLITE_DB_PATH`** — SQLite file path (default `./review_results.db`).
- **`PREFLIGHT_AUTO_REINIT_DB`** — If `true` (default), a failed schema check triggers deletion of the DB file and a fresh `init_db()`. Set to `false` to avoid destructive resets (e.g. production debugging).
- **`AUTO_BOOTSTRAP_ENV_PROJECT`** — If `1`/`true`/`yes`, and `APP_SECRET_KEY` plus `GITHUB_REPO` / `GITHUB_TOKEN` are set, one project row may be created from the environment on first DB init. Otherwise use onboarding or **Settings** only.

### Legacy environment fallbacks (optional)

- **`GITHUB_TOKEN`** / **`GITHUB_WEBHOOK_SECRET`** — Used when no matching encrypted project row exists (e.g. webhook verification before projects are registered).

### LLM

Set one of the following:

- **OpenAI:** `OPENAI_API_KEY`, `LLM_MODEL` (e.g. `gpt-4o-mini`).
- **OpenAI-compatible server:** `LLM_BASE_URL=http://host:port/v1`, `OPENAI_API_KEY=local-key`, `LLM_MODEL=<model-name>`.

Reviewer, fixer, and summarizer read these settings automatically.

## Backend API (selected)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health/preflight` | Schema, encryption, credential readiness |
| GET | `/settings/crypto-status` | Whether `APP_SECRET_KEY` is loaded |
| GET | `/settings/onboarding-status` | Wizard steps (encryption / first project) |
| POST | `/settings/generate-app-secret` | Generate key and write `APP_SECRET_KEY` to `.env` |
| GET | `/projects` | List registered repos (no secrets) |
| POST | `/projects` | Add a project (`full_name`, `github_token`, optional `webhook_secret`) |
| PATCH | `/projects/{id}` | Rotate token / webhook secret |
| DELETE | `/projects/{id}` | Remove a project |
| POST | `/webhook/github` | GitHub webhook (signature per repo or legacy secret) |
| POST | `/review` | Manual review (`project_id`, `pr_id`, `repo`, `pr_number`, …) |
| GET | `/github/default-pr` | `?project_id=` |
| GET | `/github/open-prs` | `?project_id=` |
| GET | `/github/pr/{n}` | `?project_id=` |
| POST | `/github/post-comment` | Body includes `project_id` |
| POST | `/github/approve-pr` | Body includes `project_id` |
| GET | `/results/{pr_id}` | Stored workflow result |
| GET | `/decisions/history/runs` | Optional `?project_id=` filter |
| GET | `/actions/{pr_id}` | Logged actions for a PR |

## Workflow

```text
START → Reviewer Fast (deterministic + lint) → Test Agent
                                      |
                                      | confidence gate:
                                      | - escalate if business_logic_change OR semantic_risk
                                      | - escalate if confidence_score < confidence_threshold
                                      v
                      Reviewer (LLM) → Fix Generator (LLM) → Test Agent
                                               | (on fail, max attempts)
                                               v
                                        Fix Generator (retry)
                                               |
                                               v
                                          Summary (LLM/fallback) → END
```

- `confidence_threshold` defaults to `0.5` and adapts to `0.4` for arithmetic/control-flow mutation risk.
- LLM is invoked in `Reviewer` (issue extraction), `Fix Generator` (patch proposal), and `Summary` (final comment with fallback).

## Agents

- **`Reviewer Fast` (`backend/agents/reviewer.py`)**: Runs deterministic checks and lint ingestion without LLM calls. It is used first to keep low-risk PRs fast and cheap.
- **`Test Agent` (`backend/agents/tester.py`)**: Executes tests through the sandbox runner and records `test_output`. It also computes confidence metadata (`confidence_score`, `semantic_risk`, `business_logic_change`, and adaptive threshold inputs).
- **`Reviewer` (`backend/agents/reviewer.py`)**: Escalated reviewer that uses LLM (`llm_json`) to extract structured issues (type, severity, location, message) from the diff.
- **`Fix Generator` (`backend/agents/fixer.py`)**: Uses LLM (`llm_json`) plus issue context to propose patch-ready improvements and explanation text; may retry if tests fail and retry budget remains.
- **`Summary` (`backend/agents/summarizer.py`)**: Produces final PR comment using LLM (`llm_text`) with fallback formatting when LLM output is unavailable.

### Agent Routing Behavior

- Start with `Reviewer Fast` and `Test Agent`.
- Escalate to LLM path when `business_logic_change` or `semantic_risk` is true, or when `confidence_score < confidence_threshold`.
- On escalated path, `Fix Generator` is retried only when tests fail and retry budget remains.
- End with `Summary`, which persists a final human-readable review comment.

##########################################
## Team members and their Contributions ##
##########################################

### 1) Initial Proof of Concept (POC)

- Built a minimal system to fetch and display the latest PR from a given GitHub repository.
- Introduced a multi-agent analysis pipeline to evaluate PR content.
- Output was presented as raw JSON analysis.

**Ownership** Mukund C Gokulan
- **Backend:** GitHub API integration and agent orchestration.
- **Fullstack:** Basic API consumption and result rendering.
- **Frontend:** Minimal UI scaffold for displaying raw results.

### 2) Structured Analysis & UI Transformation

- Converted raw JSON into a structured, UI-friendly PR analysis report.
- Added parsing logic to highlight:
  - Code issues
  - Suggestions
  - Risk indicators

**Ownership** Aadhithya Mohandas
- **Backend:** Structured response schema design.
- **Fullstack:** JSON parsing and transformation logic.
- **Frontend:** UI components for readable analysis visualization.

### 3) Persistence Layer (SQLite Integration)

- Integrated SQLite database to store PR analysis reports.
- Enabled:
  - Historical tracking of PR reviews
  - Faster retrieval without recomputation

**Ownership** Sruthy Muraleedharan
- **Backend:** Database schema design and storage/retrieval APIs.
- **Fullstack:** Data flow integration between API and UI.
- **Frontend:** Display of stored analysis results.

### 4) GitHub Actions Integration

- Added direct PR interactions from the app:
  - Approve PR
  - Add comments

**Ownership** Aadhithya Mohandas
- **Backend:** GitHub API action handlers (approve/comment).
- **Fullstack:** Action trigger wiring from UI to APIs.
- **Frontend:** Action buttons and interaction flows.

### 5) Multi-PR Support

- Extended system to fetch all PRs in a repository.
- Enabled users to select and analyze specific PRs.

**Ownership** Sruthy Muraleedharan
- **Backend:** PR listing APIs and filtering support.
- **Fullstack:** Selection logic and API integration.
- **Frontend:** PR listing UI and selection controls.

### 6) Multi-Repository Support

- Introduced support for multiple repositories.
- Enabled users to:
  - Switch between repositories
  - Analyze PRs across projects

**Ownership** Mukund C Gokulan
- **Backend:** Multi-repo handling and dynamic configuration.
- **Fullstack:** State management for repository switching.
- **Frontend:** Repository selection UI.

### 7) UI Enhancements (GitHub-like Experience)

- Transformed the initial scaffold into a GitHub-inspired interface.
- Improved:
  - Layout
  - Readability
  - Developer experience

**Ownership** Sruthy Muraleedharan
- **Frontend:** Major UI/UX redesign.
- **Fullstack:** Data binding improvements.
- **Backend:** Minor response adjustments for UI compatibility.

### 8) Webhook Integration (Event-Driven Automation)

- Integrated GitHub webhooks to automate PR ingestion.
- On PR creation:
  - Event is sent to backend
  - PR becomes automatically available for analysis

**Ownership** Mukund C Gokulan
- **Backend:** Webhook endpoint, signature validation, and event processing.
- **Fullstack:** Integration with existing review pipeline.
- **Frontend:** Display of newly received PR activity.

### 9) Future Scope (Planned, Not Yet Implemented)

- Push notifications for new PR events (deferred due to cost considerations).
- Enhanced agent intelligence (risk scoring, deeper semantic analysis).
- CI/CD pipeline integration for automated workflows.

Mukund C Gokulan, Aadhithya Mohandas and Sruthy Muraleedharan

## Setup

### 1) Backend

From the **repository root** (the main project folder):

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
cp .env.example .env
uvicorn backend.main:app --reload
```

The current working directory must be the repo root so the `backend` package imports correctly. The API is served at `http://127.0.0.1:8000` by default.

### 2) Frontend

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_BASE` if the API is not at `http://localhost:8000`.

### 3) Tests

```bash
cd /path/to/repo
python -m pytest backend/tests/ -q
```

### 4) Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

- Backend: `http://localhost:8000`
- Frontend: `http://localhost:4173`

## Notes

- `POST /webhook/github` verifies the HMAC signature and deduplicates by `X-GitHub-Delivery`.
- The webhook handler loads real PR file patches from GitHub (`pulls/{number}/files`), not the PR body.
- The sandbox test runner prefers Docker with resource limits; it can fall back to local pytest.
- Use HTTPS in front of the API in production so tokens are not sent in cleartext from the browser.
