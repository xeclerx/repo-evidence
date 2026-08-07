import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from structlog.contextvars import bind_contextvars, clear_contextvars

from repo_evidence.application.errors import AppError
from repo_evidence.config import get_settings
from repo_evidence.logging import configure_logging
from repo_evidence.presentation.api import health_router
from repo_evidence.presentation.api import router as api_router
from repo_evidence.presentation.web import router as web_router
from repo_evidence.telemetry import configure_telemetry

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)

app = FastAPI(
    title="RepoEvidence API",
    version="0.1.0",
    description="Прозрачный статический анализ Python backend-репозиториев.",
    debug=settings.app_debug,
)
package_root = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=package_root / "static"), name="static")
app.include_router(health_router)
app.include_router(api_router)
app.include_router(web_router)
configure_telemetry(app, settings)


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[object]]
) -> object:
    clear_contextvars()
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:100]
    bind_contextvars(request_id=request_id, method=request.method, path=request.url.path)
    response = await call_next(request)
    response.headers["x-request-id"] = request_id  # type: ignore[attr-defined]
    response.headers["x-robots-tag"] = "noindex, nofollow"  # type: ignore[attr-defined]
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.info("application_error", code=exc.code, path=request.url.path)
    return JSONResponse(
        status_code=exc.status_code,
        media_type="application/problem+json",
        content={
            "type": f"https://repo-evidence.local/problems/{exc.code}",
            "title": exc.code,
            "status": exc.status_code,
            "detail": exc.detail,
            "instance": request.url.path,
            "code": exc.code,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        media_type="application/problem+json",
        content={
            "type": "https://repo-evidence.local/problems/validation_error",
            "title": "validation_error",
            "status": 422,
            "detail": "Запрос не соответствует API-контракту.",
            "instance": request.url.path,
            "code": "validation_error",
            "errors": jsonable_encoder(exc.errors()),
        },
    )
