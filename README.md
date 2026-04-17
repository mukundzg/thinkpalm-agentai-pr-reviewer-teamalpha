# PR Review Multi-Agent System

This project implements a GitHub PR review pipeline:

GitHub PR -> Webhook -> FastAPI Backend -> LangGraph multi-agent flow -> tools + memory -> PR comment/UI.

## Implemented Stack

- Agent orchestration: LangGraph
- Backend: FastAPI
- Tools: GitHub API, linter wrapper, sandbox test runner, diff generator
- Memory: ChromaDB vector store for issue/fix history
- UI: React + Vite dashboard
- LLM providers: OpenAI or local OpenAI-compatible endpoint

## Project Structure

```text
backend/
  main.py
  models.py
  agents/
  tools/
  memory/
  graph/
frontend/
  src/
README.md
.env.example
```

## Backend Endpoints

- `POST /webhook/github`: Receives GitHub PR events and verifies signature
- `POST /review`: Manual review trigger
- `GET /results/{pr_id}`: Fetch workflow results

## LLM Configuration

Set one of the following in `.env`:

- OpenAI:
  - `OPENAI_API_KEY=...`
  - `LLM_MODEL=gpt-4o-mini` (or any available model)
- Local OpenAI-compatible endpoint (e.g. Ollama gateway):
  - `LLM_BASE_URL=http://host:port/v1`
  - `OPENAI_API_KEY=local-key`
  - `LLM_MODEL=<local-model-name>`

Reviewer, fixer, and summarizer use these settings automatically with safe fallback behavior.

## Workflow

START -> Reviewer -> Fix Generator -> Test Agent
                          | (on fail, max attempts)
                          v
                    Fix Generator (retry)
                          |
                          v
                      Summary -> END

## Setup

### 1) Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env
uvicorn backend.main:app --reload --app-dir ..
```

### 2) Frontend

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_BASE` if backend is not running on `http://localhost:8000`.

### 3) Run Tests

```bash
cd backend
pytest -q
```

### 4) One-command Startup (Docker Compose)

```bash
cp .env.example .env
docker compose up --build
```

- Backend: `http://localhost:8000`
- Frontend: `http://localhost:4173`

## Notes

- `POST /webhook/github` includes signature verification and delivery-id dedupe.
- Webhook flow fetches real PR file patches from GitHub (`pulls/{number}/files`) instead of PR body text.
- Sandbox tool prefers Docker with resource/network limits; falls back to local pytest.
- Workflow and webhook behavior are covered by automated tests in `backend/tests/`.
