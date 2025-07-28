# interviews/router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List

from .. import schemas, models # Importa schemas e models do nível acima
from ..auth.dependencies import get_db # Importa get_db do diretório auth

router = APIRouter(
    prefix="/interviews",
    tags=["Interviews"]
)

@router.post("/", response_model=schemas.InterviewOut)
def create_interview(interview: schemas.InterviewCreate, db: Session = Depends(get_db)):
    print("📥 Dados recebidos no corpo da requisição:", interview.dict())

    try:
        # AQUI, se você alterou last_interview_date/next_interview_date para 'date' no schema
        # e eles vêm como `date` de fato, o `**interview.dict()` funcionará.
        # Se você ainda está recebendo `datetime` aqui para as datas, mas o DB espera `date`,
        # você precisaria converter:
        # db_interview = models.Interview(
        #     **interview.dict(exclude={"last_interview_date", "next_interview_date"}),
        #     last_interview_date=interview.last_interview_date.date() if interview.last_interview_date else None,
        #     next_interview_date=interview.next_interview_date.date() if interview.next_interview_date else None
        # )
        # Mas com schemas.InterviewBase usando `Optional[date]`, isso já é tratado pelo Pydantic.
        
        db_interview = models.Interview(**interview.dict())
        db.add(db_interview)
        db.commit()
        db.refresh(db_interview)
        return db_interview
    except Exception as e:
        print("❌ Erro ao salvar entrevista:", str(e))
        raise HTTPException(status_code=500, detail="Erro ao salvar entrevista")

@router.get("/{interview_id}", response_model=schemas.InterviewOut)
def read_interview(interview_id: str, db: Session = Depends(get_db)):
    interview = db.query(models.Interview).filter(models.Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview

@router.get("/", response_model=List[schemas.InterviewOut])
def list_interviews(db: Session = Depends(get_db)):
    interviews = db.query(models.Interview)\
        .order_by(models.Interview.created_at.desc())\
        .all()
    # Não precisa de serialize_list se schemas.InterviewOut tem from_attributes=True
    return interviews

@router.put("/{interview_id}", response_model=schemas.InterviewOut)
def update_interview(interview_id: str, updated: schemas.InterviewUpdate, db: Session = Depends(get_db)):
    interview = db.query(models.Interview).filter(models.Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    # Exclua id para não tentar atualizar a PK
    for key, value in updated.dict(exclude_unset=True).items():
        setattr(interview, key, value)
    
    # Se você mudou para `date` no schema, e o DB é `DateTime`, pode haver necessidade de converter
    # if 'last_interview_date' in updated.dict(exclude_unset=True) and updated.last_interview_date is not None:
    #     interview.last_interview_date = updated.last_interview_date.date()
    # if 'next_interview_date' in updated.dict(exclude_unset=True) and updated.next_interview_date is not None:
    #     interview.next_interview_date = updated.next_interview_date.date()

    db.commit()
    db.refresh(interview)
    return interview

@router.delete("/{interview_id}")
def delete_interview(interview_id: str, db: Session = Depends(get_db)):
    interview = db.query(models.Interview).filter(models.Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    db.delete(interview)
    db.commit()
    return {"detail": "Interview deleted"}

@router.get("/next/", response_model=List[schemas.InterviewOut])
def get_upcoming_interviews(db: Session = Depends(get_db)):
    # Certifique-se de que os tipos aqui (datetime) correspondem ao tipo da coluna no DB (models.Interview.next_interview_date)
    # Se a coluna for `Date`, mude para `date.today()` e `date + timedelta`.
    now = datetime.utcnow() # Assume que next_interview_date no DB é DateTime
    soon = now + timedelta(days=120)

    interviews = db.query(models.Interview)\
        .filter(
            models.Interview.next_interview_date != None,
            models.Interview.next_interview_date >= now,
            models.Interview.next_interview_date <= soon
        )\
        .order_by(models.Interview.next_interview_date.asc())\
        .all()
    
    return interviews # Retorna diretamente para serialização automática