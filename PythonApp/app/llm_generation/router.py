# llm_generation/router.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from openai import OpenAI # Importa OpenAI aqui
import traceback
import os
import asyncio
import re
from dotenv import load_dotenv

from .services import extract_text_from_pdf, build_prompt
from ..worker.tasks import process_resume_feedback # Importa a tarefa Celery do nível acima
from ..worker.celery_app import celery_app # Importa a instância do Celery
from typing import Optional

load_dotenv() # Carrega variáveis de ambiente para este arquivo também

router = APIRouter(
    tags=["LLM Generation"]
)

# Inicializa o cliente OpenAI aqui (ou passe como dependência se preferir)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


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