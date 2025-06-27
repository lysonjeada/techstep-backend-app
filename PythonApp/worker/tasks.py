# tasks.py

from .celery_app import celery_app
import traceback
import fitz
from openai import OpenAI
import os
from services.interview_generator import extract_text_from_pdf
from dotenv import load_dotenv

load_dotenv()

client = OpenAI()

@celery_app.task(name="worker.tasks.process_resume_feedback")
def process_resume_feedback(resume_bytes: bytes) -> str:
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

        response = client.chat.completions.create(
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
        return "❌ Erro ao gerar feedback do currículo."
