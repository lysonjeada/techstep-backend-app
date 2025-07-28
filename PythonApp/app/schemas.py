from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID
import uuid

class InterviewBase(BaseModel):
    company_name: str
    job_title: str
    job_seniority: str
    location: Optional[str] = None
    last_interview_date: Optional[datetime] = None
    next_interview_date: Optional[datetime] = None
    notes: Optional[str] = None
    skills: List[str] = [""]

    model_config = ConfigDict(from_attributes=True)

class InterviewCreate(InterviewBase):
    pass

class InterviewUpdate(InterviewBase):
    pass

class InterviewOut(BaseModel):
    id: UUID
    company_name: str
    job_title: str
    job_seniority: str
    location: Optional[str] = None
    last_interview_date: Optional[date] 
    next_interview_date: Optional[date]
    notes: Optional[str]
    skills: Optional[List[str]] = None 
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

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
    email: Optional[str]
    username: Optional[str]

    model_config = ConfigDict(from_attributes=True)