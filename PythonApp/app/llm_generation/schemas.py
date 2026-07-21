from typing import List, Optional

from pydantic import BaseModel

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