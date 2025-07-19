from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid 

class InterviewBase(BaseModel):
    company_name: str
    job_title: str
    job_seniority: str
    location: str
    last_interview_date: Optional[datetime]
    next_interview_date: Optional[datetime]
    notes: Optional[str] = None
    skills: List[str]

    class Config:
        orm_mode = True

class InterviewCreate(InterviewBase):
    pass

class InterviewUpdate(InterviewBase):
    pass

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from uuid import UUID

class InterviewOut(BaseModel):
    id: UUID
    company_name: str
    job_title: str
    job_seniority: str
    location: Optional[str] = None
    last_interview_date: Optional[str]
    next_interview_date: Optional[str]
    notes: Optional[str]
    skills: Optional[List[str]] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

    @classmethod
    def from_orm(cls, obj):
        return cls(
            id=obj.id,
            company_name=obj.company_name,
            job_title=obj.job_title,
            job_seniority=obj.job_seniority,
            location=obj.location,
            last_interview_date=obj.last_interview_date.strftime("%d/%m/%Y") if obj.last_interview_date else None,
            next_interview_date=obj.next_interview_date.strftime("%d/%m/%Y") if obj.next_interview_date else None,
            notes=obj.notes,
            skills=obj.skills or [],
            created_at=obj.created_at,
            updated_at=obj.updated_at
        )

# --- Novos Schemas para Usuário ---

class UserBase(BaseModel):
    email: str = Field(..., example="user@example.com")
    username: str = Field(..., example="devjunior")

class UserCreate(UserBase):
    password: str = Field(..., min_length=6, example="minhasenhaforte") # A senha que será hashed

class UserLogin(BaseModel):
    username: str = Field(..., example="devjunior") # Pode ser email também, sua escolha
    password: str = Field(..., example="minhasenhaforte")

class UserUpdate(BaseModel):
    email: Optional[str] = Field(None, example="novo_email@example.com")
    username: Optional[str] = Field(None, example="novo_devjunior")
    password: Optional[str] = Field(None, min_length=6, example="nova_senha_forte")

class UserOut(UserBase):
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True # Ou orm_mode = True para versões mais antigas do Pydantic