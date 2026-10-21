import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.db.session import get_db
from app.schemas import HealthResponse

logger = logging.getLogger(__name__)

health_router = APIRouter(tags=["health"])
api_router = APIRouter(prefix="/api/v1")


@health_router.get("/health", response_model=HealthResponse)
def health(response: Response, db: Session = Depends(get_db)) -> HealthResponse:
    """Report API status and whether the database answers a trivial query."""
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except SQLAlchemyError:
        logger.exception("Database health check failed")
        database = "unavailable"

    if database != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", database=database, version=__version__)
    return HealthResponse(status="ok", database=database, version=__version__)
