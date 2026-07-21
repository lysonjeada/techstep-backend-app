# llm_generation/router.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from openai import OpenAI # Importa OpenAI aqui
import traceback
import os
import asyncio
import re
from dotenv import load_dotenv
from typing import List, Optional

from .services import extract_text_from_pdf, build_prompt
from ..worker.tasks import process_resume_feedback # Importa a tarefa Celery do nível acima
from ..worker.celery_app import celery_app # Importa a instância do Celery
from typing import Optional

from .schemas import (
    SimulationEvaluationRequest,
    SimulationEvaluationResponse,
    SimulationQuestionsRequest,
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


@router.post("/generate-interview-questions/")
async def generate_questions(
    job_title: str = Form(...),
    seniority: str = Form(...),
    description: Optional[str] = Form(None),
    resume: Optional[UploadFile] = File(None)
):
    try:
        normalized_job_title = job_title.strip()
        normalized_seniority = seniority.strip()
        normalized_description = (description or "").strip()

        if not normalized_job_title:
            raise HTTPException(
                status_code=422,
                detail="O título da vaga é obrigatório.",
            )

        if not normalized_seniority:
            raise HTTPException(
                status_code=422,
                detail="A senioridade é obrigatória.",
            )

        resume_text = ""

        # O currículo agora é opcional.
        if resume is not None:
            try:
                if (
                    resume.content_type
                    and resume.content_type != "application/pdf"
                ):
                    raise HTTPException(
                        status_code=422,
                        detail="O currículo deve ser enviado em formato PDF.",
                    )

                content = await resume.read()

                if content:
                    resume_text = extract_text_from_pdf(content)

            finally:
                await resume.close()

        prompt = build_prompt(
            resume_text=resume_text,
            job_title=normalized_job_title,
            seniority=normalized_seniority,
            description=normalized_description,
        )

        print("🔍 Prompt gerado:", prompt)

        # O client usado é síncrono, então a chamada é executada
        # fora do event loop do FastAPI.
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é um recrutador técnico experiente. "
                        "Retorne somente perguntas técnicas."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.7,
        )

        print("✅ Resposta OpenAI:", response)

        if not response.choices:
            raise HTTPException(
                status_code=502,
                detail="A inteligência artificial não retornou uma resposta.",
            )

        response_content = response.choices[0].message.content

        if not response_content:
            raise HTTPException(
                status_code=502,
                detail="A inteligência artificial retornou uma resposta vazia.",
            )

        question_list = parse_questions(response_content)

        if not question_list:
            raise HTTPException(
                status_code=502,
                detail="Nenhuma pergunta válida foi gerada.",
            )

        return {
            "questions": question_list
        }

    except HTTPException:
        # Preserva o status original, como 422 ou 502.
        raise

    except Exception as error:
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=f"Erro ao gerar perguntas: {str(error)}",
        ) from error

def parse_questions(content: str) -> list[str]:
    questions: list[str] = []

    for line in content.splitlines():
        normalized_line = line.strip()

        if not normalized_line:
            continue

        # Remove formatos como:
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
            questions.append(normalized_line)

    return questions[:7]

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
            f"Descrição da vaga:\n{description}"
        )

    if resume_text:
        context_parts.append(
            f"Currículo da pessoa candidata:\n{resume_text}"
        )

    context = "\n\n".join(context_parts)

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

@router.post("/resume-feedback/")
async def resume_feedback(resume: UploadFile = File(...)):
    try:
        content = await resume.read()
        resume_text = extract_text_from_pdf(content)

        prompt = (
            "Você é um recrutador profissional experiente. Analise o currículo abaixo e forneça sugestões de melhorias "
            "em relação a clareza, uso de palavras-chave relevantes, formatação, impacto e boas práticas para destacar o candidato:\n\n"
            f"{resume_text}\n\n"
            "Escreva um parecer estruturado com feedback construtivo e sugestões específicas de melhoria."
            "Não escreva em markdown, entre asteríscos, apenas numere e titule cada sessão de melhoria sem nenhuma formatação"
            "Exemplo certo: 1. Resumo Pessoal:"
        )

        print("🔍 Prompt gerado para feedback:", prompt[:300], "...")

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Você é um recrutador profissional experiente."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )

        feedback = response.choices[0].message.content.strip()
        print("✅ Feedback gerado:", feedback[:300], "...")

        return {"feedback": feedback}

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao gerar feedback de currículo")

@router.post("/submit-feedback/")
async def submit_resume(resume: UploadFile = File(...)):
    try:
        content = await resume.read()
        task = process_resume_feedback.delay(content) # Chama a tarefa Celery
        print("📨 Task enviada ao Celery com ID:", task.id)

        return {"task_id": task.id}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao processar currículo")

@router.get("/feedback-status/{task_id}")
def get_status(task_id: str):
    result = celery_app.AsyncResult(task_id)
    return {"status": result.status}

@router.get("/feedback-result/{task_id}")
def get_result(task_id: str):
    result = celery_app.AsyncResult(task_id)
    if result.ready():
        return {"feedback": result.get()}
    else:
        raise HTTPException(status_code=202, detail="Ainda processando...")

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
        content = await audio.read()

        if not content:
            raise HTTPException(
                status_code=422,
                detail="O áudio está vazio.",
            )

        suffix = os.path.splitext(
            audio.filename or "answer.m4a"
        )[1] or ".m4a"

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_path = temporary_file.name

        def transcribe():
            with open(temporary_path, "rb") as file:
                return client.audio.transcriptions.create(
                    model="whisper-1",
                    file=file,
                )

        transcription = await asyncio.to_thread(
            transcribe
        )

        transcript = transcription.text.strip()

        if not transcript:
            raise HTTPException(
                status_code=502,
                detail="Não foi possível transcrever o áudio.",
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
            detail=str(error),
        )

    finally:
        await audio.close()

        if temporary_path and os.path.exists(
            temporary_path
        ):
            os.remove(temporary_path)

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