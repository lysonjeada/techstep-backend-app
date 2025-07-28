# auth/router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app import schemas, models # Importa schemas e models do nível acima
from .dependencies import get_db, verify_password, get_password_hash # Importa as dependências

router = APIRouter(
    prefix="/users",
    tags=["Users and Authentication"]
)

@router.post("/register/", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    cleaned_email = user.email.strip()
    cleaned_username = user.username.strip()
    cleaned_password = user.password.strip()

    if not cleaned_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email não pode ser vazio.")
    if not cleaned_username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nome de usuário não pode ser vazio.")
    if not cleaned_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Senha não pode ser vazia.")

    db_user_email = db.query(models.User).filter(models.User.email == cleaned_email).first()
    if db_user_email:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email já registrado")

    db_user_username = db.query(models.User).filter(models.User.username == cleaned_username).first()
    if db_user_username:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nome de usuário já existe")

    hashed_password = get_password_hash(cleaned_password)
    
    db_user = models.User(
        email=cleaned_email,
        username=cleaned_username,
        hashed_password=hashed_password
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return db_user

@router.post("/login/", response_model=schemas.UserOut)
def login_user(user_credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.username == user_credentials.username).first()

    if not db_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário ou senha inválidos")

    if not verify_password(user_credentials.password, db_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário ou senha inválidos")

    return db_user

@router.get("/{user_id}", response_model=schemas.UserOut)
def get_user(user_id: str, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")
    return db_user

@router.put("/{user_id}", response_model=schemas.UserOut)
def update_user(user_id: str, updated_user: schemas.UserUpdate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")

    if updated_user.email is not None and updated_user.email != db_user.email:
        existing_email_user = db.query(models.User).filter(models.User.email == updated_user.email).first()
        if existing_email_user:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Novo email já está em uso")
        db_user.email = updated_user.email

    if updated_user.username is not None and updated_user.username != db_user.username:
        existing_username_user = db.query(models.User).filter(models.User.username == updated_user.username).first()
        if existing_username_user:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Novo nome de usuário já está em uso")
        db_user.username = updated_user.username

    if updated_user.password is not None:
        db_user.hashed_password = get_password_hash(updated_user.password)

    db.commit()
    db.refresh(db_user)
    return db_user

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")
    
    db.delete(db_user)
    db.commit()
    return