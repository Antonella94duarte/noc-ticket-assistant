import logging

from fastapi import FastAPI

from app import __version__
from app.api.routes import api_router, health_router
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(title=settings.app_name, version=__version__)
    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()
