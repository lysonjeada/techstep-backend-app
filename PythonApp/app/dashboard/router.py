from fastapi import (
    APIRouter,
    Depends,
    Query,
)

from sqlalchemy.orm import Session

from app.database import get_db
from app.dashboard.schemas import (
    ProgressDashboardResponse,
)
from app.dashboard.service import (
    build_progress_dashboard,
)

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
)

@router.get(
    "/progress",
    response_model=ProgressDashboardResponse,
)
def get_progress_dashboard(
    months: int = Query(
        default=6,
        ge=3,
        le=12,
    ),
    db: Session = Depends(get_db),
):
    return build_progress_dashboard(
        db=db,
        months=months,
    )