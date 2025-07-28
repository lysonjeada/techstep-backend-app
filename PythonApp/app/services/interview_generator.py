import fitz  # PyMuPDF

def extract_text_from_pdf(pdf_bytes: bytes, max_words=1500) -> str:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()

        words = text.split()
        if len(words) > max_words:
            text = " ".join(words[:max_words])
        return text
    except Exception as e:
        print("❌ Erro ao extrair texto do PDF:", e)
        return ""

def build_prompt(resume_text: str, job_title: str, seniority: str, description: str = "") -> str:
    return f"""
Com base no seguinte currículo:

{resume_text}

E considerando a vaga de {job_title} com nível de senioridade {seniority}{',' if description else ''} {f"a seguinte descrição da vaga: {description}" if description else ""},
gere uma lista com 5 perguntas técnicas que poderiam ser feitas em uma entrevista para essa vaga.
Responda com uma lista simples de perguntas, sem introduções, títulos ou explicações.
"""
