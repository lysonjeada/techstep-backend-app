# app/worker/tasks.py

# A importação para celery_app permanece como está, pois é necessária para o decorator @celery_app.task
from .celery_app import celery_app
import traceback
import uuid
from openai import OpenAI
import os
# CORREÇÃO AQUI: Ajuste o caminho de importação para extract_text_from_pdf
# Baseado em discussões anteriores, ele está em app/llm_generation/services.py
from app.llm_generation.services import extract_text_from_pdf
from dotenv import load_dotenv

from app.credits import service as credits_service
from app.database import SessionLocal
from app.observability import logger

load_dotenv()

# Mude o nome da instância do cliente OpenAI para evitar conflitos e deixar claro que é para o Celery
celery_openai_client = OpenAI()


def _refund_credit_after_task_failure(user_id: str, credit_cost: int) -> None:
    """O /submit-feedback/ debita o crédito (via ai_credit_gate) antes de
    enfileirar esta task — a chamada à OpenAI acontece aqui, fora do
    ciclo de requisição HTTP, então o reembolso automático da dependency
    do gate não alcança essa falha. Reembolsa manualmente aqui, com sua
    própria sessão de banco (a task roda num worker separado)."""

    db = SessionLocal()

    try:
        balance = credits_service.credit(
            db, uuid.UUID(user_id), credit_cost
        )

        logger.info(
            "ai credit refunded",
            extra={
                "event": "ai_credit_refunded",
                "userId": user_id,
                "scope": "resume_feedback_submit",
                "cost": credit_cost,
                "balanceAfter": balance,
                "source": "celery_task_failure",
            },
        )
    finally:
        db.close()


@celery_app.task(name="app.worker.tasks.process_resume_feedback") # Nome da tarefa com caminho completo
def process_resume_feedback(
    resume_bytes: bytes,
    user_id: str | None = None,
    credit_cost: int = 0,
) -> str:
    try:
        print("📥 Iniciando extração e análise do currículo...")

        resume_text = extract_text_from_pdf(resume_bytes)
        if not resume_text.strip():
            return "❌ Não foi possível extrair texto do PDF."

        print("📄 Primeiras palavras extraídas:", resume_text[:300], "...")

        prompt = (
            "Você é um recrutador especializado em avaliação de currículos. "
            "Analise o currículo abaixo e forneça sugestões construtivas. "
            "Evite reescrever o currículo. Foque nos seguintes pontos:\n\n"
            "- Clareza e organização\n"
            "- Uso de palavras-chave\n"
            "- Impacto e resultados mensuráveis\n"
            "- Problemas de formatação\n"
            "- Sugestões específicas de melhoria\n\n"
            f"Currículo:\n{resume_text}"
        )

        print("🔍 Enviando prompt para a OpenAI...")

        response = celery_openai_client.chat.completions.create( # Use a instância renomeada
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Você é um recrutador profissional experiente."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5
        )

        feedback = response.choices[0].message.content.strip()
        print("✅ Feedback retornado:", feedback[:300], "...")
        return feedback

    except Exception as e:
        traceback.print_exc()

        if user_id and credit_cost:
            _refund_credit_after_task_failure(user_id, credit_cost)

        # É importante levantar a exceção para que o Celery marque a tarefa como falha
        # e o backend possa obter o status de falha.
        # Se você retornar uma string de erro, o Celery considerará a tarefa como bem-sucedida com essa string.
        raise e # Lança a exceção para que o Celery a registre como falha
