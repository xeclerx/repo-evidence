import asyncio
import uuid

import structlog
from celery import Celery

from repo_evidence.application.analysis_service import AnalysisService
from repo_evidence.config import get_settings
from repo_evidence.database import session_factory
from repo_evidence.infrastructure.github import GitHubClient
from repo_evidence.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)

celery_app = Celery("repo_evidence", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_time_limit=settings.analysis_timeout_seconds,
    task_soft_time_limit=max(10, settings.analysis_timeout_seconds - 5),
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


async def _execute(analysis_id: uuid.UUID) -> None:
    async with session_factory() as session:
        service = AnalysisService(session, settings, GitHubClient(settings))
        await service.execute(analysis_id)


@celery_app.task(name="repo_evidence.run_analysis")  # type: ignore[untyped-decorator]
def run_analysis_task(analysis_id: str) -> None:
    logger.info("analysis_started", analysis_id=analysis_id)
    asyncio.run(_execute(uuid.UUID(analysis_id)))
    logger.info("analysis_finished", analysis_id=analysis_id)
