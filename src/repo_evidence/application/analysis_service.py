import uuid
from dataclasses import dataclass

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession

from repo_evidence.analysis.context import AnalysisContext
from repo_evidence.analysis.rules import run_rules
from repo_evidence.analysis.scoring import build_scorecard
from repo_evidence.application.errors import AnalysisFailed, AnalysisNotFound, AppError
from repo_evidence.config import Settings
from repo_evidence.infrastructure.github import (
    GitHubClient,
    parse_repository_url,
    repository_source_path,
)
from repo_evidence.infrastructure.repositories import AnalysisStore, RepositoryStore


@dataclass(slots=True, frozen=True)
class AnalysisRequestResult:
    analysis_id: uuid.UUID
    status: str
    cached: bool


class AnalysisService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        github: GitHubClient,
        celery: Celery | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.github = github
        self.celery = celery
        self.repositories = RepositoryStore(session)
        self.analyses = AnalysisStore(session)

    async def request(self, repository_url: str) -> AnalysisRequestResult:
        ref = parse_repository_url(repository_url)
        github_repository = await self.github.resolve(ref)
        repository = await self.repositories.upsert(github_repository)
        existing = await self.analyses.get_by_identity(
            repository.id, github_repository.commit_sha, self.settings.analyzer_version
        )
        if existing:
            await self.session.commit()
            return AnalysisRequestResult(existing.id, existing.status, True)
        analysis, created = await self.analyses.create_or_get(
            repository.id, github_repository.commit_sha, self.settings.analyzer_version
        )
        await self.session.commit()
        if created and self.celery:
            self.celery.send_task("repo_evidence.run_analysis", args=[str(analysis.id)])
        return AnalysisRequestResult(analysis.id, analysis.status, not created)

    async def execute(self, analysis_id: uuid.UUID) -> None:
        analysis = await self.analyses.get(analysis_id)
        if analysis is None:
            raise AnalysisNotFound("Анализ не найден.")
        await self.analyses.mark_running(analysis)
        await self.session.commit()
        try:
            github_repository = await self.github.resolve(
                parse_repository_url(analysis.repository.html_url)
            )
            if github_repository.commit_sha != analysis.commit_sha:
                github_repository = type(github_repository)(
                    ref=github_repository.ref,
                    default_branch=github_repository.default_branch,
                    commit_sha=analysis.commit_sha,
                )
            temporary = await self.github.download_and_extract(github_repository)
            try:
                context = AnalysisContext.build(
                    repository_source_path(temporary), self.settings.max_text_file_bytes
                )
                scorecard = build_scorecard(run_rules(context))
                analysis = await self.analyses.get(analysis_id)
                if analysis is None:
                    raise AnalysisNotFound("Анализ удалён во время выполнения.")
                await self.analyses.complete(analysis, context.framework, scorecard)
                await self.session.commit()
            finally:
                temporary.cleanup()
        except AppError as exc:
            await self.session.rollback()
            analysis = await self.analyses.get(analysis_id, loaded=False)
            if analysis:
                await self.analyses.fail(analysis, exc.code, exc.detail)
                await self.session.commit()
            raise
        except Exception as exc:
            await self.session.rollback()
            analysis = await self.analyses.get(analysis_id, loaded=False)
            if analysis:
                await self.analyses.fail(analysis, "analysis_failed", "Внутренняя ошибка анализа.")
                await self.session.commit()
            raise AnalysisFailed("Внутренняя ошибка анализа.") from exc
