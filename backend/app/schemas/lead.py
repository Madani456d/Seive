from typing import List, Optional
from pydantic import BaseModel, Field


class ICPPlan(BaseModel):
    target_industries: List[str] = Field(default_factory=list)
    company_size: str = "10-200 employees"
    target_roles: List[str] = Field(default_factory=list)
    search_queries: List[str] = Field(default_factory=list)


class RawLead(BaseModel):
    company_name: str
    domain: str
    description: str = ""
    industry: str = ""
    source: str = "mock"


class EnrichedLead(RawLead):
    contact_name: Optional[str] = None
    contact_role: Optional[str] = None
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    tech_stack: List[str] = Field(default_factory=list)
    enrichment_cost_usd: float = 0.0


class LeadScore(BaseModel):
    fit_score: int = Field(ge=0, le=100)
    reasoning: str
    outreach_angle: str


class ScoredLead(EnrichedLead):
    fit_score: int = 0
    reasoning: str = ""
    outreach_angle: str = ""
