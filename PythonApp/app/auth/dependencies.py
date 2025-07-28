# app/auth/dependencies.py
from sqlalchemy.orm import Session
from passlib.context import CryptContext
# from fastapi.security import OAuth2PasswordBearer # Se for usar segurança de token
from app.database import SessionLocal # Importa SessionLocal do pacote 'app'

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

# Se você for implementar JWT, você definiria o oauth2_scheme aqui:
# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="users/token")