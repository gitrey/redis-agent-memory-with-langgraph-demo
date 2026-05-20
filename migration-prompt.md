Please plan and implement the migration of our current agent to Google ADK. 

### 1. The Migration Goal
Migrate the existing LangGraph agent that currently uses Redis for memory (session and long-term) to a Google Agent Development Kit (ADK) agent that uses the built-in Memory Store Service of the Agent Engine. 

### 2. Repository Context & Guidelines
* First, read the `GEMINI.md` file in the project root. It contains our core environment guidelines, active skills, directory structure, and deployment architecture.
* We use `uv` as our primary package manager and target Python 3.12.
* All agent logic lives in `backend/`. 
* The static UI in `frontend/` communicates with specific FastAPI endpoints. We must keep the existing FastAPI route signatures and response payloads intact so the frontend continues to work seamlessly.
* The existing test suite is located in `tests/`.

### 3. Recommended Phase-by-Phase Execution Plan

Please work systematically through the following phases and verify correctness at each step:

#### Phase 1: Research & Mapping
1. Read the current LangGraph implementation and `redis-agent-memory` integration in the `backend/` directory.
2. Document how short-term (session) and long-term memory (LTM) are currently saved, retrieved, and structured.
3. Create a mapping plan of how these memory scopes translate into the built-in Memory Store Service of Agent Engine.

#### Phase 2: Scaffolding & Dependencies
1. Use the `google-agents-cli-scaffold` skill to enhance our current project with ADK configuration.
2. Add `google-adk` dependency using `uv add google-adk` and sync the project.
3. Ensure the development environment builds successfully.

#### Phase 3: ADK Implementation
1. Implement the new ADK agent using patterns from the `/google-agents-cli-adk-code` skill.
2. Integrate the built-in Memory Store Service of the Agent Engine for both short-term and long-term scopes.
3. Wire the ADK agent into the FastAPI router, keeping existing API endpoints (`/api/chat`, `/api/sessions/*`, etc.) fully compatible.

#### Phase 4: Testing & Verification
1. Run the test suite using `uv run pytest`.
2. Verify both local mock-based memory operations and check for regression issues.

#### Phase 5: Deployment Prep
1. Prepare the deployment configuration targeting Agent Runtime (formerly Vertex AI Agent Engine) for the backend, and Cloud Run for the decoupled frontend.
