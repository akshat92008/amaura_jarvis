from typing import Literal, Annotated, Any
import operator
from langgraph.graph import StateGraph, END
from typing import TypedDict
from jarvis.amaura.actions import AmauraActions

class ContentWorkflowState(TypedDict):
    campaign_id: str
    asset_id: str | None
    topic: str
    outline: str | None
    draft: str | None
    review_status: str | None
    status: str

class ContentWorkflowGraph:
    def __init__(self, actions: AmauraActions):
        self.actions = actions
        self.graph = StateGraph(ContentWorkflowState)
        self._build_graph()

    def _build_graph(self) -> None:
        self.graph.add_node("ideate", self.ideate)
        self.graph.add_node("outline", self.outline)
        self.graph.add_node("draft", self.draft)
        self.graph.add_node("review", self.review)
        self.graph.add_node("publish", self.publish)

        self.graph.set_entry_point("ideate")
        self.graph.add_edge("ideate", "outline")
        self.graph.add_edge("outline", "draft")
        self.graph.add_edge("draft", "review")
        
        self.graph.add_conditional_edges(
            "review",
            self.route_after_review,
            {"publish": "publish", "draft": "draft"}
        )
        
        self.graph.add_edge("publish", END)
        self.compiled = self.graph.compile()

    def ideate(self, state: ContentWorkflowState) -> dict:
        return {"status": "ideated"}

    def outline(self, state: ContentWorkflowState) -> dict:
        return {"status": "outlined", "outline": "1. Intro\n2. Body\n3. Conclusion"}

    def draft(self, state: ContentWorkflowState) -> dict:
        return {"status": "drafted", "draft": "This is the content body."}

    def review(self, state: ContentWorkflowState) -> dict:
        return {"status": "reviewed", "review_status": "approved"}

    def route_after_review(self, state: ContentWorkflowState) -> Literal["publish", "draft"]:
        if state["review_status"] == "approved":
            return "publish"
        return "draft"

    def publish(self, state: ContentWorkflowState) -> dict:
        return {"status": "published"}
