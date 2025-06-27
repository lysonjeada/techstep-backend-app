from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from uuid import UUID

class InterviewBase(BaseModel):
    company_name: str
    job_title: str
    job_seniority: str
    last_interview_date: Optional[date] = None
    next_interview_date: Optional[date] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    skills: Optional[List[str]] = None  # 🆕 lista de skills

class InterviewCreate(InterviewBase):
    pass

class InterviewUpdate(InterviewBase):
    pass

class InterviewOut(InterviewBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

