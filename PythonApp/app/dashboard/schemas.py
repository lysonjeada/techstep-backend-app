from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    total_applications: int
    completed_interviews: int
    scheduled_interviews: int
    response_rate: float
    offers_count: int
    active_companies_count: int


class SkillDemandItem(BaseModel):
    skill: str
    count: int
    percentage: float


class ActiveCompanyItem(BaseModel):
    company_name: str
    active_processes: int
    latest_activity: Optional[datetime] = None


class MonthlyProgressItem(BaseModel):
    month: str
    label: str
    applications: int
    interviews: int
    offers: int


class ProgressDashboardResponse(BaseModel):
    summary: DashboardSummary
    top_skills: List[SkillDemandItem]
    active_companies: List[ActiveCompanyItem]
    monthly_evolution: List[MonthlyProgressItem]