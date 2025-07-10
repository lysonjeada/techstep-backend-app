from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
import models, schemas, database
from services.interview_generator import extract_text_from_pdf, build_prompt
from openai import OpenAI
import os
import traceback
from worker.tasks import process_resume_feedback
from datetime import datetime, timedelta

from dotenv import load_dotenv
from jobs_service import job_router

load_dotenv()

app = FastAPI()

app.include_router(job_router)

task_results = {}

# Cria as tabelas caso ainda não existam
models.Base.metadata.create_all(bind=database.engine)

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/interviews/", response_model=schemas.InterviewOut)
def create_interview(interview: schemas.InterviewCreate, db: Session = Depends(get_db)):
    print("📥 Dados recebidos no corpo da requisição:")
    print(interview.dict())

    try:
        db_interview = models.Interview(**interview.dict())
        db.add(db_interview)
        db.commit()
        db.refresh(db_interview)
        return db_interview
    except Exception as e:
        print("❌ Erro ao salvar entrevista:", str(e))
        raise HTTPException(status_code=500, detail="Erro ao salvar entrevista")

@app.get("/interviews/{interview_id}", response_model=schemas.InterviewOut)
def read_interview(interview_id: str, db: Session = Depends(get_db)):
    interview = db.query(models.Interview).filter(models.Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview

@app.get("/interviews/", response_model=list[schemas.InterviewOut])
def list_interviews(db: Session = Depends(get_db)):
    interviews = db.query(models.Interview)\
        .order_by(models.Interview.created_at.desc())\
        .all()
    return interviews

@app.put("/interviews/{interview_id}", response_model=schemas.InterviewOut)
def update_interview(interview_id: str, updated: schemas.InterviewUpdate, db: Session = Depends(get_db)):
    interview = db.query(models.Interview).filter(models.Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    for key, value in updated.dict(exclude_unset=True).items():
        setattr(interview, key, value)
    db.commit()
    db.refresh(interview)
    return interview

@app.delete("/interviews/{interview_id}")
def delete_interview(interview_id: str, db: Session = Depends(get_db)):
    interview = db.query(models.Interview).filter(models.Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    db.delete(interview)
    db.commit()
    return {"detail": "Interview deleted"}

client = OpenAI()

@app.post("/generate-interview-questions/")
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
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/resume-feedback/")
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

    

@app.post("/submit-feedback/")
async def submit_resume(resume: UploadFile = File(...)):
    try:
        content = await resume.read()
        # ✅ Envia a tarefa para o Celery
        task = process_resume_feedback.delay(content)
        print("📨 Task enviada ao Celery com ID:", task.id)

        return {"task_id": task.id}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao processar currículo")

@app.get("/feedback-status/{task_id}")
def get_status(task_id: str):
    from worker.celery_app import celery_app
    result = celery_app.AsyncResult(task_id)
    return {"status": result.status}

@app.get("/feedback-result/{task_id}")
def get_result(task_id: str):
    from worker.celery_app import celery_app
    result = celery_app.AsyncResult(task_id)
    if result.ready():
        return {"feedback": result.get()}
    else:
        return {"detail": "Ainda processando..."}, 202

@app.get("/interviews/next/", response_model=list[schemas.InterviewOut])
def get_upcoming_interviews(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    soon = now + timedelta(hours=480)  # pode ajustar para dias ou horas
    
    interviews = (
        db.query(models.Interview)
        .filter(
            models.Interview.next_interview_date != None,
            models.Interview.next_interview_date >= now,
            models.Interview.next_interview_date <= soon
        )
        .order_by(models.Interview.next_interview_date.asc())
        .all()
    )
    
    return interviews
