import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from repo_evidence.domain.models import AnalysisStatus, Framework, ScoreCard
from repo_evidence.infrastructure.db_models import (
    AnalysisORM,
    CategoryResultORM,
    CheckResultORM,
    EvidenceORM,
    RecommendationORM,
    RepositoryORM,
)
from repo_evidence.infrastructure.github import GitHubRepository

ANALYSIS_LOAD_OPTIONS = (
    selectinload(AnalysisORM.repository),
    selectinload(AnalysisORM.categories),
    selectinload(AnalysisORM.checks).selectinload(CheckResultORM.evidence),
    selectinload(AnalysisORM.checks).selectinload(CheckResultORM.recommendation),
)


class RepositoryStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, github: GitHubRepository) -> RepositoryORM:
        identifier = await self.session.scalar(
            insert(RepositoryORM)
            .values(
                owner=github.ref.owner,
                name=github.ref.name,
                html_url=github.ref.html_url,
                default_branch=github.default_branch,
            )
            .on_conflict_do_update(
                constraint="uq_repository_owner_name",
                set_={
                    "html_url": github.ref.html_url,
                    "default_branch": github.default_branch,
                },
            )
            .returning(RepositoryORM.id)
        )
        if identifier is None:  # pragma: no cover - RETURNING is guaranteed by PostgreSQL
            raise RuntimeError("Repository upsert did not return an identifier")
        result = await self.session.execute(
            select(RepositoryORM).where(RepositoryORM.id == identifier)
        )
        return result.scalar_one()

    async def get_by_slug(self, owner: str, name: str) -> RepositoryORM | None:
        result = await self.session.execute(
            select(RepositoryORM).where(RepositoryORM.owner == owner, RepositoryORM.name == name)
        )
        return result.scalar_one_or_none()


class AnalysisStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_identity(
        self, repository_id: uuid.UUID, commit_sha: str, analyzer_version: str
    ) -> AnalysisORM | None:
        result = await self.session.execute(
            select(AnalysisORM)
            .where(
                AnalysisORM.repository_id == repository_id,
                AnalysisORM.commit_sha == commit_sha,
                AnalysisORM.analyzer_version == analyzer_version,
            )
            .options(*ANALYSIS_LOAD_OPTIONS)
        )
        return result.scalar_one_or_none()

    async def create_or_get(
        self, repository_id: uuid.UUID, commit_sha: str, analyzer_version: str
    ) -> tuple[AnalysisORM, bool]:
        identifier = await self.session.scalar(
            insert(AnalysisORM)
            .values(
                id=uuid.uuid4(),
                repository_id=repository_id,
                commit_sha=commit_sha,
                analyzer_version=analyzer_version,
                status=AnalysisStatus.QUEUED.value,
            )
            .on_conflict_do_nothing(constraint="uq_analysis_identity")
            .returning(AnalysisORM.id)
        )
        if identifier is not None:
            created = await self.get(identifier)
            if created is None:  # pragma: no cover - protected by the same transaction
                raise RuntimeError("Created analysis cannot be loaded")
            return created, True
        existing = await self.get_by_identity(repository_id, commit_sha, analyzer_version)
        if existing is None:  # pragma: no cover - conflict guarantees an existing row
            raise RuntimeError("Conflicting analysis cannot be loaded")
        return existing, False

    async def get(self, analysis_id: uuid.UUID, *, loaded: bool = True) -> AnalysisORM | None:
        statement = select(AnalysisORM).where(AnalysisORM.id == analysis_id)
        if loaded:
            statement = statement.options(*ANALYSIS_LOAD_OPTIONS)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def history(self, repository_id: uuid.UUID) -> list[AnalysisORM]:
        result = await self.session.execute(
            select(AnalysisORM)
            .where(AnalysisORM.repository_id == repository_id)
            .order_by(AnalysisORM.created_at.desc())
            .options(*ANALYSIS_LOAD_OPTIONS)
        )
        return list(result.scalars().unique())

    async def mark_running(self, analysis: AnalysisORM) -> None:
        analysis.status = AnalysisStatus.RUNNING.value
        analysis.started_at = datetime.now(UTC)
        analysis.error_code = None
        analysis.error_detail = None
        await self.session.flush()

    async def complete(
        self, analysis: AnalysisORM, framework: Framework, scorecard: ScoreCard
    ) -> None:
        analysis.status = AnalysisStatus.COMPLETED.value
        analysis.framework = framework.value
        analysis.score = scorecard.score
        analysis.maturity = scorecard.maturity
        analysis.coverage = scorecard.coverage
        analysis.finished_at = datetime.now(UTC)
        analysis.categories.clear()
        analysis.checks.clear()
        for category in scorecard.categories:
            analysis.categories.append(
                CategoryResultORM(
                    category=category.category.value,
                    title=category.title,
                    score=category.score,
                    max_score=category.max_score,
                    applicable_points=category.applicable_points,
                    registry_points=category.registry_points,
                )
            )
        for outcome in scorecard.checks:
            check = CheckResultORM(
                check_id=outcome.check_id,
                version=outcome.version,
                category=outcome.category.value,
                title=outcome.title,
                status=outcome.status.value,
                points=outcome.points,
                max_points=outcome.max_points,
                explanation=outcome.explanation,
            )
            check.evidence = [
                EvidenceORM(
                    kind=item.kind,
                    path=item.path,
                    line_start=item.line_start,
                    line_end=item.line_end,
                    message=item.message,
                )
                for item in outcome.evidence
            ]
            if outcome.recommendation:
                check.recommendation = RecommendationORM(text=outcome.recommendation)
            analysis.checks.append(check)
        await self.session.flush()

    async def fail(self, analysis: AnalysisORM, code: str, detail: str) -> None:
        analysis.status = AnalysisStatus.FAILED.value
        analysis.error_code = code
        analysis.error_detail = detail[:2000]
        analysis.finished_at = datetime.now(UTC)
        await self.session.flush()
