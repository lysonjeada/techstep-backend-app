import uuid

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY,
    UUID,
)
from sqlalchemy.orm import relationship

from app.database import Base


class TutorProfile(Base):
    __tablename__ = "tutor_profiles"

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
        nullable=True,
        unique=True,
        index=True,
    )

    name = Column(
        String(120),
        nullable=False,
    )

    profession = Column(
        String(120),
        nullable=False,
    )

    years_of_experience = Column(
        Integer,
        nullable=False,
        default=0,
    )

    levels = Column(
        ARRAY(String),
        nullable=False,
        default=list,
    )

    hourly_rate = Column(
        Float,
        nullable=False,
    )

    language = Column(
        String(80),
        nullable=False,
    )

    profile_image_url = Column(
        String,
        nullable=True,
    )

    bio = Column(
        Text,
        nullable=True,
    )

    user = relationship(
        "User",
        back_populates="tutor_profile",
    )