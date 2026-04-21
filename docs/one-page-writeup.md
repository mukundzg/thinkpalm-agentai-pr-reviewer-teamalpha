# One-Page Project Write-Up

## Project Title
**AgentAI PR Reviewer – Multi-Repository, Multi-Agent Pull Request Analysis Platform**

## Problem Statement
Pull request review is often slow, repetitive, and inconsistent across teams. Traditional linting/test pipelines catch syntax and test failures, but they may miss semantic risks and provide limited actionable review guidance. Teams also lose time when review insights and GitHub actions (comment/approve) are spread across multiple tools.

## Proposed Solution
This project delivers an end-to-end PR review assistant that combines deterministic checks, confidence-based routing, LLM-assisted reasoning, and test verification. The system supports both manual and webhook-driven analysis, allows multiple GitHub repositories under one dashboard, and enables direct PR actions from the application.

## Core Architecture
- **Frontend (React):** Dashboard for onboarding, project switching, PR selection, review execution, history, decision flow, webhook inbox, and post-analysis actions.
- **Backend (FastAPI):** API orchestration, webhook handling, GitHub API integration, and persistence.
- **Workflow Engine (LangGraph):** Multi-agent flow with adaptive escalation.
- **Persistence (SQLite):** Stores review results, run history, decision logs, webhook events, and action logs.
- **Security Layer (Fernet):** Encrypts GitHub tokens and webhook secrets using `APP_SECRET_KEY`.

## Agent Workflow
1. **Reviewer Fast** performs a lightweight first-pass issue scan.
2. **Tester** executes checks and computes confidence/risk signals.
3. If confidence is high and risk is low, flow goes to **Summarizer** directly.
4. If confidence is low or semantic/business risk is detected, flow escalates to:
   - **Reviewer (LLM-based deeper analysis)**
   - **Fixer (LLM-based patch/fix generation)**
   - **Tester** retry loop (bounded by max attempts)
5. **Summarizer** produces final PR-ready comment output.

## Multi-Repository & Webhook Support
- Users can register multiple repositories, each with its own encrypted token and optional webhook secret.
- GitHub webhook events (`opened`, `synchronize`, `reopened`) are validated and ingested automatically.
- Incoming webhook PRs are recorded and shown in a UI inbox for operator visibility.

## Key Features
- Structured PR analysis report (issues, summary, patch, diagnostics)
- Confidence-gated escalation to reduce cost and improve reliability
- PR history and decision traceability for audit/debug
- Direct GitHub actions from UI (comment and approve)
- Secure project onboarding with encryption key generation

## Outcome and Value
The platform reduces review turnaround time, improves consistency, and centralizes review + action workflows. It balances speed (fast path) with depth (LLM escalation), while maintaining traceability and security across multiple repositories.

## Tech Stack (High Level)
- Python, FastAPI, LangGraph, SQLite, PyGithub, OpenAI-compatible LLM APIs
- React + Vite frontend
- Fernet encryption for secret storage
