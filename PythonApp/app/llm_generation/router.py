# app/llm_generation/router.py

import asyncio
import os
import re
import time

from typing import Optional

from dotenv import load_dotenv

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)

from openai import OpenAI

from .services import (
    extract_text_from_pdf,
)

from ..observability import logger

from ..worker.tasks import (
    process_resume_feedback,
)

from ..worker.celery_app import (
    celery_app,
)

from .schemas import (
    SimulationEvaluationRequest,
    SimulationEvaluationResponse,
    SimulationQuestionsRequest,
)

from app.credits.service import ai_credit_gate

from app.uploads.validation import (
    MAX_PDF_SIZE_BYTES,
    looks_like_pdf,
    read_upload_with_limit,
)


load_dotenv()


router = APIRouter(
    tags=["LLM Generation"]
)


client = OpenAI(
    api_key=os.getenv(
        "OPENAI_API_KEY"
    )
)


OPENAI_MODEL = os.getenv(
    "OPENAI_INTERVIEW_MODEL",
    "gpt-4",
)


# MARK: - Generate Interview Questions


@router.post(
    "/generate-interview-questions/"
)
async def generate_questions(
    job_title: str = Form(...),
    seniority: str = Form(...),
    description: Optional[str] = Form(
        None
    ),
    resume: Optional[UploadFile] = File(
        None
    ),
    _credit_gate=Depends(
        ai_credit_gate("generate_questions")
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
        "interview question generation started",
        extra={
            "event":
                "interview_questions_generation_started",
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
        },
    )

    try:
        if not normalized_job_title:
            raise HTTPException(
                status_code=422,
                detail=(
                    "O título da vaga "
                    "é obrigatório."
                ),
            )

        if not normalized_seniority:
            raise HTTPException(
                status_code=422,
                detail=(
                    "A senioridade "
                    "é obrigatória."
                ),
            )

        resume_text = ""

        # Currículo opcional.
        if resume is not None:
            try:
                logger.info(
                    "resume received for interview question generation",
                    extra={
                        "event":
                            "interview_questions_resume_received",
                        "contentType":
                            resume.content_type,
                        "fileName":
                            resume.filename,
                    },
                )

                if (
                    resume.content_type
                    and resume.content_type
                    != "application/pdf"
                ):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "O currículo deve "
                            "ser enviado em "
                            "formato PDF."
                        ),
                    )

                content = await read_upload_with_limit(
                    resume,
                    MAX_PDF_SIZE_BYTES,
                    detail=(
                        "O currículo excede o "
                        "tamanho máximo permitido."
                    ),
                )

                if content and not looks_like_pdf(content):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "O currículo deve "
                            "ser enviado em "
                            "formato PDF."
                        ),
                    )

                if content:
                    resume_text = (
                        extract_text_from_pdf(
                            content
                        )
                    )

                    logger.info(
                        "resume text extracted for interview questions",
                        extra={
                            "event":
                                "interview_questions_resume_extracted",
                            "resumeTextLength":
                                len(
                                    resume_text
                                ),
                        },
                    )

            finally:
                await resume.close()

        prompt = build_prompt(
            resume_text=resume_text,
            job_title=
                normalized_job_title,
            seniority=
                normalized_seniority,
            description=
                normalized_description,
        )

        logger.info(
            "interview questions prompt built",
            extra={
                "event":
                    "interview_questions_prompt_built",
                "promptLength":
                    len(prompt),
                "model":
                    OPENAI_MODEL,
            },
        )

        openai_started_at = (
            time.perf_counter()
        )

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=OPENAI_MODEL,
            messages=[
                {
                    "role":
                        "system",
                    "content": (
                        "Você é um recrutador "
                        "técnico experiente. "
                        "Retorne somente "
                        "perguntas técnicas."
                    ),
                },
                {
                    "role":
                        "user",
                    "content":
                        prompt,
                },
            ],
            temperature=0.7,
        )

        openai_duration_ms = round(
            (
                time.perf_counter()
                - openai_started_at
            )
            * 1000,
            2,
        )

        logger.info(
            "openai interview questions response received",
            extra={
                "event":
                    "openai_interview_questions_completed",
                "model":
                    OPENAI_MODEL,
                "durationMs":
                    openai_duration_ms,
                "choicesCount":
                    len(
                        response.choices
                    ),
            },
        )

        if not response.choices:
            raise HTTPException(
                status_code=502,
                detail=(
                    "A inteligência artificial "
                    "não retornou uma resposta."
                ),
            )

        response_content = (
            response
            .choices[0]
            .message
            .content
        )

        if not response_content:
            raise HTTPException(
                status_code=502,
                detail=(
                    "A inteligência artificial "
                    "retornou uma resposta vazia."
                ),
            )

        question_list = (
            parse_questions(
                response_content
            )
        )

        if not question_list:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Nenhuma pergunta válida "
                    "foi gerada."
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
            "interview questions generated successfully",
            extra={
                "event":
                    "interview_questions_generated",
                "questionCount":
                    len(
                        question_list
                    ),
                "jobTitle":
                    normalized_job_title,
                "seniority":
                    normalized_seniority,
                "durationMs":
                    duration_ms,
            },
        )

        return {
            "questions":
                question_list
        }

    except HTTPException as error:
        logger.info(
            "interview question generation rejected",
            extra={
                "event":
                    "interview_questions_generation_rejected",
                "statusCode":
                    error.status_code,
                "jobTitle":
                    normalized_job_title,
                "seniority":
                    normalized_seniority,
            },
        )

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
            "failed to generate interview questions",
            extra={
                "event":
                    "interview_questions_generation_failed",
                "jobTitle":
                    normalized_job_title,
                "seniority":
                    normalized_seniority,
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao gerar perguntas: "
                f"{str(error)}"
            ),
        ) from error


# MARK: - Parse Questions


def parse_questions(
    content: str
) -> list[str]:
    questions: list[str] = []

    for line in content.splitlines():
        normalized_line = (
            line.strip()
        )

        if not normalized_line:
            continue

        # Remove formatos:
        #
        # 1. Pergunta
        # 1) Pergunta
        # - Pergunta
        # * Pergunta
        # • Pergunta

        normalized_line = re.sub(
            r"^(?:\d+[\.\)]|[-*•])\s*",
            "",
            normalized_line,
        ).strip()

        if normalized_line:
            questions.append(
                normalized_line
            )

    parsed_questions = (
        questions[:7]
    )

    logger.info(
        "openai questions parsed",
        extra={
            "event":
                "interview_questions_parsed",
            "questionCount":
                len(
                    parsed_questions
                ),
        },
    )

    return parsed_questions


# MARK: - Build Prompt


def build_prompt(
    resume_text: str,
    job_title: str,
    seniority: str,
    description: str = "",
) -> str:
    context_parts = [
        f"Cargo: {job_title}",
        f"Senioridade: {seniority}",
    ]

    if description:
        context_parts.append(
            f"""
Descrição da vaga:
{description}
""".strip()
        )

    if resume_text:
        context_parts.append(
            f"""
Currículo da pessoa candidata:
{resume_text}
""".strip()
        )

    context = "\n\n".join(
        context_parts
    )

    return f"""
Com base nas informações abaixo, gere exatamente 5 perguntas técnicas para uma entrevista.

{context}

Regras:
- As perguntas devem ser adequadas ao cargo e à senioridade.
- Use a descrição da vaga quando ela estiver disponível.
- Use o currículo quando ele estiver disponível.
- Não inclua introduções, títulos ou explicações.
- Retorne somente as perguntas, uma por linha.
""".strip()


# MARK: - Resume Feedback


@router.post(
    "/resume-feedback/"
)
async def resume_feedback(
    resume: UploadFile = File(...),
    _credit_gate=Depends(
        ai_credit_gate("resume_feedback")
    ),
):
    started_at = time.perf_counter()

    logger.info(
        "resume feedback generation started",
        extra={
            "event":
                "resume_feedback_started",
            "fileName":
                resume.filename,
            "contentType":
                resume.content_type,
        },
    )

    try:
        if (
            resume.content_type
            and resume.content_type
            != "application/pdf"
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "O currículo deve "
                    "ser enviado em "
                    "formato PDF."
                ),
            )

        content = await read_upload_with_limit(
            resume,
            MAX_PDF_SIZE_BYTES,
            detail=(
                "O currículo excede o "
                "tamanho máximo permitido."
            ),
        )

        if not content or not looks_like_pdf(content):
            raise HTTPException(
                status_code=422,
                detail=(
                    "O currículo deve "
                    "ser enviado em "
                    "formato PDF."
                ),
            )

        resume_text = (
            extract_text_from_pdf(
                content
            )
        )

        logger.info(
            "resume extracted for feedback",
            extra={
                "event":
                    "resume_feedback_text_extracted",
                "resumeTextLength":
                    len(
                        resume_text
                    ),
            },
        )

        prompt = (
            "Você é um recrutador profissional "
            "experiente. Analise o currículo abaixo "
            "e forneça sugestões de melhorias "
            "em relação a clareza, uso de palavras-chave "
            "relevantes, formatação, impacto e boas práticas "
            "para destacar o candidato:\n\n"
            f"{resume_text}\n\n"
            "Escreva um parecer estruturado com feedback "
            "construtivo e sugestões específicas de melhoria. "
            "Não escreva em markdown, entre asteriscos, "
            "apenas numere e titule cada sessão de melhoria "
            "sem nenhuma formatação. "
            "Exemplo certo: 1. Resumo Pessoal:"
        )

        logger.info(
            "resume feedback prompt built",
            extra={
                "event":
                    "resume_feedback_prompt_built",
                "promptLength":
                    len(prompt),
                "model":
                    OPENAI_MODEL,
            },
        )

        openai_started_at = (
            time.perf_counter()
        )

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=OPENAI_MODEL,
            messages=[
                {
                    "role":
                        "system",
                    "content": (
                        "Você é um recrutador "
                        "profissional experiente."
                    ),
                },
                {
                    "role":
                        "user",
                    "content":
                        prompt,
                },
            ],
            temperature=0.7,
        )

        openai_duration_ms = round(
            (
                time.perf_counter()
                - openai_started_at
            )
            * 1000,
            2,
        )

        logger.info(
            "openai resume feedback response received",
            extra={
                "event":
                    "openai_resume_feedback_completed",
                "model":
                    OPENAI_MODEL,
                "durationMs":
                    openai_duration_ms,
                "choicesCount":
                    len(
                        response.choices
                    ),
            },
        )

        if not response.choices:
            raise HTTPException(
                status_code=502,
                detail=(
                    "A inteligência artificial "
                    "não retornou feedback."
                ),
            )

        feedback_content = (
            response
            .choices[0]
            .message
            .content
        )

        if not feedback_content:
            raise HTTPException(
                status_code=502,
                detail=(
                    "A inteligência artificial "
                    "retornou um feedback vazio."
                ),
            )

        feedback = (
            feedback_content.strip()
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
            "resume feedback generated successfully",
            extra={
                "event":
                    "resume_feedback_generated",
                "feedbackLength":
                    len(
                        feedback
                    ),
                "durationMs":
                    duration_ms,
            },
        )

        return {
            "feedback":
                feedback
        }

    except HTTPException as error:
        logger.info(
            "resume feedback request rejected",
            extra={
                "event":
                    "resume_feedback_rejected",
                "statusCode":
                    error.status_code,
            },
        )

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
            "failed to generate resume feedback",
            extra={
                "event":
                    "resume_feedback_failed",
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao gerar "
                "feedback de currículo"
            ),
        ) from error

    finally:
        await resume.close()


# MARK: - Submit Async Feedback


@router.post(
    "/submit-feedback/"
)
async def submit_resume(
    resume: UploadFile = File(...),
    credit_gate=Depends(
        ai_credit_gate("resume_feedback_submit")
    ),
):
    started_at = time.perf_counter()

    logger.info(
        "resume submitted for asynchronous feedback",
        extra={
            "event":
                "resume_feedback_task_submission_started",
            "fileName":
                resume.filename,
            "contentType":
                resume.content_type,
        },
    )

    try:
        if (
            resume.content_type
            and resume.content_type
            != "application/pdf"
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "O currículo deve "
                    "ser enviado em "
                    "formato PDF."
                ),
            )

        content = await read_upload_with_limit(
            resume,
            MAX_PDF_SIZE_BYTES,
            detail=(
                "O currículo excede o "
                "tamanho máximo permitido."
            ),
        )

        if not content or not looks_like_pdf(content):
            raise HTTPException(
                status_code=422,
                detail=(
                    "O currículo deve "
                    "ser enviado em "
                    "formato PDF."
                ),
            )

        task = (
            process_resume_feedback
            .delay(
                content,
                user_id=str(
                    credit_gate.current_user.id
                ),
                credit_cost=(
                    credit_gate.cost
                    if credit_gate.credit_consumed
                    else 0
                ),
            )
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
            "resume feedback task sent to celery",
            extra={
                "event":
                    "resume_feedback_task_submitted",
                "taskId":
                    task.id,
                "fileSizeBytes":
                    len(content),
                "durationMs":
                    duration_ms,
            },
        )

        return {
            "task_id":
                task.id
        }

    except HTTPException as error:
        logger.info(
            "resume feedback task submission rejected",
            extra={
                "event":
                    "resume_feedback_task_submission_rejected",
                "statusCode":
                    error.status_code,
            },
        )

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
            "failed to submit resume feedback task",
            extra={
                "event":
                    "resume_feedback_task_submission_failed",
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao processar currículo"
            ),
        ) from error

    finally:
        await resume.close()


# MARK: - Feedback Status


@router.get(
    "/feedback-status/{task_id}"
)
def get_status(
    task_id: str
):
    try:
        result = (
            celery_app.AsyncResult(
                task_id
            )
        )

        logger.info(
            "resume feedback task status requested",
            extra={
                "event":
                    "resume_feedback_status_requested",
                "taskId":
                    task_id,
                "taskStatus":
                    result.status,
            },
        )

        return {
            "status":
                result.status
        }

    except Exception as error:
        logger.exception(
            "failed to retrieve resume feedback task status",
            extra={
                "event":
                    "resume_feedback_status_failed",
                "taskId":
                    task_id,
            },
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao consultar "
                "o status do feedback."
            ),
        ) from error


# MARK: - Feedback Result


@router.get(
    "/feedback-result/{task_id}"
)
def get_result(
    task_id: str
):
    try:
        result = (
            celery_app.AsyncResult(
                task_id
            )
        )

        logger.info(
            "resume feedback result requested",
            extra={
                "event":
                    "resume_feedback_result_requested",
                "taskId":
                    task_id,
                "taskStatus":
                    result.status,
                "isReady":
                    result.ready(),
            },
        )

        if not result.ready():
            logger.info(
                "resume feedback task still processing",
                extra={
                    "event":
                        "resume_feedback_still_processing",
                    "taskId":
                        task_id,
                    "taskStatus":
                        result.status,
                },
            )

            raise HTTPException(
                status_code=202,
                detail=(
                    "Ainda processando..."
                ),
            )

        feedback = result.get()

        logger.info(
            "resume feedback result retrieved",
            extra={
                "event":
                    "resume_feedback_result_retrieved",
                "taskId":
                    task_id,
                "taskStatus":
                    result.status,
            },
        )

        return {
            "feedback":
                feedback
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.exception(
            "failed to retrieve resume feedback result",
            extra={
                "event":
                    "resume_feedback_result_failed",
                "taskId":
                    task_id,
            },
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao buscar "
                "o resultado do feedback."
            ),
        ) from error