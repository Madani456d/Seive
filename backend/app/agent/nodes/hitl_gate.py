from langgraph.types import interrupt
from app.agent.state import AgentState
from app.schemas.lead import RawLead


def hitl_gate_node(state: AgentState) -> dict:
    pending = state.get("prefiltered_leads", [])
    estimated_cost = round(len(pending) * 0.02, 4)

    decision = interrupt({
        "message": "Review pre-filtered leads before waterfall enrichment.",
        "pending_leads": [
            lead.model_dump() if hasattr(lead, "model_dump") else lead
            for lead in pending
        ],
        "estimated_cost_usd": estimated_cost,
    })

    approved = bool(decision.get("approved", False))
    raw_approved = decision.get("approved_leads")

    if not approved:
        approved_leads = []
    elif raw_approved is None:
        approved_leads = pending
    else:
        approved_leads = [
            lead if isinstance(lead, RawLead) else RawLead(**lead)
            for lead in raw_approved
        ]

    return {
        "hitl_approved": approved,
        "approved_leads": approved_leads,
    }
