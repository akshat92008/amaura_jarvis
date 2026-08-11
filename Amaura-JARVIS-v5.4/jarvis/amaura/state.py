from typing import TypedDict, Annotated, Any
import operator

class LeadWorkflowState(TypedDict):
    campaign_id: str
    lead_id: str | None
    lead_data: dict[str, Any]
    research_data: dict[str, Any]
    draft_message_id: str | None
    status: str
    errors: Annotated[list[str], operator.add]
    review_status: str | None

class CampaignState(TypedDict):
    campaign_id: str
    config: dict[str, Any]
    active_leads: Annotated[list[str], operator.add]
    completed_leads: Annotated[list[str], operator.add]
    failed_leads: Annotated[list[str], operator.add]
