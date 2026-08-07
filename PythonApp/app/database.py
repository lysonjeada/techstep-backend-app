import os
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker


load_dotenv()


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:D%40823%21@localhost:15432/techstep",
)


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
