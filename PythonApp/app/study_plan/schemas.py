from typing import List

from pydantic import BaseModel

class StudyPlanTopicResponse(BaseModel):
    title: str
    description: str
    priority: str
    estimated_hours: int
    subtopics: List[str]
    practice: str

class StudyPlanResponse(BaseModel):
    title: str
    summary: str
    estimated_total_hours: int
    topics: List[StudyPlanTopicResponse]