from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID
import uuid
import asyncio
import json
import os
import re
import tempfile
import traceback

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    UploadFile,
)


router = APIRouter()

OPENAI_MODEL = os.getenv(
    "OPENAI_INTERVIEW_MODEL",
    "gpt-4",
)

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

    @field_validator(
        "company_name",
        "job_title",
        "job_seniority",
        "location",
        mode="before",
    )
    @classmethod
    def format_text_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        return format_title(value)

    @field_validator("skills", mode="before")
    @classmethod
    def format_skills(
        cls,
        value: Optional[List[str]],
    ) -> Optional[List[str]]:
        if value is None:
            return None

        return [
            format_title(skill)
            for skill in value
            if skill and skill.strip()
        ]

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

SPECIAL_NAMES = {
    "ios": "iOS",
    "swiftui": "SwiftUI",
    "ui": "UI",
    "ux": "UX",
    "sql": "SQL",
    "api": "API",
    "aws": "AWS",
    "php": "PHP",
    "html": "HTML",
    "css": "CSS",
}

def format_title(value: str) -> str:
    words = value.strip().split()

    return " ".join(
        SPECIAL_NAMES.get(word.lower(), word.capitalize())
        for word in words
    )


class SimulationQuestionsRequest(BaseModel):
    job_title: str
    seniority: str
    description: Optional[str] = None


class SimulationAnswerRequest(BaseModel):
    question: str
    answer: str
    response_time_seconds: int


class SimulationEvaluationRequest(BaseModel):
    job_title: str
    seniority: str
    answers: List[SimulationAnswerRequest]


class SimulationEvaluationResponse(BaseModel):
    clarity: int
    objectivity: int
    examples: int
    technical_knowledge: int
    response_time: int
    overall: int
    summary: str
    strengths: List[str]
    improvements: List[str]