import shutil
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from repo_evidence.application.analysis_service import AnalysisService
from repo_evidence.application.errors import UnsupportedProject
from repo_evidence.config import Settings
from repo_evidence.infrastructure.github import GitHubRepository, RepositoryRef


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeGitHub:
    def __init__(self, source: Path | None = None) -> None:
        self.source = source

    async def resolve(self, ref: RepositoryRef) -> GitHubRepository:
        return GitHubRepository(ref, "main", "a" * 40)

    async def download_and_extract(
        self, repository: GitHubRepository
    ) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        target = Path(temporary.name) / "source"
        if self.source:
            shutil.copytree(self.source, target)
        else:
            target.mkdir()
        return temporary


class FakeRepositories:
    repository = SimpleNamespace(id=uuid.uuid4())

    async def upsert(self, github: GitHubRepository) -> Any:
        return self.repository


class FakeAnalyses:
    def __init__(self, analysis: Any | None = None) -> None:
        self.analysis = analysis
        self.completed = None
        self.failed = None

    async def get_by_identity(self, *args: object) -> Any | None:
        return self.analysis

    async def create_or_get(self, *args: object) -> tuple[Any, bool]:
        self.analysis = SimpleNamespace(id=uuid.uuid4(), status="queued")
        return self.analysis, True

    async def get(self, analysis_id: uuid.UUID, *, loaded: bool = True) -> Any | None:
        return self.analysis

    async def mark_running(self, analysis: Any) -> None:
        analysis.status = "running"

    async def complete(self, analysis: Any, framework: Any, scorecard: Any) -> None:
        self.completed = (framework, scorecard)

    async def fail(self, analysis: Any, code: str, detail: str) -> None:
        self.failed = (code, detail)


class FakeCelery:
    def __init__(self) -> None:
        self.sent: list[tuple[str, list[str]]] = []

    def send_task(self, name: str, args: list[str]) -> None:
        self.sent.append((name, args))


def make_service(
    github: FakeGitHub, analysis: Any | None = None
) -> tuple[AnalysisService, FakeSession, FakeAnalyses, FakeCelery]:
    session = FakeSession()
    celery = FakeCelery()
    service = AnalysisService(
        cast(AsyncSession, session), Settings(), cast(Any, github), cast(Any, celery)
    )
    analyses = FakeAnalyses(analysis)
    service.repositories = cast(Any, FakeRepositories())
    service.analyses = cast(Any, analyses)
    return service, session, analyses, celery


@pytest.mark.asyncio
async def test_request_creates_and_dispatches_analysis() -> None:
    service, session, analyses, celery = make_service(FakeGitHub())
    result = await service.request("https://github.com/owner/repo")
    assert result.cached is False
    assert result.status == "queued"
    assert celery.sent == [("repo_evidence.run_analysis", [str(analyses.analysis.id)])]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_request_returns_cached_analysis() -> None:
    existing = SimpleNamespace(id=uuid.uuid4(), status="completed")
    service, _, _, celery = make_service(FakeGitHub(), existing)
    result = await service.request("https://github.com/owner/repo")
    assert result.cached is True
    assert result.analysis_id == existing.id
    assert celery.sent == []


@pytest.mark.asyncio
async def test_execute_builds_and_saves_scorecard(fastapi_project: Path) -> None:
    analysis = SimpleNamespace(
        id=uuid.uuid4(),
        status="queued",
        commit_sha="a" * 40,
        repository=SimpleNamespace(html_url="https://github.com/owner/repo"),
    )
    service, session, analyses, _ = make_service(FakeGitHub(fastapi_project), analysis)
    await service.execute(analysis.id)
    assert analyses.completed is not None
    framework, scorecard = analyses.completed
    assert framework.value == "fastapi"
    assert scorecard.score is not None
    assert session.commits == 2


@pytest.mark.asyncio
async def test_execute_records_expected_failure() -> None:
    analysis = SimpleNamespace(
        id=uuid.uuid4(),
        status="queued",
        commit_sha="a" * 40,
        repository=SimpleNamespace(html_url="https://github.com/owner/repo"),
    )
    service, session, analyses, _ = make_service(FakeGitHub(), analysis)
    with pytest.raises(UnsupportedProject):
        await service.execute(analysis.id)
    assert analyses.failed and analyses.failed[0] == "unsupported_project"
    assert session.rollbacks == 1
