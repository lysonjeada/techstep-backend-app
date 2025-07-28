# llm_generation/router.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from openai import OpenAI # Importa OpenAI aqui
import traceback
import os
from dotenv import load_dotenv

from .services import extract_text_from_pdf, build_prompt
from ..worker.tasks import process_resume_feedback # Importa a tarefa Celery do nível acima
from ..worker.celery_app import celery_app # Importa a instância do Celery

load_dotenv() # Carrega variáveis de ambiente para este arquivo também

router = APIRouter(
    tags=["LLM Generation"]
)

# Inicializa o cliente OpenAI aqui (ou passe como dependência se preferir)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@router.post("/generate-interview-questions/")
async def generate_questions(
    resume: UploadFile = File(...),
    job_title: str = Form(...),
    seniority: str = Form(...),
    description: str = Form(None)
):
    try:
        content = await resume.read()
        resume_text = extract_text_from_pdf(content)
        prompt = build_prompt(resume_text, job_title, seniority, description)
        print("🔍 Prompt gerado:", prompt)

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Você é um recrutador técnico experiente."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )

        print("✅ Resposta OpenAI:", response)

        questions = response.choices[0].message.content

        question_lines = questions.strip().split("\n")
        question_list = [
            line.lstrip("0123456789. ").strip()
            for line in question_lines
            if line.strip()
        ]

        return {"questions": question_list}

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

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