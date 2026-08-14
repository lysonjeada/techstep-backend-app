from math import ceil
from typing import Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

class TutorBase(BaseModel):
    name: str
    profession: str

    years_of_experience: int = Field(
        ge=0
    )

    levels: list[str] = Field(
        default_factory=list
    )

    hourly_rate: float = Field(
        ge=0
    )

    language: str

    profile_image_url: Optional[str] = None
    bio: Optional[str] = None


class TutorCreate(TutorBase):
    user_id: Optional[UUID] = None


class TutorOut(TutorBase):
    id: UUID
    user_id: Optional[UUID] = None

    model_config = ConfigDict(
        from_attributes=True
    )


class TutorPageResponse(BaseModel):
    items: list[TutorOut]

    page: int
    page_size: int

    total: int
    total_pages: int

    has_next: bool
    has_previous: bool

    @classmethod
    def create(
        cls,
        *,
        items: list,
        page: int,
        page_size: int,
        total: int,
    ):
        total_pages = (
            ceil(total / page_size)
            if total > 0
            else 0
        )

        return cls(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        )