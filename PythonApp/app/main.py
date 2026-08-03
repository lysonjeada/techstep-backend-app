from dotenv import load_dotenv
from fastapi import FastAPI

# Deve acontecer antes de importar módulos que criam o client da OpenAI.
load_dotenv()

from app import database
import app.models
import app.interview_simulation.models

from app.auth.router import router as auth_router
from app.interviews.router import router as interviews_router
from app.llm_generation.router import router as llm_router
from app.jobs_service.job_router import job_router
from app.study_plan.router import router as study_plan_router
from app.interview_simulation.router import (
    router as interview_simulation_router
)
from app.dashboard.router import (
    router as dashboard_router,
)

app = FastAPI(
    title="Your Recruiting API",
    description=(
        "API for managing job applications, interviews, "
        "and AI-powered tools."
    ),
    version="0.1.0",
)

app.include_router(auth_router)
app.include_router(interviews_router)
app.include_router(llm_router)
app.include_router(job_router)
app.include_router(study_plan_router)
app.include_router(interview_simulation_router)
app.include_router(dashboard_router)

# Todos os models importados acima serão registrados neste metadata.
database.Base.metadata.create_all(
    bind=database.engine
)