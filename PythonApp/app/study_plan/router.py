# app/study_plan/router.py

import time

from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)

from app.config import OPENAI_MODEL
from app.llm_generation.pdf_utils import (
    extract_text_from_pdf,
)
from app.observability import logger
from app.openai_client import client
from app.rate_limit.service import (
    OPENAI_ENDPOINT_MAX,
    OPENAI_ENDPOINT_WINDOW_SECONDS,
    ip_rate_limiter,
)
from app.study_plan.service import (
    create_study_plan,
)

from .schemas import StudyPlanResponse


router = APIRouter(
    prefix="/study-plan",
    tags=["Study Plan"],
)


# MARK: - Generate Study Plan


@router.post(
    "/generate",
    response_model=StudyPlanResponse,
)
async def generate_study_plan(
    job_title: str = Form(...),
    seniority: str = Form(...),
    description: Optional[str] = Form(
        None
    ),
    resume: Optional[UploadFile] = File(
        None
    ),
    _rate_limit: None = Depends(
        ip_rate_limiter(
            "openai-study-plan",
            OPENAI_ENDPOINT_MAX,
            OPENAI_ENDPOINT_WINDOW_SECONDS,
        )
    ),
):
    started_at = time.perf_counter()

    normalized_job_title = (
        job_title.strip()
    )

    normalized_seniority = (
        seniority.strip()
    )

    normalized_description = (
        description or ""
    ).strip()

    logger.info(
        "study plan generation started",
        extra={
            "event":
                "study_plan_generation_started",
            "jobTitle":
                normalized_job_title,
            "seniority":
                normalized_seniority,
            "hasDescription":
                bool(
                    normalized_description
                ),
            "hasResume":
                resume is not None,
            "model":
                OPENAI_MODEL,
        },
    )

    try:
        # MARK: - Validation

        if not normalized_job_title:
            logger.info(
                "study plan generation rejected because job title is empty",
                extra={
                    "event":
                        "study_plan_validation_failed",
                    "field":
                        "job_title",
                    "statusCode":
                        422,
                },
            )

            raise HTTPException(
                status_code=422,
                detail=(
                    "O cargo é obrigatório."
                ),
            )

        if not normalized_seniority:
            logger.info(
                "study plan generation rejected because seniority is empty",
                extra={
                    "event":
                        "study_plan_validation_failed",
                    "field":
                        "seniority",
                    "jobTitle":
                        normalized_job_title,
                    "statusCode":
                        422,
                },
            )

            raise HTTPException(
                status_code=422,
                detail=(
                    "A senioridade "
                    "é obrigatória."
                ),
            )

        # MARK: - Resume

        resume_text = ""

        if resume is not None:
            try:
                filename = (
                    resume.filename or ""
                ).lower()

                content_type = (
                    resume.content_type or ""
                ).lower()

                logger.info(
                    "resume received for study plan generation",
                    extra={
                        "event":
                            "study_plan_resume_received",
                        "jobTitle":
                            normalized_job_title,
                        "seniority":
                            normalized_seniority,
                        "fileName":
                            filename,
                        "contentType":
                            content_type,
                    },
                )

                is_pdf = (
                    filename.endswith(
                        ".pdf"
                    )
                    or content_type
                    == "application/pdf"
                )

                if not is_pdf:
                    logger.info(
                        "study plan resume rejected because file is not pdf",
                        extra={
                            "event":
                                "study_plan_resume_validation_failed",
                            "jobTitle":
                                normalized_job_title,
                            "seniority":
                                normalized_seniority,
                            "fileName":
                                filename,
                            "contentType":
                                content_type,
                            "statusCode":
                                422,
                        },
                    )

                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "O currículo deve "
                            "estar em formato PDF."
                        ),
                    )

                content = (
                    await resume.read()
                )

                logger.info(
                    "study plan resume file read",
                    extra={
                        "event":
                            "study_plan_resume_read",
                        "jobTitle":
                            normalized_job_title,
                        "seniority":
                            normalized_seniority,
                        "fileSizeBytes":
                            len(content),
                    },
                )

                if content:
                    extraction_started_at = (
                        time.perf_counter()
                    )

                    resume_text = (
                        extract_text_from_pdf(
                            content
                        )
                    )

                    extraction_duration_ms = (
                        round(
                            (
                                time.perf_counter()
                                - extraction_started_at
                            )
                            * 1000,
                            2,
                        )
                    )

                    logger.info(
                        "resume text extracted for study plan",
                        extra={
                            "event":
                                "study_plan_resume_extracted",
                            "jobTitle":
                                normalized_job_title,
                            "seniority":
                                normalized_seniority,
                            "resumeTextLength":
                                len(
                                    resume_text
                                ),
                            "durationMs":
                                extraction_duration_ms,
                        },
                    )

                else:
                    logger.info(
                        "empty resume file received for study plan",
                        extra={
                            "event":
                                "study_plan_resume_empty",
                            "jobTitle":
                                normalized_job_title,
                            "seniority":
                                normalized_seniority,
                        },
                    )

            finally:
                await resume.close()

                logger.info(
                    "study plan resume file closed",
                    extra={
                        "event":
                            "study_plan_resume_closed",
                        "jobTitle":
                            normalized_job_title,
                    },
                )

        # MARK: - Generate Plan

        logger.info(
            "study plan service call started",
            extra={
                "event":
                    "study_plan_service_started",
                "jobTitle":
                    normalized_job_title,
                "seniority":
                    normalized_seniority,
                "hasDescription":
                    bool(
                        normalized_description
                    ),
                "hasResumeText":
                    bool(
                        resume_text
                    ),
                "descriptionLength":
                    len(
                        normalized_description
                    ),
                "resumeTextLength":
                    len(
                        resume_text
                    ),
                "model":
                    OPENAI_MODEL,
            },
        )

        generation_started_at = (
            time.perf_counter()
        )

        study_plan = (
            await create_study_plan(
                client=client,
                model=
                    OPENAI_MODEL,
                job_title=
                    normalized_job_title,
                seniority=
                    normalized_seniority,
                description=
                    normalized_description,
                resume_text=
                    resume_text,
            )
        )

        generation_duration_ms = round(
            (
                time.perf_counter()
                - generation_started_at
            )
            * 1000,
            2,
        )

        total_duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.info(
            "study plan generated successfully",
            extra={
                "event":
                    "study_plan_generated",
                "jobTitle":
                    normalized_job_title,
                "seniority":
                    normalized_seniority,
                "model":
                    OPENAI_MODEL,
                "generationDurationMs":
                    generation_duration_ms,
                "durationMs":
                    total_duration_ms,
            },
        )

        return study_plan

    # MARK: - HTTP Errors

    except HTTPException as error:
        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.info(
            "study plan request rejected",
            extra={
                "event":
                    "study_plan_request_rejected",
                "jobTitle":
                    normalized_job_title,
                "seniority":
                    normalized_seniority,
                "statusCode":
                    error.status_code,
                "durationMs":
                    duration_ms,
            },
        )

        raise

    # MARK: - Invalid AI Response

    except ValueError as error:
        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.exception(
            "invalid study plan response",
            extra={
                "event":
                    "study_plan_invalid_response",
                "jobTitle":
                    normalized_job_title,
                "seniority":
                    normalized_seniority,
                "model":
                    OPENAI_MODEL,
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error

    # MARK: - Unexpected Errors

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
            "study plan generation failed",
            extra={
                "event":
                    "study_plan_generation_failed",
                "jobTitle":
                    normalized_job_title,
                "seniority":
                    normalized_seniority,
                "model":
                    OPENAI_MODEL,
                "hasDescription":
                    bool(
                        normalized_description
                    ),
                "hasResume":
                    resume is not None,
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao gerar plano "
                "de estudos."
            ),
        ) from error