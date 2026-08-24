# app/interview_simulation/router.py

import asyncio
import json
import os
import re
import tempfile
import time

from dotenv import load_dotenv

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)

from openai import OpenAI

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.observability import logger

from app.interview_simulation.models import (
    InterviewQuestionSet,
    SavedInterviewQuestion,
)

from app.interview_simulation.schemas import (
    SaveGeneratedQuestionsRequest,
    SaveGeneratedQuestionsResponse,
    SimulationEvaluationRequest,
    SimulationEvaluationResponse,
    SimulationQuestionsRequest,
)

from app.credits.service import ai_credit_gate

from app.uploads.validation import (
    MAX_AUDIO_SIZE_BYTES,
    is_allowed_audio_content,
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


# MARK: - Generate Simulation Questions


@router.post(
    "/interview-simulation/questions"
)
async def generate_simulation_questions(
    request: SimulationQuestionsRequest,
    _credit_gate=Depends(
        ai_credit_gate("simulation_questions")
    ),
):
    started_at = time.perf_counter()

    job_title = (
        request.job_title.strip()
    )

    seniority = (
        request.seniority.strip()
    )

    description = (
        request.description or ""
    ).strip()

    logger.info(
        "interview simulation question generation started",
        extra={
            "event":
                "simulation_questions_generation_started",
            "jobTitle":
                job_title,
            "seniority":
                seniority,
            "hasDescription":
                bool(description),
        },
    )

    try:
        if not job_title:
            raise HTTPException(
                status_code=422,
                detail=(
                    "O cargo é obrigatório."
                ),
            )

        if not seniority:
            raise HTTPException(
                status_code=422,
                detail=(
                    "A senioridade é obrigatória."
                ),
            )

        prompt = """
Crie exatamente 5 perguntas para uma entrevista técnica.

Cargo: {job_title}
Senioridade: {seniority}
Descrição da vaga: {description}

Regras:
- Faça uma pergunta por linha.
- Não inclua introdução.
- Não inclua respostas.
- Adapte a dificuldade à senioridade.
- Misture conceitos técnicos, experiência prática e arquitetura.
""".format(
            job_title=job_title,
            seniority=seniority,
            description=(
                description
                or "Não informada"
            ),
        )

        logger.info(
            "simulation questions prompt built",
            extra={
                "event":
                    "simulation_questions_prompt_built",
                "jobTitle":
                    job_title,
                "seniority":
                    seniority,
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
                        "Você é um entrevistador "
                        "técnico experiente."
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
            "openai simulation questions response received",
            extra={
                "event":
                    "simulation_questions_openai_completed",
                "jobTitle":
                    job_title,
                "seniority":
                    seniority,
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

        content = (
            response
            .choices[0]
            .message
            .content
            or ""
        )

        questions = (
            parse_questions(
                content
            )
        )

        if not questions:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Nenhuma pergunta "
                    "foi gerada."
                ),
            )

        selected_questions = (
            questions[:5]
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
            "simulation questions generated successfully",
            extra={
                "event":
                    "simulation_questions_generated",
                "jobTitle":
                    job_title,
                "seniority":
                    seniority,
                "questionCount":
                    len(
                        selected_questions
                    ),
                "durationMs":
                    duration_ms,
            },
        )

        return {
            "questions":
                selected_questions
        }

    except HTTPException as error:
        logger.info(
            "simulation question generation rejected",
            extra={
                "event":
                    "simulation_questions_generation_rejected",
                "jobTitle":
                    job_title,
                "seniority":
                    seniority,
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
            "failed to generate simulation questions",
            extra={
                "event":
                    "simulation_questions_generation_failed",
                "jobTitle":
                    job_title,
                "seniority":
                    seniority,
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao gerar perguntas "
                "para a simulação."
            ),
        ) from error


# MARK: - Parse Questions


def parse_questions(
    content: str
) -> list[str]:
    questions: list[str] = []

    for line in content.splitlines():
        normalized = (
            line.strip()
        )

        if not normalized:
            continue

        normalized = re.sub(
            r"^(?:\d+[\.\)]|[-*•])\s*",
            "",
            normalized,
        ).strip()

        if normalized:
            questions.append(
                normalized
            )

    logger.info(
        "simulation questions parsed",
        extra={
            "event":
                "simulation_questions_parsed",
            "questionCount":
                len(questions),
        },
    )

    return questions


# MARK: - Transcribe Interview Audio


@router.post(
    "/interview-simulation/transcribe"
)
async def transcribe_interview_audio(
    audio: UploadFile = File(...),
    _credit_gate=Depends(
        ai_credit_gate("simulation_transcribe")
    ),
):
    started_at = time.perf_counter()

    temporary_path = None

    logger.info(
        "interview audio transcription started",
        extra={
            "event":
                "interview_audio_transcription_started",
            "fileName":
                audio.filename,
            "contentType":
                audio.content_type,
        },
    )

    try:
        content = await read_upload_with_limit(
            audio,
            MAX_AUDIO_SIZE_BYTES,
            detail=(
                "O áudio excede o tamanho "
                "máximo permitido."
            ),
        )

        logger.info(
            "interview audio received",
            extra={
                "event":
                    "interview_audio_received",
                "fileName":
                    audio.filename,
                "contentType":
                    audio.content_type,
                "fileSizeBytes":
                    len(content),
            },
        )

        if not content:
            raise HTTPException(
                status_code=422,
                detail=(
                    "O áudio recebido "
                    "está vazio."
                ),
            )

        allowed_content_types = {
            "audio/mp4",
            "audio/m4a",
            "audio/x-m4a",
            "application/octet-stream",
        }

        if (
            audio.content_type
            and audio.content_type
            not in allowed_content_types
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Formato de áudio "
                    "não suportado: "
                    + audio.content_type
                ),
            )

        # O Content-Type é só um chute do cliente (o app iOS, por
        # exemplo, às vezes manda "application/octet-stream"). Os
        # primeiros bytes do arquivo são a única fonte confiável do
        # formato real.
        if not is_allowed_audio_content(content):
            raise HTTPException(
                status_code=422,
                detail=(
                    "O conteúdo do áudio não "
                    "corresponde a um formato suportado."
                ),
            )

        # Extensão sempre fixa e gerada pelo servidor — nunca
        # derivada do filename do cliente. `os.path.splitext` opera
        # sobre a string crua (não trata "/" como separador de
        # diretório do jeito que pathlib faz), então um filename tipo
        # "a.mp4/../../etc/cron.d/x" podia produzir um suffix com "/"
        # dentro dele e escapar do diretório temporário.
        suffix = ".m4a"

        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            suffix=suffix,
        ) as temporary_file:
            temporary_file.write(
                content
            )

            temporary_file.flush()

            temporary_path = (
                temporary_file.name
            )

        logger.info(
            "temporary audio file created",
            extra={
                "event":
                    "interview_audio_temporary_file_created",
                "fileSizeBytes":
                    len(content),
                "fileExtension":
                    suffix,
            },
        )

        def transcribe():
            with open(
                temporary_path,
                "rb"
            ) as file:
                return (
                    client
                    .audio
                    .transcriptions
                    .create(
                        model="whisper-1",
                        file=file,
                        language="pt",
                    )
                )

        logger.info(
            "audio sent to openai transcription",
            extra={
                "event":
                    "interview_audio_openai_started",
                "model":
                    "whisper-1",
                "fileSizeBytes":
                    len(content),
            },
        )

        openai_started_at = (
            time.perf_counter()
        )

        transcription = (
            await asyncio.to_thread(
                transcribe
            )
        )

        openai_duration_ms = round(
            (
                time.perf_counter()
                - openai_started_at
            )
            * 1000,
            2,
        )

        transcript = (
            transcription.text
            or ""
        ).strip()

        logger.info(
            "openai audio transcription completed",
            extra={
                "event":
                    "interview_audio_openai_completed",
                "model":
                    "whisper-1",
                "durationMs":
                    openai_duration_ms,
                "transcriptLength":
                    len(transcript),
            },
        )

        if not transcript:
            raise HTTPException(
                status_code=502,
                detail=(
                    "A API processou o áudio, "
                    "mas não retornou nenhum texto."
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
            "interview audio transcribed successfully",
            extra={
                "event":
                    "interview_audio_transcribed",
                "transcriptLength":
                    len(transcript),
                "durationMs":
                    duration_ms,
            },
        )

        return {
            "transcript":
                transcript
        }

    except HTTPException as error:
        logger.info(
            "interview audio transcription rejected",
            extra={
                "event":
                    "interview_audio_transcription_rejected",
                "statusCode":
                    error.status_code,
                "fileName":
                    audio.filename,
                "contentType":
                    audio.content_type,
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
            "failed to transcribe interview audio",
            extra={
                "event":
                    "interview_audio_transcription_failed",
                "fileName":
                    audio.filename,
                "contentType":
                    audio.content_type,
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao transcrever "
                "o áudio."
            ),
        ) from error

    finally:
        await audio.close()

        if (
            temporary_path
            and os.path.exists(
                temporary_path
            )
        ):
            try:
                os.remove(
                    temporary_path
                )

                logger.info(
                    "temporary audio file removed",
                    extra={
                        "event":
                            "interview_audio_temporary_file_removed",
                    },
                )

            except OSError:
                logger.exception(
                    "failed to remove temporary audio file",
                    extra={
                        "event":
                            "interview_audio_temporary_file_removal_failed",
                    },
                )


# MARK: - Evaluate Interview Simulation


@router.post(
    "/interview-simulation/evaluate",
    response_model=
        SimulationEvaluationResponse,
)
async def evaluate_interview_simulation(
    request: SimulationEvaluationRequest,
    _credit_gate=Depends(
        ai_credit_gate("simulation_evaluate")
    ),
):
    started_at = time.perf_counter()

    logger.info(
        "interview simulation evaluation started",
        extra={
            "event":
                "simulation_evaluation_started",
            "jobTitle":
                request.job_title,
            "seniority":
                request.seniority,
            "answerCount":
                len(
                    request.answers
                ),
        },
    )

    try:
        if not request.answers:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Nenhuma resposta "
                    "foi enviada."
                ),
            )

        formatted_answers = []

        for index, answer in enumerate(
            request.answers,
            start=1,
        ):
            formatted_answers.append(
                """
Pergunta {index}: {question}
Resposta: {answer}
Tempo: {time} segundos
""".format(
                    index=index,
                    question=
                        answer.question,
                    answer=
                        answer.answer,
                    time=
                        answer
                        .response_time_seconds,
                )
            )

        answers_text = "\n".join(
            formatted_answers
        )

        prompt = """
Avalie esta entrevista simulada.

Cargo: {job_title}
Senioridade: {seniority}

Respostas:
{answers}

Avalie de 0 a 100:

- clarity: clareza das respostas
- objectivity: objetividade
- examples: uso de exemplos reais
- technical_knowledge: conhecimento técnico
- response_time: adequação do tempo de resposta
- overall: média geral

Retorne somente JSON neste formato:

{{
    "clarity": 0,
    "objectivity": 0,
    "examples": 0,
    "technical_knowledge": 0,
    "response_time": 0,
    "overall": 0,
    "summary": "Resumo da avaliação",
    "strengths": [
        "Ponto forte"
    ],
    "improvements": [
        "Ponto a melhorar"
    ]
}}
""".format(
            job_title=
                request.job_title,
            seniority=
                request.seniority,
            answers=
                answers_text,
        )

        logger.info(
            "simulation evaluation prompt built",
            extra={
                "event":
                    "simulation_evaluation_prompt_built",
                "jobTitle":
                    request.job_title,
                "seniority":
                    request.seniority,
                "answerCount":
                    len(
                        request.answers
                    ),
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
                        "Você é um avaliador "
                        "de entrevistas técnicas. "
                        "Responda somente com JSON."
                    ),
                },
                {
                    "role":
                        "user",
                    "content":
                        prompt,
                },
            ],
            temperature=0.3,
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
            "openai simulation evaluation completed",
            extra={
                "event":
                    "simulation_evaluation_openai_completed",
                "jobTitle":
                    request.job_title,
                "seniority":
                    request.seniority,
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
                    "não retornou uma avaliação."
                ),
            )

        content = (
            response
            .choices[0]
            .message
            .content
            or ""
        )

        if not content.strip():
            raise HTTPException(
                status_code=502,
                detail=(
                    "A inteligência artificial "
                    "retornou uma avaliação vazia."
                ),
            )

        evaluation = (
            extract_json(
                content
            )
        )

        normalized_evaluation = (
            normalize_evaluation(
                evaluation
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
            "interview simulation evaluated successfully",
            extra={
                "event":
                    "simulation_evaluation_completed",
                "jobTitle":
                    request.job_title,
                "seniority":
                    request.seniority,
                "answerCount":
                    len(
                        request.answers
                    ),
                "overallScore":
                    normalized_evaluation
                    .get(
                        "overall"
                    ),
                "strengthCount":
                    len(
                        normalized_evaluation
                        .get(
                            "strengths",
                            [],
                        )
                    ),
                "improvementCount":
                    len(
                        normalized_evaluation
                        .get(
                            "improvements",
                            [],
                        )
                    ),
                "durationMs":
                    duration_ms,
            },
        )

        return (
            normalized_evaluation
        )

    except HTTPException as error:
        logger.info(
            "simulation evaluation rejected",
            extra={
                "event":
                    "simulation_evaluation_rejected",
                "jobTitle":
                    request.job_title,
                "seniority":
                    request.seniority,
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
            "failed to evaluate interview simulation",
            extra={
                "event":
                    "simulation_evaluation_failed",
                "jobTitle":
                    request.job_title,
                "seniority":
                    request.seniority,
                "answerCount":
                    len(
                        request.answers
                    ),
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao avaliar "
                "a entrevista simulada."
            ),
        ) from error


# MARK: - Extract JSON


def extract_json(
    content: str
) -> dict:
    normalized = (
        content.strip()
    )

    normalized = (
        normalized.replace(
            "```json",
            "",
        )
    )

    normalized = (
        normalized.replace(
            "```",
            "",
        )
    )

    start_index = (
        normalized.find("{")
    )

    end_index = (
        normalized.rfind("}")
    )

    if (
        start_index == -1
        or end_index == -1
    ):
        logger.info(
            "openai evaluation response does not contain json",
            extra={
                "event":
                    "simulation_evaluation_json_missing",
                "responseLength":
                    len(content),
            },
        )

        raise ValueError(
            "A OpenAI não retornou "
            "um JSON válido."
        )

    json_content = normalized[
        start_index:
        end_index + 1
    ]

    try:
        parsed_json = json.loads(
            json_content
        )

        logger.info(
            "simulation evaluation json parsed",
            extra={
                "event":
                    "simulation_evaluation_json_parsed",
                "responseLength":
                    len(content),
            },
        )

        return parsed_json

    except json.JSONDecodeError:
        logger.exception(
            "failed to parse simulation evaluation json",
            extra={
                "event":
                    "simulation_evaluation_json_parse_failed",
                "responseLength":
                    len(content),
            },
        )

        raise


# MARK: - Normalize Evaluation


def normalize_evaluation(
    evaluation: dict,
) -> dict:
    score_fields = [
        "clarity",
        "objectivity",
        "examples",
        "technical_knowledge",
        "response_time",
        "overall",
    ]

    for field in score_fields:
        score = int(
            evaluation.get(
                field,
                0,
            )
        )

        evaluation[field] = max(
            0,
            min(
                score,
                100,
            ),
        )

    evaluation[
        "summary"
    ] = evaluation.get(
        "summary",
        "Avaliação concluída.",
    )

    evaluation[
        "strengths"
    ] = evaluation.get(
        "strengths",
        [],
    )

    evaluation[
        "improvements"
    ] = evaluation.get(
        "improvements",
        [],
    )

    logger.info(
        "simulation evaluation normalized",
        extra={
            "event":
                "simulation_evaluation_normalized",
            "clarityScore":
                evaluation[
                    "clarity"
                ],
            "objectivityScore":
                evaluation[
                    "objectivity"
                ],
            "examplesScore":
                evaluation[
                    "examples"
                ],
            "technicalKnowledgeScore":
                evaluation[
                    "technical_knowledge"
                ],
            "responseTimeScore":
                evaluation[
                    "response_time"
                ],
            "overallScore":
                evaluation[
                    "overall"
                ],
        },
    )

    return evaluation


# MARK: - Save Generated Questions


@router.post(
    "/interview-simulation/saved-questions",
    response_model=
        SaveGeneratedQuestionsResponse,
    status_code=
        status.HTTP_201_CREATED,
)
def save_generated_questions(
    request:
        SaveGeneratedQuestionsRequest,
    db: Session = Depends(
        get_db
    ),
):
    started_at = time.perf_counter()

    job_title = (
        request.job_title.strip()
    )

    seniority = (
        request.seniority.strip()
    )

    logger.info(
        "saving generated interview questions started",
        extra={
            "event":
                "saved_questions_creation_started",
            "jobTitle":
                job_title,
            "seniority":
                seniority,
            "receivedQuestionCount":
                len(
                    request.questions
                ),
        },
    )

    try:
        if not job_title:
            raise HTTPException(
                status_code=422,
                detail=(
                    "O cargo é obrigatório."
                ),
            )

        if not seniority:
            raise HTTPException(
                status_code=422,
                detail=(
                    "A senioridade "
                    "é obrigatória."
                ),
            )

        normalized_questions = []

        for question in request.questions:
            normalized_question = (
                question.strip()
            )

            if (
                normalized_question
                and normalized_question
                not in normalized_questions
            ):
                normalized_questions.append(
                    normalized_question
                )

        logger.info(
            "generated interview questions normalized",
            extra={
                "event":
                    "saved_questions_normalized",
                "jobTitle":
                    job_title,
                "seniority":
                    seniority,
                "receivedQuestionCount":
                    len(
                        request.questions
                    ),
                "normalizedQuestionCount":
                    len(
                        normalized_questions
                    ),
            },
        )

        if not normalized_questions:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Nenhuma pergunta válida "
                    "foi enviada."
                ),
            )

        question_set = (
            InterviewQuestionSet(
                job_title=
                    job_title,
                seniority=
                    seniority,
            )
        )

        db.add(
            question_set
        )

        db.flush()

        logger.info(
            "interview question set created",
            extra={
                "event":
                    "question_set_created",
                "questionSetId":
                    str(
                        question_set.id
                    ),
                "jobTitle":
                    job_title,
                "seniority":
                    seniority,
            },
        )

        for index, question in enumerate(
            normalized_questions,
            start=1,
        ):
            db.add(
                SavedInterviewQuestion(
                    question_set_id=
                        question_set.id,
                    text=
                        question,
                    position=
                        index,
                )
            )

        db.commit()

        db.refresh(
            question_set
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
            "generated interview questions saved successfully",
            extra={
                "event":
                    "saved_questions_created",
                "questionSetId":
                    str(
                        question_set.id
                    ),
                "jobTitle":
                    job_title,
                "seniority":
                    seniority,
                "savedQuestionCount":
                    len(
                        normalized_questions
                    ),
                "durationMs":
                    duration_ms,
            },
        )

        return (
            SaveGeneratedQuestionsResponse(
                id=
                    question_set.id,
                saved_count=
                    len(
                        normalized_questions
                    ),
                message=
                    "Perguntas salvas com sucesso.",
            )
        )

    except HTTPException as error:
        db.rollback()

        logger.info(
            "saving generated questions rejected",
            extra={
                "event":
                    "saved_questions_creation_rejected",
                "jobTitle":
                    job_title,
                "seniority":
                    seniority,
                "statusCode":
                    error.status_code,
            },
        )

        raise

    except SQLAlchemyError as error:
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
            "database error while saving generated questions",
            extra={
                "event":
                    "saved_questions_database_failed",
                "jobTitle":
                    job_title,
                "seniority":
                    seniority,
                "receivedQuestionCount":
                    len(
                        request.questions
                    ),
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Não foi possível salvar "
                "as perguntas no banco "
                "de dados."
            ),
        ) from error

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
            "failed to save generated interview questions",
            extra={
                "event":
                    "saved_questions_creation_failed",
                "jobTitle":
                    job_title,
                "seniority":
                    seniority,
                "receivedQuestionCount":
                    len(
                        request.questions
                    ),
                "durationMs":
                    duration_ms,
            },
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao salvar perguntas."
            ),
        ) from error