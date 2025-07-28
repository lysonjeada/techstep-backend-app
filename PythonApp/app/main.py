from fastapi import FastAPI, Depends
from . import models, database
from dotenv import load_dotenv

from app.auth.router import router as auth_router
from app.interviews.router import router as interviews_router
from app.llm_generation.router import router as llm_router 
from app.jobs_service.job_router import job_router as job_router 

load_dotenv()

app = FastAPI(
    title="Your Recruiting API",
    description="API for managing job applications, interviews, and AI-powered tools.",
    version="0.1.0",
)

app.include_router(auth_router)
app.include_router(interviews_router)
app.include_router(llm_router)
app.include_router(job_router)

models.Base.metadata.create_all(bind=database.engine)