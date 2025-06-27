from sqlalchemy import Column, String, Date, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
import uuid
from database import Base

class Interview(Base):
    __tablename__ = "interviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(Text, nullable=False)
    job_title = Column(Text, nullable=False)
    job_seniority = Column(Text, nullable=True)
    last_interview_date = Column(Date, nullable=True)
    next_interview_date = Column(Date, nullable=True)
    location = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    skills = Column(ARRAY(String), nullable=True) 
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
