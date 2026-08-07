import uuid
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from repo_evidence.application.errors import IncompatibleAnalysisVersions
from repo_evidence.infrastructure.db_models import (
    AnalysisORM,
    CategoryResultORM,
    CheckResultORM,
    RepositoryORM,
)
from repo_evidence.presentation import api


def analysis_with_score(
    repository: RepositoryORM,
    score: float,
    check_status: str,
    check_points: float,
    *,
    version: str = "1.0.0",
) -> AnalysisORM:
    analysis = AnalysisORM(
        id=uuid.uuid4(),
        repository_id=repository.id,
        repository=repository,
        commit_sha=uuid.uuid4().hex + "abcd1234",
        analyzer_version=version,
        framework="fastapi",
        status="completed",
        score=score,
        maturity="Устойчивый",
        coverage=100,
        created_at=datetime.now(UTC),
    )
    analysis.categories = [
        CategoryResultORM(
            category="architecture",
            title="Архитектура",
            score=score / 5,
            max_score=20,
            applicable_points=20,
            registry_points=20,
        )
    ]
    analysis.checks = [
        CheckResultORM(
            check_id="architecture.layers",
            version="1.0",
            category="architecture",
            title="Слои",
            status=check_status,
            points=check_points,
            max_points=6,
            explanation="Результат.",
        )
    ]
    return analysis


@pytest.mark.asyncio
async def test_comparison_reports_improvement(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = RepositoryORM(
        id=uuid.uuid4(),
        owner="owner",
        name="repo",
        html_url="https://github.com/owner/repo",
        default_branch="main",
    )
    base = analysis_with_score(repository, 60, "partial", 3)
    head = analysis_with_score(repository, 75, "passed", 6)
    items = {base.id: base, head.id: head}

    class FakeStore:
        def __init__(self, session: object) -> None:
            pass

        async def get(self, identifier: uuid.UUID) -> AnalysisORM | None:
            return items.get(identifier)

    monkeypatch.setattr(api, "AnalysisStore", FakeStore)
    result = await api.compare_analyses(
        base=base.id, head=head.id, session=cast(AsyncSession, object())
    )
    assert result.score_delta == 15
    assert result.improved[0].check_id == "architecture.layers"
    assert result.category_deltas["architecture"] == 3


@pytest.mark.asyncio
async def test_comparison_rejects_different_analyzer_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = RepositoryORM(
        id=uuid.uuid4(),
        owner="owner",
        name="repo",
        html_url="https://github.com/owner/repo",
        default_branch="main",
    )
    base = analysis_with_score(repository, 60, "partial", 3)
    head = analysis_with_score(repository, 75, "passed", 6, version="2.0.0")
    items = {base.id: base, head.id: head}

    class FakeStore:
        def __init__(self, session: object) -> None:
            pass

        async def get(self, identifier: uuid.UUID) -> AnalysisORM | None:
            return items.get(identifier)

    monkeypatch.setattr(api, "AnalysisStore", FakeStore)
    with pytest.raises(IncompatibleAnalysisVersions):
        await api.compare_analyses(base=base.id, head=head.id, session=cast(AsyncSession, object()))
