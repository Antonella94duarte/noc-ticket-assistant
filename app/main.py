import logging
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import FileResponse, JSONResponse

from app import __version__
from app.api.routes import api_router, health_router
from app.config import get_settings
from app.llm.client import LLMError, LLMNotConfiguredError

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LLMNotConfiguredError)
    def llm_not_configured(request: Request, exc: LLMNotConfiguredError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
        )

    @app.exception_handler(LLMError)
    def llm_failed(request: Request, exc: LLMError) -> JSONResponse:
        # Log the cause but don't leak provider details to the client.
        logger.warning("LLM call failed on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": "The analysis model could not process the ticket"},
        )


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(title=settings.app_name, version=__version__)
    _register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    def demo_page() -> FileResponse:
        """Single-page demo UI that calls the API above."""
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
