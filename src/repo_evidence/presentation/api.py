import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from repo_evidence.application.analysis_service import AnalysisService
from repo_evidence.application.errors import (
    AnalysisNotFound,
    IncompatibleAnalysisVersions,
    InvalidComparison,
    ReportNotReady,
)
from repo_evidence.config import Settings, get_settings
from repo_evidence.database import get_session
from repo_evidence.infrastructure.github import GitHubClient
from repo_evidence.infrastructure.repositories import AnalysisStore, RepositoryStore
from repo_evidence.presentation.schemas import (
    AnalysisCreate,
    AnalysisRequestResponse,
    AnalysisResponse,
    CheckChange,
    ComparisonResponse,
    HistoryResponse,
    ReportResponse,
)
from repo_evidence.presentation.serializers import (
    analysis_response,
    report_response,
    repository_response,
)
from repo_evidence.worker import celery_app

router = APIRouter(prefix="/api/v1")
health_router = APIRouter(prefix="/health")


@router.post("/analyses", response_model=AnalysisRequestResponse)
async def create_analysis(
    payload: AnalysisCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AnalysisRequestResponse:
    service = AnalysisService(session, settings, GitHubClient(settings), celery_app)
    result = await service.request(str(payload.repository_url))
    response.status_code = 200 if result.cached and result.status == "completed" else 202
    return AnalysisRequestResponse(
        analysis_id=result.analysis_id,
        status=result.status,
        cached=result.cached,
        status_url=f"/api/v1/analyses/{result.analysis_id}",
        report_url=f"/reports/{result.analysis_id}",
    )


@router.get("/analyses/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> AnalysisResponse:
    analysis = await AnalysisStore(session).get(analysis_id)
    if analysis is None:
        raise AnalysisNotFound("Анализ не найден.")
    return analysis_response(analysis)


@router.get("/analyses/{analysis_id}/report", response_model=ReportResponse)
async def get_report(
    analysis_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ReportResponse:
    analysis = await AnalysisStore(session).get(analysis_id)
    if analysis is None:
        raise AnalysisNotFound("Анализ не найден.")
    if analysis.status != "completed":
        raise ReportNotReady("Отчёт ещё не готов.")
    return report_response(analysis)


@router.get("/repositories/{owner}/{name}/analyses", response_model=HistoryResponse)
async def get_history(
    owner: str, name: str, session: AsyncSession = Depends(get_session)
) -> HistoryResponse:
    repository = await RepositoryStore(session).get_by_slug(owner, name)
    if repository is None:
        raise AnalysisNotFound("История репозитория не найдена.")
    analyses = await AnalysisStore(session).history(repository.id)
    return HistoryResponse(
        repository=repository_response(repository),
        analyses=[analysis_response(item) for item in analyses],
    )


@router.get("/comparisons", response_model=ComparisonResponse)
async def compare_analyses(
    base: uuid.UUID = Query(),
    head: uuid.UUID = Query(),
    session: AsyncSession = Depends(get_session),
) -> ComparisonResponse:
    store = AnalysisStore(session)
    base_analysis = await store.get(base)
    head_analysis = await store.get(head)
    if base_analysis is None or head_analysis is None:
        raise AnalysisNotFound("Один из сравниваемых анализов не найден.")
    if base_analysis.repository_id != head_analysis.repository_id:
        raise InvalidComparison("Можно сравнивать только один репозиторий.")
    if base_analysis.analyzer_version != head_analysis.analyzer_version:
        raise IncompatibleAnalysisVersions(
            "Версии анализатора различаются; повторите анализ обоих commit текущей версией."
        )
    if base_analysis.status != "completed" or head_analysis.status != "completed":
        raise InvalidComparison("Оба анализа должны быть завершены.")
    base_checks = {item.check_id: item for item in base_analysis.checks}
    head_checks = {item.check_id: item for item in head_analysis.checks}
    improved: list[CheckChange] = []
    regressed: list[CheckChange] = []
    unchanged = 0
    for check_id in sorted(base_checks.keys() & head_checks.keys()):
        before = base_checks[check_id]
        after = head_checks[check_id]
        change = CheckChange(
            check_id=check_id,
            title=after.title,
            before_status=before.status,
            after_status=after.status,
            points_delta=round(after.points - before.points, 2),
        )
        if change.points_delta > 0:
            improved.append(change)
        elif change.points_delta < 0:
            regressed.append(change)
        else:
            unchanged += 1
    base_categories = {item.category: item.score for item in base_analysis.categories}
    head_categories = {item.category: item.score for item in head_analysis.categories}
    return ComparisonResponse(
        base=analysis_response(base_analysis),
        head=analysis_response(head_analysis),
        score_delta=(
            round(head_analysis.score - base_analysis.score, 2)
            if head_analysis.score is not None and base_analysis.score is not None
            else None
        ),
        category_deltas={
            key: round(head_categories.get(key, 0) - base_categories.get(key, 0), 2)
            for key in sorted(base_categories.keys() | head_categories.keys())
        },
        improved=improved,
        regressed=regressed,
        unchanged_count=unchanged,
    )


@health_router.get("/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/ready")
async def readiness(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    from redis.asyncio import Redis

    redis = Redis.from_url(get_settings().redis_url)
    try:
        await redis.ping()
    finally:
        await redis.aclose()
    return {"status": "ready"}
