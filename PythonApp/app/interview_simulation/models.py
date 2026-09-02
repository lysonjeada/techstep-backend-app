import uuid

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class InterviewQuestionSet(Base):
    __tablename__ = "interview_question_sets"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    job_title = Column(
        String(150),
        nullable=False,
    )

    seniority = Column(
        String(80),
        nullable=False,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=True,
        index=True,
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    questions = relationship(
        "SavedInterviewQuestion",
        back_populates="question_set",
        cascade="all, delete-orphan",
        order_by="SavedInterviewQuestion.position",
    )


class SavedInterviewQuestion(Base):
    __tablename__ = "saved_interview_questions"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    question_set_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "interview_question_sets.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    text = Column(
        Text,
        nullable=False,
    )

    position = Column(
        Integer,
        nullable=False,
    )

    question_set = relationship(
        "InterviewQuestionSet",
        back_populates="questions",
    )