# Migration Plan

The system transition from a linear workflow kernel to an autonomous LangGraph-orchestrated workforce will occur in successive, test-gated milestones.

## Milestone 1: Control Plane & Test Harness Repair
- **Objective**: Fix the test suite (currently 4 failing tests related to `review_attestation`), ensure command boundaries are strictly typed and transaction layers do not cause exceptions. 
- **Actions**:
  - Mock cryptographic attestations in `tests/test_amaura_os.py` and `test_amaura_supervisor.py` to allow simulated agents to correctly perform independent review.
  - Assert that all domain logic transactions occur at the `CommandBus` level only.

## Milestone 2: The Agent Action Layer & LangGraph Adapter
- **Objective**: Introduce `LangGraph` and a set of narrow agent tools.
- **Actions**:
  - Define `LeadWorkflowState` and `CampaignState` schemas using Pydantic.
  - Implement the `AmauraActions` wrapper, securely calling the `AmauraControlPlane`.
  - Create a mock `LangGraph` orchestration loop that can persist to SQLite and resume on interruption.

## Milestone 3: Lead-to-Client LangGraph Workflow
- **Objective**: Execute the complete sales workflow.
- **Actions**:
  - Define nodes: `discover -> research -> score -> qualification -> draft outreach -> founder approval`.
  - Write `tests/test_lead_workflow.py` tracking an end-to-end execution.

## Milestone 4: n8n Communication Integrations
- **Objective**: Connect the output of the LangGraph approval stage to external webhook executions.
- **Actions**:
  - Create `docker-compose.yml` to spin up PostgreSQL, the Amaura API, and n8n.
  - Build n8n workflows for Gmail outbox, Telegram founder approvals, and Webhook ingestion.
  - Trigger these securely from LangGraph nodes.

## Milestone 5: The Coding Abstraction
- **Objective**: Decouple the software workflow from `Nexus` to allow OpenHands support.
- **Actions**:
  - Write the `CodingBackend` protocol.
  - Refactor `executor.py` (`GovernedTaskRunner`) to implement this protocol.
  - Build an OpenHands adapter.

## Milestone 6: Software Delivery Workflow
- **Objective**: Implement the `software_delivery` LangGraph.
- **Actions**:
  - Define nodes: `requirements -> project plan -> approval -> task fan-out -> worktree generation -> coding loop -> test -> merge`.

## Milestone 7: Operations & Dashboard
- **Objective**: Ensure the founder can interactively view and pause workflows.
- **Actions**:
  - Update `jarvis/static/app.js` and HTML to poll the LangGraph/Amaura SQLite state.
  - Enable direct interaction to resolve Human-in-the-Loop approval nodes in LangGraph.

Every milestone will be gated by a full run of the contract and integration tests.
