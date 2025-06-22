from pydantic import BaseModel
from typing import Optional
from datetime import date
from uuid import UUID

class InterviewBase(BaseModel):
    company_name: str
    job_title: str
    last_interview_date: Optional[date] = None
    next_interview_date: Optional[date] = None
    location: Optional[str] = None
    notes: Optional[str] = None

class InterviewCreate(InterviewBase):
    pass

class InterviewUpdate(InterviewBase):
    pass

class InterviewOut(InterviewBase):
    id: UUID
    created_at: str
    updated_at: str

    class Config:
        orm_mode = True
