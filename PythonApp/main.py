from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
import models, schemas, database
from services.interview_generator import extract_text_from_pdf, build_prompt
from openai import OpenAI
import os
import traceback

from dotenv import load_dotenv
load_dotenv()

app = FastAPI()

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
    db_interview = models.Interview(**interview.dict())
    db.add(db_interview)
    db.commit()
    db.refresh(db_interview)
    return db_interview

@app.get("/interviews/{interview_id}", response_model=schemas.InterviewOut)
def read_interview(interview_id: str, db: Session = Depends(get_db)):
    interview = db.query(models.Interview).filter(models.Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview

@app.get("/interviews/", response_model=list[schemas.InterviewOut])
def list_interviews(db: Session = Depends(get_db)):
    interviews = db.query(models.Interview).all()
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

