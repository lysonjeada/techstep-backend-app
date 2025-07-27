from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session
import models, schemas, database
from services.interview_generator import extract_text_from_pdf, build_prompt
from openai import OpenAI
import os
import traceback
from worker.tasks import process_resume_feedback
from datetime import datetime, timedelta
from utils.serializers import serialize_list
from dotenv import load_dotenv
from jobs_service import job_router

from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer 

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

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

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
    
    return serialize_list(interviews, schemas.InterviewOut)

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
    soon = now + timedelta(days=120)

    interviews = db.query(models.Interview)\
        .filter(
            models.Interview.next_interview_date != None,
            models.Interview.next_interview_date >= now,
            models.Interview.next_interview_date <= soon
        )\
        .order_by(models.Interview.next_interview_date.asc())\
        .all()

    return serialize_list(interviews, schemas.InterviewOut)

@app.post("/users/register/", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    """
    Endpoint para registrar um novo usuário.
    Requer email, username e senha.
    A senha é hashed antes de ser armazenada.
    """
    # --- SANITIZAÇÃO DOS DADOS: REMOVENDO ESPAÇOS EM BRANCO ---
    # Aplica .strip() para remover espaços em branco no início e no fim
    cleaned_email = user.email.strip()
    cleaned_username = user.username.strip()
    cleaned_password = user.password.strip() # Importante limpar antes de hashear!

    # Opcional: Você pode adicionar validação para garantir que os campos não fiquem vazios
    # APÓS o strip, se eles forem obrigatórios e não puderem ser apenas espaços.
    if not cleaned_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email não pode ser vazio.")
    if not cleaned_username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nome de usuário não pode ser vazio.")
    if not cleaned_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Senha não pode ser vazia.")

    # Verifica se o email já existe usando o email limpo
    db_user_email = db.query(models.User).filter(models.User.email == cleaned_email).first()
    if db_user_email:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email já registrado")

    # Verifica se o username já existe usando o username limpo
    db_user_username = db.query(models.User).filter(models.User.username == cleaned_username).first()
    if db_user_username:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nome de usuário já existe")

    # Hasheia a senha limpa
    hashed_password = get_password_hash(cleaned_password)
    
    # Cria o novo usuário com os dados limpos
    db_user = models.User(
        email=cleaned_email,
        username=cleaned_username,
        hashed_password=hashed_password
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return db_user

@app.post("/users/login/", response_model=schemas.UserOut) # Ou um token de acesso para sistemas mais complexos
def login_user(user_credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    """
    Endpoint para login de usuário.
    Verifica as credenciais (username e senha) no banco de dados.
    """
    db_user = db.query(models.User).filter(models.User.username == user_credentials.username).first()

    if not db_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário ou senha inválidos")

    # Verifica a senha hashed
    if not verify_password(user_credentials.password, db_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário ou senha inválidos")

    # Retorna os dados do usuário se o login for bem-sucedido
    # Em um sistema real, aqui você geraria e retornaria um token JWT
    return db_user

@app.get("/users/{user_id}", response_model=schemas.UserOut)
def get_user(user_id: str, db: Session = Depends(get_db)):
    """
    Endpoint para buscar um usuário pelo ID.
    """
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")
    return db_user

@app.put("/users/{user_id}", response_model=schemas.UserOut)
def update_user(user_id: str, updated_user: schemas.UserUpdate, db: Session = Depends(get_db)):
    """
    Endpoint para atualizar as informações de um usuário.
    Permite atualizar email, username e/ou senha.
    """
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")

    # Atualiza email se fornecido e se não for duplicado
    if updated_user.email is not None and updated_user.email != db_user.email:
        existing_email_user = db.query(models.User).filter(models.User.email == updated_user.email).first()
        if existing_email_user:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Novo email já está em uso")
        db_user.email = updated_user.email

    # Atualiza username se fornecido e se não for duplicado
    if updated_user.username is not None and updated_user.username != db_user.username:
        existing_username_user = db.query(models.User).filter(models.User.username == updated_user.username).first()
        if existing_username_user:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Novo nome de usuário já está em uso")
        db_user.username = updated_user.username

    # Atualiza senha se fornecida
    if updated_user.password is not None:
        db_user.hashed_password = get_password_hash(updated_user.password)

    db.commit()
    db.refresh(db_user)
    return db_user

@app.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, db: Session = Depends(get_db)):
    """
    Endpoint para deletar um usuário pelo ID.
    Retorna status 204 No Content em caso de sucesso.
    """
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")
    
    db.delete(db_user)
    db.commit()
    return # Retorna 204 No Content automaticamente