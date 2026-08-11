# Open-Source Dependency Decisions

This document outlines the strategic decisions regarding the integration of open-source components into the Amaura AI workforce, replacing or complementing existing internal capabilities.

## 1. LangGraph (`langchain-ai/langgraph`)

### Rationale
Amaura currently attempts to orchestrate multi-step business logic via its `AmauraSupervisor` and the `control_plane` coupled with SQLite `work_items` and `execution_runs`. While this provides governance, it lacks robust primitives for non-linear workflows (conditional branching, cycle detection, parallel execution/fan-out, fan-in, transparent suspension on human input, and native state checkpointing).

### Decision
**Adopt LangGraph as the canonical orchestration layer.**
- **Replaced:** Ad-hoc linear workflow loops and custom task transition states in `supervisor.py`.
- **Kept:** The `AmauraControlPlane` as the strict action/mutation gateway (enforcing policy, budgeting, and auditability).
- **Adapted:** We will wrap our control plane actions inside LangGraph nodes. LangGraph provides the execution topology, while Amaura's Control Plane provides the business rules.

### Checkpointing
- **Development:** SQLite checkpointer (to reuse local capabilities).
- **Production:** PostgreSQL checkpointer to support durability and concurrent horizontal scaling.

## 2. n8n (`n8n-io/n8n`)

### Rationale
Our current system handles external communication (e.g., Gmail, Telegram) directly via Python scripts (e.g., `jarvis/telegram/bot.py`). Building direct API integrations for dozens of platforms (Google Drive, Calendar, GitHub, CRM, Slack) is unscalable and brittle compared to standard integration platforms.

### Decision
**Adopt n8n for deterministic integration workflows.**
- **Replaced:** Internal, bespoke Python HTTP request wrappers for external service webhooks and notifications.
- **Kept:** The strict approval mechanisms in `AmauraControlPlane`. n8n will only trigger API calls *after* the immutable approval hash is validated.
- **Adapted:** The system will invoke authenticated n8n webhooks to perform actions, rather than directly managing OAuth credentials and raw REST logic in Python.
- **Security:** All n8n endpoints exposed to Amaura will require authentication.

## 3. OpenHands (`OpenHands/OpenHands`)

### Rationale
The existing `nexus` CLI provides local file mutation. However, deep automated software engineering tasks require a true read-write-execute loop within a secure, isolated sandbox to compile code, run tests, and manipulate Git, without jeopardizing the host environment. OpenHands is purpose-built for this autonomous coding loop.

### Decision
**Evaluate and Integrate OpenHands alongside Nexus CLI.**
- **Replaced:** Untrusted, un-sandboxed code execution on the host machine.
- **Kept:** The `Nexus` CLI as a fast, low-cost fallback for straightforward edits where the full weight of OpenHands is unnecessary.
- **Adapted:** Create a unified `CodingBackend` protocol. The system routes tasks to `Nexus` (for small, safe changes) or `OpenHands` (for complex, multi-file refactors or test-driven cycles).

## 4. Pydantic (`pydantic/pydantic`)

### Rationale
AI agents are prone to producing unstructured or hallucinated formats. State transitions must rely on deterministic, typed structures, not raw natural language.

### Decision
**Enforce Pydantic across all Agent Interfaces.**
- **Replaced:** Returning raw dictionaries, JSON strings, or free-text analysis from agents.
- **Kept:** Existing Pydantic definitions in `models.py` and `api.py`.
- **Adapted:** Every workflow state in LangGraph, and every action boundary, will be strictly typed using Pydantic. Any model failure to produce this schema will invoke a retry loop.

## 5. PostgreSQL

### Rationale
The current architecture relies heavily on SQLite `BEGIN IMMEDIATE` locks, leading to concurrent transaction contention and nested transaction exceptions (as recently fixed in P0 remediation). SQLite is excellent for a single-user local application, but an autonomous workforce producing significant concurrent read/writes requires a robust relational database.

### Decision
**Migrate persistence from SQLite to PostgreSQL (while maintaining local SQLite support).**
- **Replaced:** Direct SQLite coupling where concurrency limits the worker threads.
- **Kept:** The repository/store pattern (`store.py`) to abstract the underlying SQL engine.
- **Adapted:** We will introduce SQLAlchemy or a DB-API compliant abstraction that allows for SQLite during local development/testing, but connects to PostgreSQL for production deployments.

## Licensing & Upgrades
- All chosen tools operate under permissive open-source licenses (MIT/Apache 2.0 or Fair-code models for self-hosting).
- Upgrades will be managed via pinned Docker images (for n8n/OpenHands) and strictly pinned Python dependencies in `pyproject.toml` and `uv.lock`.
