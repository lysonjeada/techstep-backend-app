from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SaveGeneratedQuestionsRequest(BaseModel):
    job_title: str
    seniority: str
    questions: List[str]


class SaveGeneratedQuestionsResponse(BaseModel):
    id: UUID
    saved_count: int
    message: str


class SavedQuestionSetOut(BaseModel):
    id: UUID
    job_title: str
    seniority: str
    questions: List[str]
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True
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