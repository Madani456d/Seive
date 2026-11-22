from typing import List, Optional, TypedDict
from app.schemas.lead import ICPPlan, RawLead, EnrichedLead, ScoredLead


class AgentState(TypedDict, total=False):
    run_id: str
    user_query: str
    icp_plan: Optional[ICPPlan]
    raw_leads: List[RawLead]
    approved_leads: List[RawLead]
    enriched_leads: List[EnrichedLead]
    scored_leads: List[ScoredLead]
    budget_spent_usd: float
    hitl_approved: bool
    errors: List[str]
