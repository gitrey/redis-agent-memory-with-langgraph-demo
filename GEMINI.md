# Project Instructions: ADK & Agent Engine Memory Store Migration

This repository is dedicated to migrating an existing LangGraph agent that uses
Redis for memory to a Google Agent Development Kit (ADK) agent that uses the
built-in Memory Store Service of the Agent Engine.

## Core Development Guidelines

- **Package & Environment Management**:
  - Always use `uv` as the primary package manager. Do not use standard `pip` or
    manual `venv` creation.
  - To synchronize or install dependencies, run `uv sync`.
  - To execute tests, run `uv run pytest`.
- **Python Target**:
  - Use Python `3.12` as specified in `.python-version`.
- **Agent Architecture**:
  - Utilize the Google Agent Development Kit (`google-adk`) for agent creation,
    tool management, and orchestration patterns.
  - Migrate the memory backend from Redis Agent Memory to the Agent Engine's
    built-in Memory Store Service.

## Prioritized & Active Skills

When developing in this repository, please load and adhere to the instructions
in the following skills:

- `google-agents-cli-workflow` — General ADK development phases and coding
  guidelines.
- `google-agents-cli-adk-code` — Specific ADK coding patterns, tools, callbacks,
  and state management.
- `google-agents-cli-scaffold` — Best practices for project setup, structure
  enhancement, and scaffolding.
- `google-agents-cli-eval` — Evaluation methodologies, test sets, and
  optimization loops.
- `google-agents-cli-deploy` — Deployment workflows, service accounts, and
  Agent Runtime configuration.

## Deployment Architecture (Decoupled)

The project uses a decoupled deployment architecture on Google Cloud:

### 1. Backend (Agent Runtime)
- **Deployment Target**: The agent backend targets the **Agent Runtime** (formerly Vertex AI Agent Engine) managed service.
- **Command**: Use `agents-cli deploy` to deploy:
  ```bash
  agents-cli deploy --deployment-target agent_runtime
  ```
- **Asynchronous Deploys**: Since Agent Runtime deployments can take 5-10 minutes, use `--no-wait` to return immediately and `--status` to check progress:
  ```bash
  agents-cli deploy --deployment-target agent_runtime --no-wait
  agents-cli deploy --status
  ```
- **Secrets & Configurations**: Map secrets from Secret Manager using the `--secrets` flag at deploy time.

### 2. Frontend (Cloud Run)
- **Deployment Target**: The lightweight static frontend is deployed to **Cloud Run** (built and run via `Dockerfile.frontend` and `nginx.conf`).

## Workspace Directory Structure

- `backend/` — FastAPI backend containing the migrated ADK agent logic (migrated from LangGraph).
- `frontend/` — Lightweight static web interface (target: Cloud Run decoupled deployment).
- `tests/` — Unit and integration test suite (run via `uv run pytest`).
