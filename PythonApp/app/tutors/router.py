from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from app.database import get_db

from . import (
    models,
    schemas,
)


router = APIRouter(
    prefix="/tutors",
    tags=["Tutors"],
)


@router.get(
    "/",
    response_model=
        schemas.TutorPageResponse,
)
def list_tutors(
    page: int = Query(
        default=1,
        ge=1,
    ),
    page_size: int = Query(
        default=10,
        ge=1,
        le=50,
    ),
    db: Session = Depends(get_db),
):
    query = db.query(
        models.TutorProfile
    )

    total = query.count()

    offset = (
        page - 1
    ) * page_size

    tutors = (
        query
        .order_by(
            models.TutorProfile
            .name.asc()
        )
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return (
        schemas.TutorPageResponse
        .create(
            items=tutors,
            page=page,
            page_size=page_size,
            total=total,
        )
    )


@router.get(
    "/{tutor_id}",
    response_model=schemas.TutorOut,
)
def get_tutor(
    tutor_id: UUID,
    db: Session = Depends(get_db),
):
    tutor = (
        db.query(
            models.TutorProfile
        )
        .filter(
            models.TutorProfile.id
            == tutor_id
        )
        .first()
    )

    if tutor is None:
        raise HTTPException(
            status_code=
                status.HTTP_404_NOT_FOUND,
            detail=
                "Tutor não encontrado.",
        )

    return tutor