# app/interviews/router.py

import time

from datetime import date
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from sqlalchemy.orm import Session

from app.database import get_db

from app.observability import (
    logger,
)

from app.auth.dependencies import (
    get_current_user,
)

from .. import (
    models,
    schemas,
)


router = APIRouter(
    prefix="/interviews",
    tags=["Interviews"],
)


# MARK: - Create Interview


@router.post(
    "/",
    response_model=schemas.InterviewOut,
    status_code=status.HTTP_201_CREATED,
)
def create_interview(
    interview: schemas.InterviewCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(
        get_current_user
    ),
):
    started_at = time.perf_counter()

    logger.info(
        "interview creation started",
        extra={
            "event":
                "interview_creation_started",
            "userId":
                str(current_user.id),
            "companyName":
                interview.company_name,
            "jobTitle":
                interview.job_title,
            "seniority":
                interview.job_seniority,
            "hasNextInterviewDate":
                interview.next_interview_date
                is not None,
            "hasLastInterviewDate":
                interview.last_interview_date
                is not None,
        },
    )

    try:
        db_interview = models.Interview(
            **interview.model_dump(),
            user_id=current_user.id,
        )

        db.add(
            db_interview
        )

        db.commit()

        db.refresh(
            db_interview
        )

        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.info(
            "interview created successfully",
            extra={
                "event":
                    "interview_created",
                "userId":
                    str(current_user.id),
                "interviewId":
                    str(db_interview.id),
                "companyName":
                    db_interview.company_name,
                "durationMs":
                    duration_ms,
            },
        )

        return db_interview

    except Exception as error:
        db.rollback()

        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.exception(
            "failed to create interview",
            extra={
                "event":
                    "interview_creation_failed",
                "userId":
                    str(current_user.id),
                "companyName":
                    interview.company_name,
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=
                "Erro ao salvar entrevista.",
        ) from error


# MARK: - Upcoming Interviews
#
# Essa rota fica ANTES de /{interview_id}
# para evitar conflito com a rota dinâmica.


@router.get(
    "/next/",
    response_model=list[
        schemas.InterviewOut
    ],
)
def get_upcoming_interviews(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(
        get_current_user
    ),
):
    started_at = time.perf_counter()

    today = date.today()

    logger.info(
        "upcoming interviews request started",
        extra={
            "event":
                "upcoming_interviews_request_started",
            "userId":
                str(current_user.id),
            "referenceDate":
                str(today),
        },
    )

    try:
        upcoming_interviews = (
            db.query(
                models.Interview
            )
            .filter(
                models.Interview.user_id
                == current_user.id,
                models.Interview
                .next_interview_date
                .isnot(None),
                models.Interview
                .next_interview_date
                >= today,
            )
            .order_by(
                models.Interview
                .next_interview_date
                .asc()
            )
            .all()
        )

        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.info(
            "upcoming interviews retrieved",
            extra={
                "event":
                    "upcoming_interviews_retrieved",
                "userId":
                    str(current_user.id),
                "interviewCount":
                    len(
                        upcoming_interviews
                    ),
                "referenceDate":
                    str(today),
                "durationMs":
                    duration_ms,
            },
        )

        return upcoming_interviews

    except Exception as error:
        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.exception(
            "failed to retrieve upcoming interviews",
            extra={
                "event":
                    "upcoming_interviews_failed",
                "userId":
                    str(current_user.id),
                "referenceDate":
                    str(today),
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Erro ao buscar "
                "próximas entrevistas."
            ),
        ) from error


# MARK: - List Interviews


@router.get(
    "/",
    response_model=list[
        schemas.InterviewOut
    ],
)
def list_interviews(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(
        get_current_user
    ),
):
    started_at = time.perf_counter()

    logger.info(
        "interview list request started",
        extra={
            "event":
                "interview_list_request_started",
            "userId":
                str(current_user.id),
        },
    )

    try:
        interviews = (
            db.query(
                models.Interview
            )
            .filter(
                models.Interview.user_id
                == current_user.id
            )
            .order_by(
                models.Interview
                .created_at
                .desc()
            )
            .all()
        )

        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.info(
            "interviews retrieved successfully",
            extra={
                "event":
                    "interview_list_retrieved",
                "userId":
                    str(current_user.id),
                "interviewCount":
                    len(interviews),
                "durationMs":
                    duration_ms,
            },
        )

        return interviews

    except Exception as error:
        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.exception(
            "failed to retrieve interviews",
            extra={
                "event":
                    "interview_list_failed",
                "userId":
                    str(current_user.id),
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Erro ao buscar entrevistas."
            ),
        ) from error


# MARK: - Read Interview


@router.get(
    "/{interview_id}",
    response_model=schemas.InterviewOut,
)
def read_interview(
    interview_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(
        get_current_user
    ),
):
    started_at = time.perf_counter()

    logger.info(
        "interview detail request started",
        extra={
            "event":
                "interview_detail_request_started",
            "userId":
                str(current_user.id),
            "interviewId":
                str(interview_id),
        },
    )

    try:
        interview = (
            db.query(
                models.Interview
            )
            .filter(
                models.Interview.id
                == interview_id,
                models.Interview.user_id
                == current_user.id,
            )
            .first()
        )

        if interview is None:
            logger.info(
                "interview not found",
                extra={
                    "event":
                        "interview_not_found",
                    "userId":
                        str(
                            current_user.id
                        ),
                    "interviewId":
                        str(
                            interview_id
                        ),
                },
            )

            raise HTTPException(
                status_code=
                    status.HTTP_404_NOT_FOUND,
                detail=(
                    "Entrevista não encontrada."
                ),
            )

        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.info(
            "interview detail retrieved",
            extra={
                "event":
                    "interview_detail_retrieved",
                "userId":
                    str(current_user.id),
                "interviewId":
                    str(interview.id),
                "durationMs":
                    duration_ms,
            },
        )

        return interview

    except HTTPException:
        raise

    except Exception as error:
        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.exception(
            "failed to retrieve interview detail",
            extra={
                "event":
                    "interview_detail_failed",
                "userId":
                    str(current_user.id),
                "interviewId":
                    str(interview_id),
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Erro ao buscar entrevista."
            ),
        ) from error


# MARK: - Update Interview


@router.put(
    "/{interview_id}",
    response_model=schemas.InterviewOut,
)
def update_interview(
    interview_id: UUID,
    updated: schemas.InterviewUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(
        get_current_user
    ),
):
    started_at = time.perf_counter()

    updated_fields = (
        updated.model_dump(
            exclude_unset=True
        )
    )

    logger.info(
        "interview update started",
        extra={
            "event":
                "interview_update_started",
            "userId":
                str(current_user.id),
            "interviewId":
                str(interview_id),
            "updatedFields":
                list(
                    updated_fields.keys()
                ),
        },
    )

    try:
        interview = (
            db.query(
                models.Interview
            )
            .filter(
                models.Interview.id
                == interview_id,
                models.Interview.user_id
                == current_user.id,
            )
            .first()
        )

        if interview is None:
            logger.info(
                "interview update target not found",
                extra={
                    "event":
                        "interview_update_not_found",
                    "userId":
                        str(
                            current_user.id
                        ),
                    "interviewId":
                        str(
                            interview_id
                        ),
                },
            )

            raise HTTPException(
                status_code=
                    status.HTTP_404_NOT_FOUND,
                detail=(
                    "Entrevista não encontrada."
                ),
            )

        for key, value in (
            updated_fields.items()
        ):
            setattr(
                interview,
                key,
                value,
            )

        db.commit()

        db.refresh(
            interview
        )

        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.info(
            "interview updated successfully",
            extra={
                "event":
                    "interview_updated",
                "userId":
                    str(current_user.id),
                "interviewId":
                    str(interview.id),
                "updatedFields":
                    list(
                        updated_fields.keys()
                    ),
                "durationMs":
                    duration_ms,
            },
        )

        return interview

    except HTTPException:
        raise

    except Exception as error:
        db.rollback()

        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.exception(
            "failed to update interview",
            extra={
                "event":
                    "interview_update_failed",
                "userId":
                    str(current_user.id),
                "interviewId":
                    str(interview_id),
                "updatedFields":
                    list(
                        updated_fields.keys()
                    ),
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Erro ao atualizar entrevista."
            ),
        ) from error


# MARK: - Delete Interview


@router.delete(
    "/{interview_id}"
)
def delete_interview(
    interview_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(
        get_current_user
    ),
):
    started_at = time.perf_counter()

    logger.info(
        "interview deletion started",
        extra={
            "event":
                "interview_deletion_started",
            "userId":
                str(current_user.id),
            "interviewId":
                str(interview_id),
        },
    )

    try:
        interview = (
            db.query(
                models.Interview
            )
            .filter(
                models.Interview.id
                == interview_id,
                models.Interview.user_id
                == current_user.id,
            )
            .first()
        )

        if interview is None:
            logger.info(
                "interview deletion target not found",
                extra={
                    "event":
                        "interview_deletion_not_found",
                    "userId":
                        str(
                            current_user.id
                        ),
                    "interviewId":
                        str(
                            interview_id
                        ),
                },
            )

            raise HTTPException(
                status_code=
                    status.HTTP_404_NOT_FOUND,
                detail=(
                    "Entrevista não encontrada."
                ),
            )

        db.delete(
            interview
        )

        db.commit()

        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.info(
            "interview deleted successfully",
            extra={
                "event":
                    "interview_deleted",
                "userId":
                    str(current_user.id),
                "interviewId":
                    str(interview_id),
                "durationMs":
                    duration_ms,
            },
        )

        return {
            "detail":
                "Interview deleted"
        }

    except HTTPException:
        raise

    except Exception as error:
        db.rollback()

        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.exception(
            "failed to delete interview",
            extra={
                "event":
                    "interview_deletion_failed",
                "userId":
                    str(current_user.id),
                "interviewId":
                    str(interview_id),
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Erro ao excluir entrevista."
            ),
        ) from error