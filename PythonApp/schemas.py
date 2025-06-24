from pydantic import BaseModel
from typing import Optional
from datetime import date
from uuid import UUID
from datetime import datetime

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
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
