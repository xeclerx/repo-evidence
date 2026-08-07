import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from repo_evidence.domain.models import AnalysisStatus
from repo_evidence.infrastructure.db_models import Base
from repo_evidence.infrastructure.github import GitHubRepository, RepositoryRef
from repo_evidence.infrastructure.repositories import AnalysisStore, RepositoryStore


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repository_and_analysis_history() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    unique = uuid.uuid4().hex[:8]
    async with factory() as session:
        repository = await RepositoryStore(session).upsert(
            GitHubRepository(RepositoryRef(f"owner-{unique}", "repo"), "main", "a" * 40)
        )
        analysis, created = await AnalysisStore(session).create_or_get(
            repository.id, "a" * 40, "1.0.0"
        )
        await session.commit()
        assert created is True
        assert analysis.status == AnalysisStatus.QUEUED.value
        same, created_again = await AnalysisStore(session).create_or_get(
            repository.id, "a" * 40, "1.0.0"
        )
        assert same.id == analysis.id
        assert created_again is False
        history = await AnalysisStore(session).history(repository.id)
        assert [item.id for item in history] == [analysis.id]
    await engine.dispose()
