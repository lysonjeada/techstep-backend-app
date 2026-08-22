from fastapi import (
    APIRouter,
    Depends,
    Query,
)

from sqlalchemy.orm import Session

from app import models
from app.auth.dependencies import get_current_user
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
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return build_progress_dashboard(
        db=db,
        user_id=current_user.id,
        months=months,
    )