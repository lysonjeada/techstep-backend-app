import traceback

from typing import Optional

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
)

from .schemas import StudyPlanResponse
from app.study_plan.service import create_study_plan

# Ajuste conforme os caminhos reais do seu projeto.
from app.llm_generation.pdf_utils import extract_text_from_pdf
from app.config import OPENAI_MODEL
from app.openai_client import client

router = APIRouter(
    prefix="/study-plan",
    tags=["Study Plan"],
)


@router.post(
    "/generate",
    response_model=StudyPlanResponse,
)
async def generate_study_plan(
    job_title: str = Form(...),
    seniority: str = Form(...),
    description: Optional[str] = Form(None),
    resume: Optional[UploadFile] = File(None),
):
    try:
        normalized_job_title = job_title.strip()
        normalized_seniority = seniority.strip()
        normalized_description = (
            description or ""
        ).strip()

        if not normalized_job_title:
            raise HTTPException(
                status_code=422,
                detail="O cargo é obrigatório.",
            )

        if not normalized_seniority:
            raise HTTPException(
                status_code=422,
                detail="A senioridade é obrigatória.",
            )

        resume_text = ""

        if resume is not None:
            try:
                filename = (
                    resume.filename or ""
                ).lower()

                content_type = (
                    resume.content_type or ""
                ).lower()

                is_pdf = (
                    filename.endswith(".pdf")
                    or content_type == "application/pdf"
                )

                if not is_pdf:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "O currículo deve estar "
                            "em formato PDF."
                        ),
                    )

                content = await resume.read()

                if content:
                    resume_text = extract_text_from_pdf(
                        content
                    )

            finally:
                await resume.close()

        return await create_study_plan(
            client=client,
            model=OPENAI_MODEL,
            job_title=normalized_job_title,
            seniority=normalized_seniority,
            description=normalized_description,
            resume_text=resume_text,
        )

    except HTTPException:
        raise

    except ValueError as error:
        traceback.print_exc()

        raise HTTPException(
            status_code=502,
            detail=str(error),
        )

    except Exception as error:
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao gerar plano de estudos: {}"
            ).format(str(error)),
        )