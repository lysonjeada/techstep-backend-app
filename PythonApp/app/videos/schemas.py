from datetime import datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
)


class VideoOut(BaseModel):
    id: UUID
    user_id: UUID

    title: str
    description: str | None

    status: str
    rejection_reason: str | None

    created_at: datetime
    reviewed_at: datetime | None

    stream_path: str | None = None

    model_config = ConfigDict(
        from_attributes=True
    )


class VideoPageResponse(BaseModel):
    items: list[VideoOut]

    page: int
    page_size: int

    total: int
    total_pages: int

    has_next: bool