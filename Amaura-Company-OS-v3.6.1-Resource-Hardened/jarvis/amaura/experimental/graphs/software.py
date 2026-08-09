from typing import Literal, Annotated, Any
import operator
from langgraph.graph import StateGraph, END
from typing import TypedDict
from jarvis.amaura.actions import AmauraActions

class SoftwareWorkflowState(TypedDict):
    task_id: str
    repository: str
    branch: str
    diff: str | None
    test_results: dict[str, Any]
    status: str
    errors: Annotated[list[str], operator.add]

class SoftwareWorkflowGraph:
    def __init__(self, actions: AmauraActions):
        self.actions = actions
        self.graph = StateGraph(SoftwareWorkflowState)
        self._build_graph()

    def _build_graph(self) -> None:
        self.graph.add_node("setup_workspace", self.setup_workspace)
        self.graph.add_node("implement", self.implement)
        self.graph.add_node("test", self.test)
        self.graph.add_node("review", self.review)
        self.graph.add_node("merge", self.merge)

        self.graph.set_entry_point("setup_workspace")
        self.graph.add_edge("setup_workspace", "implement")
        self.graph.add_edge("implement", "test")
        
        self.graph.add_conditional_edges(
            "test",
            self.route_after_test,
            {"implement": "implement", "review": "review"}
        )
        
        self.graph.add_conditional_edges(
            "review",
            self.route_after_review,
            {"implement": "implement", "merge": "merge"}
        )
        
        self.graph.add_edge("merge", END)
        self.compiled = self.graph.compile()

    def setup_workspace(self, state: SoftwareWorkflowState) -> dict:
        return {"status": "workspace_ready"}

    def implement(self, state: SoftwareWorkflowState) -> dict:
        return {"status": "implemented", "diff": "+ dummy code"}

    def test(self, state: SoftwareWorkflowState) -> dict:
        return {"status": "tested", "test_results": {"passed": True}}

    def route_after_test(self, state: SoftwareWorkflowState) -> Literal["implement", "review"]:
        results = state.get("test_results", {})
        if results.get("passed"):
            return "review"
        return "implement"

    def review(self, state: SoftwareWorkflowState) -> dict:
        return {"status": "reviewed"}

    def route_after_review(self, state: SoftwareWorkflowState) -> Literal["merge", "implement"]:
        if state["status"] == "reviewed":
            return "merge"
        return "implement"

    def merge(self, state: SoftwareWorkflowState) -> dict:
        return {"status": "merged"}
