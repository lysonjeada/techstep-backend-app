from sqlalchemy import Column, String, Date, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from .database import Base

class Interview(Base):
    __tablename__ = "interviews"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    company_name = Column(
        Text,
        nullable=False,
    )

    job_title = Column(
        Text,
        nullable=False,
    )

    job_seniority = Column(
        Text,
        nullable=True,
    )

    last_interview_date = Column(
        Date,
        nullable=True,
    )

    next_interview_date = Column(
        Date,
        nullable=True,
    )

    location = Column(
        Text,
        nullable=True,
    )

    notes = Column(
        Text,
        nullable=True,
    )

    skills = Column(
        ARRAY(String),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    status = Column(
        String(30),
        nullable=False,
        default="applied",
        server_default="applied",
    )

    user = relationship(
        "User",
        back_populates="interviews",
    )


class User(Base):
    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    email = Column(
        String,
        unique=True,
        index=True,
        nullable=False,
    )

    username = Column(
        String,
        unique=True,
        index=True,
        nullable=False,
    )

    hashed_password = Column(
        String,
        nullable=False,
    )

    is_active = Column(
        Boolean,
        default=True,
    )

    created_at = Column(
        DateTime,
        default=func.now(),
    )

    updated_at = Column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
    )

    is_email_verified = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    verification_codes = relationship(
        "EmailVerificationCode",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    interviews = relationship(
        "Interview",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    tutor_profile = relationship(
        "TutorProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    refresh_tokens = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    videos = relationship(
    "Video",
    back_populates="user",
    cascade="all, delete-orphan",
    passive_deletes=True,
    )
