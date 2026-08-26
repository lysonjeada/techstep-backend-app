from dotenv import load_dotenv
from fastapi import FastAPI

# Deve acontecer antes de importar módulos que criam o client da OpenAI.
load_dotenv()

from app import database
import app.models
import app.interview_simulation.models
import app.auth.models
import app.rate_limit.models
import app.credits.models

import time
import uuid

from fastapi import Request

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
from app.tutors.router import (
    router as tutors_router,
)
from app.videos.router import (
    router as videos_router,
)
from app.credits.router import (
    router as credits_router,
)
from app.articles.router import (
    router as articles_router,
)
from app.rate_limit.service import _client_ip

from app.observability import (
    logger,
)

app = FastAPI(
    title="Your Recruiting API",
    description=(
        "API for managing job applications, interviews, "
        "and AI-powered tools."
    ),
    version="0.1.0",
)

@app.middleware("http")
async def observability_middleware(
    request: Request,
    call_next,
):
    request_id = (
        request.headers.get(
            "X-Railway-Request-Id"
        )
        or str(uuid.uuid4())
    )

    started_at = (
        time.perf_counter()
    )

    try:
        response = await call_next(
            request
        )

        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.info(
            "request completed",
            extra={
                "requestId":
                    request_id,
                "method":
                    request.method,
                "path":
                    request.url.path,
                "statusCode":
                    response.status_code,
                "durationMs":
                    duration_ms,
                "event":
                    "http_request",
            },
        )

        response.headers[
            "X-Request-ID"
        ] = request_id

        return response

    except Exception:
        duration_ms = round(
            (
                time.perf_counter()
                - started_at
            )
            * 1000,
            2,
        )

        logger.exception(
            "request failed",
            extra={
                "requestId":
                    request_id,
                "method":
                    request.method,
                "path":
                    request.url.path,
                "statusCode":
                    500,
                "durationMs":
                    duration_ms,
                "event":
                    "http_request_failed",
            },
        )

        raise

@app.get("/system/client-ip", include_in_schema=False)
def get_client_ip(request: Request):
    """Devolve o IP exatamente como o rate limiter o calcula (ver
    app.rate_limit.service._client_ip), para usar em
    RATE_LIMIT_EXEMPT_IPS sem adivinhar entre IP local/de rede/público.
    """

    return {"ip": _client_ip(request)}


app.include_router(auth_router)
app.include_router(interviews_router)
app.include_router(llm_router)
app.include_router(job_router)
app.include_router(study_plan_router)
app.include_router(interview_simulation_router)
app.include_router(dashboard_router)
app.include_router(tutors_router)
app.include_router(videos_router)
app.include_router(credits_router)
app.include_router(articles_router)

# Todos os models importados acima serão registrados neste metadata.
database.Base.metadata.create_all(
    bind=database.engine
)