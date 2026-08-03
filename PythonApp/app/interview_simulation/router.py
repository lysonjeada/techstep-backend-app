# llm_generation/router.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from openai import OpenAI # Importa OpenAI aqui
import traceback
import os
import asyncio
import re
import tempfile
from dotenv import load_dotenv
from typing import List, Optional
import json

from app.llm_generation.services import extract_text_from_pdf, build_prompt
from ..worker.tasks import process_resume_feedback # Importa a tarefa Celery do nível acima
from ..worker.celery_app import celery_app # Importa a instância do Celery
from typing import Optional

import traceback

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db

from app.interview_simulation.models import (
    InterviewQuestionSet,
    SavedInterviewQuestion,
)

from app.interview_simulation.schemas import (
    SaveGeneratedQuestionsRequest,
    SaveGeneratedQuestionsResponse,
)

from .schemas import (
    SimulationEvaluationRequest,
    SimulationEvaluationResponse,
    SimulationQuestionsRequest
)

load_dotenv() # Carrega variáveis de ambiente para este arquivo também

router = APIRouter(
    tags=["LLM Generation"]
)


# Inicializa o cliente OpenAI aqui (ou passe como dependência se preferir)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

OPENAI_MODEL = os.getenv(
    "OPENAI_INTERVIEW_MODEL",
    "gpt-4"
)


@router.post("/interview-simulation/questions")
async def generate_simulation_questions(
    request: SimulationQuestionsRequest,
):
    try:
        job_title = request.job_title.strip()
        seniority = request.seniority.strip()
        description = (request.description or "").strip()

        if not job_title:
            raise HTTPException(
                status_code=422,
                detail="O cargo é obrigatório.",
            )

        if not seniority:
            raise HTTPException(
                status_code=422,
                detail="A senioridade é obrigatória.",
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
            description=description or "Não informada",
        )

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é um entrevistador técnico "
                        "experiente."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.7,
        )

        content = response.choices[0].message.content or ""

        questions = parse_questions(content)

        if not questions:
            raise HTTPException(
                status_code=502,
                detail="Nenhuma pergunta foi gerada.",
            )

        return {
            "questions": questions[:5]
        }

    except HTTPException:
        raise

    except Exception as error:
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=str(error),
        )

def parse_questions(content: str) -> List[str]:
    questions = []

    for line in content.splitlines():
        normalized = line.strip()

        if not normalized:
            continue

        normalized = re.sub(
            r"^(?:\d+[\.\)]|[-*•])\s*",
            "",
            normalized,
        ).strip()

        if normalized:
            questions.append(normalized)

    return questions

@router.post("/interview-simulation/transcribe")
async def transcribe_interview_audio(
    audio: UploadFile = File(...),
):
    temporary_path = None

    try:
        print(
            "🎙️ Áudio recebido:",
            audio.filename,
            audio.content_type,
            flush=True,
        )

        content = await audio.read()

        print(
            "📦 Tamanho do áudio:",
            len(content),
            "bytes",
            flush=True,
        )

        if not content:
            raise HTTPException(
                status_code=422,
                detail="O áudio recebido está vazio.",
            )

        allowed_content_types = {
            "audio/mp4",
            "audio/m4a",
            "audio/x-m4a",
            "application/octet-stream",
        }

        if (
            audio.content_type
            and audio.content_type not in allowed_content_types
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Formato de áudio não suportado: "
                    + audio.content_type
                ),
            )

        suffix = os.path.splitext(
            audio.filename or "answer.m4a"
        )[1]

        if not suffix:
            suffix = ".m4a"

        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            suffix=suffix,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()

            temporary_path = temporary_file.name

        print(
            "📁 Arquivo temporário:",
            temporary_path,
            flush=True,
        )

        def transcribe():
            with open(temporary_path, "rb") as file:
                return client.audio.transcriptions.create(
                    model="whisper-1",
                    file=file,
                    language="pt",
                )

        print(
            "🤖 Enviando áudio para transcrição...",
            flush=True,
        )

        transcription = await asyncio.to_thread(
            transcribe
        )

        print(
            "✅ Transcrição recebida:",
            transcription,
            flush=True,
        )

        transcript = (
            transcription.text or ""
        ).strip()

        if not transcript:
            raise HTTPException(
                status_code=502,
                detail=(
                    "A API processou o áudio, mas não "
                    "retornou nenhum texto."
                ),
            )

        return {
            "transcript": transcript
        }

    except HTTPException:
        raise

    except Exception as error:
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao transcrever o áudio: "
                + str(error)
            ),
        )

    finally:
        await audio.close()

        if (
            temporary_path
            and os.path.exists(temporary_path)
        ):
            try:
                os.remove(temporary_path)

                print(
                    "🗑️ Arquivo temporário removido",
                    flush=True,
                )

            except OSError as error:
                print(
                    "⚠️ Não foi possível remover o arquivo:",
                    error,
                    flush=True,
                )

@router.post(
    "/interview-simulation/evaluate",
    response_model=SimulationEvaluationResponse,
)
async def evaluate_interview_simulation(
    request: SimulationEvaluationRequest,
):
    try:
        if not request.answers:
            raise HTTPException(
                status_code=422,
                detail="Nenhuma resposta foi enviada.",
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
                    question=answer.question,
                    answer=answer.answer,
                    time=answer.response_time_seconds,
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
            job_title=request.job_title,
            seniority=request.seniority,
            answers=answers_text,
        )

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é um avaliador de entrevistas "
                        "técnicas. Responda somente com JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.3,
        )

        content = response.choices[0].message.content or ""

        evaluation = extract_json(content)

        return normalize_evaluation(
            evaluation
        )

    except HTTPException:
        raise

    except Exception as error:
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=str(error),
        )

def extract_json(content: str) -> dict:
    normalized = content.strip()

    normalized = normalized.replace(
        "```json",
        "",
    )

    normalized = normalized.replace(
        "```",
        "",
    )

    start_index = normalized.find("{")
    end_index = normalized.rfind("}")

    if start_index == -1 or end_index == -1:
        raise ValueError(
            "A OpenAI não retornou um JSON válido."
        )

    json_content = normalized[
        start_index:end_index + 1
    ]

    return json.loads(json_content)

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
        score = int(evaluation.get(field, 0))

        evaluation[field] = max(
            0,
            min(score, 100),
        )

    evaluation["summary"] = evaluation.get(
        "summary",
        "Avaliação concluída.",
    )

    evaluation["strengths"] = evaluation.get(
        "strengths",
        [],
    )

    evaluation["improvements"] = evaluation.get(
        "improvements",
        [],
    )

    return evaluation

@router.post(
    "/interview-simulation/saved-questions",
    response_model=SaveGeneratedQuestionsResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_generated_questions(
    request: SaveGeneratedQuestionsRequest,
    db: Session = Depends(get_db),
):
    try:
        job_title = request.job_title.strip()
        seniority = request.seniority.strip()

        if not job_title:
            raise HTTPException(
                status_code=422,
                detail="O cargo é obrigatório.",
            )

        if not seniority:
            raise HTTPException(
                status_code=422,
                detail="A senioridade é obrigatória.",
            )

        normalized_questions = []

        for question in request.questions:
            normalized_question = question.strip()

            if (
                normalized_question
                and normalized_question
                not in normalized_questions
            ):
                normalized_questions.append(
                    normalized_question
                )

        if not normalized_questions:
            raise HTTPException(
                status_code=422,
                detail="Nenhuma pergunta válida foi enviada.",
            )

        question_set = InterviewQuestionSet(
            job_title=job_title,
            seniority=seniority,
        )

        db.add(question_set)
        db.flush()

        for index, question in enumerate(
            normalized_questions,
            start=1,
        ):
            db.add(
                SavedInterviewQuestion(
                    question_set_id=question_set.id,
                    text=question,
                    position=index,
                )
            )

        db.commit()
        db.refresh(question_set)

        return SaveGeneratedQuestionsResponse(
            id=question_set.id,
            saved_count=len(normalized_questions),
            message="Perguntas salvas com sucesso.",
        )

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError as error:
        db.rollback()
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=(
                "Não foi possível salvar as perguntas "
                "no banco de dados."
            ),
        ) from error

    except Exception as error:
        db.rollback()
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail="Erro ao salvar perguntas: {}".format(
                str(error)
            ),
        ) from error