from typing import Literal
from langgraph.graph import StateGraph, END
from jarvis.amaura.state import LeadWorkflowState
from jarvis.amaura.actions import AmauraActions

class LeadWorkflowGraph:
    def __init__(self, actions: AmauraActions):
        self.actions = actions
        self.graph = StateGraph(LeadWorkflowState)
        self._build_graph()

    def _build_graph(self) -> None:
        # Define nodes
        self.graph.add_node("discover", self.discover)
        self.graph.add_node("validate", self.validate)
        self.graph.add_node("research", self.research)
        self.graph.add_node("qualify", self.qualify)
        self.graph.add_node("draft", self.draft)
        self.graph.add_node("review", self.review)
        self.graph.add_node("approve", self.approve)

        # Set entry point
        self.graph.set_entry_point("discover")

        # Define edges
        self.graph.add_edge("discover", "validate")
        
        self.graph.add_conditional_edges(
            "validate",
            self.route_after_validate,
            {"research": "research", "END": END}
        )
        
        self.graph.add_edge("research", "qualify")
        
        self.graph.add_conditional_edges(
            "qualify",
            self.route_after_qualify,
            {"draft": "draft", "END": END}
        )
        
        self.graph.add_edge("draft", "review")
        
        self.graph.add_conditional_edges(
            "review",
            self.route_after_review,
            {"approve": "approve", "draft": "draft"}
        )
        
        self.graph.add_edge("approve", END)

        self.compiled = self.graph.compile()

    def discover(self, state: LeadWorkflowState) -> dict:
        lead_data = state["lead_data"]
        lead_id = self.actions.discover_lead(
            campaign_id=state["campaign_id"],
            company_name=lead_data.get("company_name", ""),
            domain_name=lead_data.get("domain_name", ""),
            source_url=lead_data.get("source_url", "")
        )
        return {"lead_id": lead_id, "status": "discovered"}

    def validate(self, state: LeadWorkflowState) -> dict:
        # In a real impl, you'd check domains, verify company exists
        if not state.get("lead_id"):
            return {"status": "invalid"}
        self.actions.transition_lead(state["lead_id"], "validated", "Domain is active and company exists.")
        return {"status": "validated"}

    def route_after_validate(self, state: LeadWorkflowState) -> Literal["research", "END"]:
        if state["status"] == "validated":
            return "research"
        return "END"

    def research(self, state: LeadWorkflowState) -> dict:
        # Example of adding evidence
        self.actions.add_evidence(
            lead_id=state["lead_id"],
            claim_type="technology_stack",
            claim="Uses Python",
            source_url="http://example.com",
            source_excerpt="Built with Python.",
            confidence=0.9
        )
        self.actions.transition_lead(state["lead_id"], "researched", "Gathered initial evidence.")
        return {"status": "researched"}

    def qualify(self, state: LeadWorkflowState) -> dict:
        res = self.actions.score_lead(state["lead_id"], {"tech_stack": 10, "company_size": 5})
        score = res.get("score", 0)
        if score >= 10:
            self.actions.transition_lead(state["lead_id"], "qualified", "Score meets threshold.")
            return {"status": "qualified"}
        
        self.actions.transition_lead(state["lead_id"], "unqualified", "Score too low.")
        return {"status": "unqualified"}

    def route_after_qualify(self, state: LeadWorkflowState) -> Literal["draft", "END"]:
        if state["status"] == "qualified":
            return "draft"
        return "END"

    def draft(self, state: LeadWorkflowState) -> dict:
        msg_id = self.actions.stage_message(
            lead_id=state["lead_id"],
            recipient="contact@" + state["lead_data"].get("domain_name", "example.com"),
            channel="email",
            message_type="outbound",
            subject="Collaboration",
            body="Hello, we would like to collaborate."
        )
        return {"draft_message_id": msg_id, "status": "drafted"}

    def review(self, state: LeadWorkflowState) -> dict:
        # Placeholder for AI review
        # Ideally would trigger a self-correction loop
        return {"status": "reviewed", "review_status": "approved"}

    def route_after_review(self, state: LeadWorkflowState) -> Literal["approve", "draft"]:
        if state["review_status"] == "approved":
            return "approve"
        return "draft"

    def approve(self, state: LeadWorkflowState) -> dict:
        # Founder approval or auto-approve
        self.actions.decide_message(
            message_id=state["draft_message_id"],
            approve=True,
            reason="Auto-approved by LangGraph worker"
        )
        return {"status": "approved"}
