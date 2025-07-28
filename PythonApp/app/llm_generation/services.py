# app/llm_generation/services.py
from pypdf import PdfReader
from io import BytesIO
from typing import Optional # Importe Optional para o tipo description

def extract_text_from_pdf(pdf_content: bytes) -> str:
    """
    Extrai texto de um conteúdo PDF em bytes.
    """
    reader = PdfReader(BytesIO(pdf_content))
    text = ""
    for page in reader.pages:
        # Use .extract_text() para obter o texto de cada página
        text += page.extract_text() or ""
    return text

def build_prompt(resume_text: str, job_title: str, seniority: str, description: Optional[str]) -> str:
    """
    Constrói o prompt para a geração de perguntas de entrevista.
    """
    prompt = (
        f"Analise o currículo abaixo para a vaga de {job_title} ({seniority}).\n"
        f"Gere 5 perguntas de entrevista técnicas e 3 comportamentais baseadas exclusivamente no currículo e na descrição da vaga (se houver).\n"
        f"O currículo é o seguinte:\n{resume_text}\n"
    )
    if description:
        prompt += f"A descrição da vaga é:\n{description}\n"
    prompt += "Liste as perguntas numericamente."
    return prompt

# O cliente OpenAI não é definido aqui neste arquivo de serviços,
# ele será definido no router ou no worker que o utiliza diretamente.
# Caso contrário, você pode ter importações circulares ou problemas de inicialização.