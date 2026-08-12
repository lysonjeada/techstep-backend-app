# interviews/router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, date
from typing import List

from app.database import get_db

from .. import schemas, models # Importa schemas e models do nível acima

from app.auth.dependencies import (
    get_current_user,
)

router = APIRouter(
    prefix="/interviews",
    tags=["Interviews"]
)

@router.post(
    "/",
    response_model=schemas.InterviewOut,
    status_code=status.HTTP_201_CREATED,
)
def create_interview(
    interview: schemas.InterviewCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(
        get_current_user
    ),
):
    print(
        "📥 Dados recebidos:",
        interview.model_dump(),
        flush=True,
    )

    print(
        "👤 Usuário autenticado:",
        current_user.id,
        flush=True,
    )

    try:
        db_interview = models.Interview(
            **interview.model_dump(),
            user_id=current_user.id,
        )

        db.add(db_interview)
        db.commit()
        db.refresh(db_interview)

        print(
            "✅ Entrevista criada:",
            db_interview.id,
            flush=True,
        )

        return db_interview

    except Exception as error:
        db.rollback()

        print(
            "❌ Erro ao salvar entrevista:",
            repr(error),
            flush=True,
        )

        raise HTTPException(
            status_code=
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=
                "Erro ao salvar entrevista.",
        )

@router.get("/{interview_id}", response_model=schemas.InterviewOut)
def read_interview(interview_id: str, db: Session = Depends(get_db)):
    interview = db.query(models.Interview).filter(models.Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview

@router.get(
    "/",
    response_model=list[schemas.InterviewOut],
)
def list_interviews(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(
        get_current_user
    ),
):
    return (
        db.query(models.Interview)
        .filter(
            models.Interview.user_id
            == current_user.id
        )
        .order_by(
            models.Interview.created_at.desc()
        )
        .all()
    )

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

@router.get(
    "/next/",
    response_model=list[schemas.InterviewOut],
)
def get_upcoming_interviews(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(
        get_current_user
    ),
):
    today = date.today()

    print(
        "📅 GET /interviews/next/",
        flush=True,
    )

    print(
        "📅 Hoje:",
        today,
        flush=True,
    )

    print(
        "👤 Usuário:",
        current_user.id,
        flush=True,
    )

    # Apenas para debug:
    # mostra todas as entrevistas desse usuário.
    user_interviews = (
        db.query(models.Interview)
        .filter(
            models.Interview.user_id
            == current_user.id
        )
        .all()
    )

    print(
        "📦 Entrevistas totais do usuário:",
        len(user_interviews),
        flush=True,
    )

    for interview in user_interviews:
        print(
            (
                "🔎 "
                f"{interview.company_name} | "
                f"next_interview_date="
                f"{interview.next_interview_date}"
            ),
            flush=True,
        )

    upcoming_interviews = (
        db.query(models.Interview)
        .filter(
            models.Interview.user_id
            == current_user.id,
            models.Interview.next_interview_date
            .isnot(None),
            models.Interview.next_interview_date
            >= today,
        )
        .order_by(
            models.Interview.next_interview_date
            .asc()
        )
        .all()
    )

    print(
        "✅ Próximas entrevistas encontradas:",
        len(upcoming_interviews),
        flush=True,
    )

    for interview in upcoming_interviews:
        print(
            (
                "📌 PRÓXIMA: "
                f"{interview.company_name} | "
                f"{interview.next_interview_date}"
            ),
            flush=True,
        )

    return upcoming_interviews