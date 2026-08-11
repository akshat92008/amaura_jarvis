from typing import Any, Literal, TypedDict
import os
from langgraph.graph import StateGraph, END

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.actions import AmauraActions
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.experimental.graphs.lead import LeadWorkflowGraph
from jarvis.amaura.experimental.graphs.software import SoftwareWorkflowGraph
from jarvis.amaura.experimental.graphs.content import ContentWorkflowGraph

class SupervisorState(TypedDict):
    worker_id: str
    workflow_id: str | None
    recovered: list[dict[str, Any]]
    claimed_task: dict[str, Any] | None
    run_info: dict[str, Any] | None
    result: dict[str, Any] | None
    error: str | None
    status: str

class LangGraphSupervisor:
    def __init__(self, control: AmauraControlPlane, worker_id: str, lease_seconds: int = 900, max_attempts: int = 2):
        if os.environ.get("AMAURA_ENABLE_EXPERIMENTAL_LANGGRAPH", "0") != "1":
            raise GovernanceError(
                "Experimental LangGraph orchestration is not release-certified. "
                "Use AmauraSupervisor, or explicitly opt in for development only."
            )
        self.control = control
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.actions = AmauraActions(control, worker_id)
        
        self.graphs = {
            "client_acquisition": LeadWorkflowGraph(self.actions).compiled,
            "software_delivery": SoftwareWorkflowGraph(self.actions).compiled,
            "content_campaign": ContentWorkflowGraph(self.actions).compiled,
        }
        
        self.graph = StateGraph(SupervisorState)
        self._build_graph()

    def _build_graph(self) -> None:
        self.graph.add_node("recover", self.recover)
        self.graph.add_node("claim", self.claim)
        self.graph.add_node("execute", self.execute)
        self.graph.add_node("finish", self.finish)

        self.graph.set_entry_point("recover")
        self.graph.add_edge("recover", "claim")
        
        self.graph.add_conditional_edges(
            "claim",
            self.route_claim,
            {"execute": "execute", "END": END}
        )
        
        self.graph.add_edge("execute", "finish")
        self.graph.add_edge("finish", END)

        self.compiled = self.graph.compile()

    def recover(self, state: SupervisorState) -> dict:
        recovered = self.control.store.recover_expired_executions(max_attempts=self.max_attempts)
        for item in recovered:
            self.control.store.publish_event("execution.recovered", item["run_id"], item)
        return {"recovered": recovered, "status": "recovered"}

    def claim(self, state: SupervisorState) -> dict:
        claim = self.control.store.claim_next_task(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            max_attempts=self.max_attempts,
            workflow_id=state.get("workflow_id")
        )
        if not claim:
            return {"status": "idle", "claimed_task": None, "run_info": None}
            
        run = claim["run"]
        task = claim["task"]
        self.control.store.publish_event(
            "execution.started",
            run["id"],
            {"task_id": task["id"], "worker_id": self.worker_id, "attempt": run["attempt"]},
        )
        return {"status": "claimed", "claimed_task": task, "run_info": run}

    def route_claim(self, state: SupervisorState) -> Literal["execute", "END"]:
        if state.get("status") == "claimed":
            return "execute"
        return "END"

    def execute(self, state: SupervisorState) -> dict:
        task = state["claimed_task"]
        workflow_type = str(task.get("workflow_id", ""))
        target_graph = self.graphs.get(workflow_type)
        if target_graph is None:
            return {
                "status": "failed",
                "error": f"No experimental graph is registered for workflow '{workflow_type}'",
            }

        try:
            metadata = dict(task.get("metadata") or {})
            initial_state = {
                **dict(metadata.get("inputs") or {}),
                "task_id": task["id"],
                "status": "initialised",
            }
            result = target_graph.invoke(initial_state)
            return {"status": "executed", "result": result}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    def finish(self, state: SupervisorState) -> dict:
        run = state["run_info"]
        if state["status"] == "executed":
            self.control.store.finish_execution(
                run["id"],
                worker_id=self.worker_id,
                succeeded=True,
                result=state["result"],
                max_attempts=self.max_attempts,
            )
            return {"status": "finished"}
        else:
            self.control.store.finish_execution(
                run["id"],
                worker_id=self.worker_id,
                succeeded=False,
                error=state.get("error", "Unknown error"),
                retryable=True,
                max_attempts=self.max_attempts,
            )
            return {"status": "failed"}

    def tick(self, *, workflow_id: str | None = None) -> dict[str, Any]:
        state = {
            "worker_id": self.worker_id,
            "workflow_id": workflow_id,
            "recovered": [],
            "claimed_task": None,
            "run_info": None,
            "result": None,
            "error": None,
            "status": "init"
        }
        final_state = self.compiled.invoke(state)
        return final_state
