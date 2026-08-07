import uuid
from datetime import UTC, datetime

from repo_evidence.infrastructure.db_models import (
    AnalysisORM,
    CategoryResultORM,
    CheckResultORM,
    EvidenceORM,
    RecommendationORM,
    RepositoryORM,
)
from repo_evidence.presentation.serializers import report_response


def test_report_contains_pinned_evidence_links_and_recommendations() -> None:
    repository = RepositoryORM(
        id=uuid.uuid4(),
        owner="owner",
        name="repo",
        html_url="https://github.com/owner/repo",
        default_branch="main",
    )
    analysis = AnalysisORM(
        id=uuid.uuid4(),
        repository_id=repository.id,
        repository=repository,
        commit_sha="a" * 40,
        analyzer_version="1.0.0",
        framework="fastapi",
        status="completed",
        score=75,
        maturity="Сильный",
        coverage=100,
        created_at=datetime.now(UTC),
    )
    analysis.categories = [
        CategoryResultORM(
            category="architecture",
            title="Архитектура",
            score=15,
            max_score=20,
            applicable_points=20,
            registry_points=20,
        )
    ]
    check = CheckResultORM(
        check_id="architecture.layers",
        version="1.0",
        category="architecture",
        title="Слои",
        status="partial",
        points=3,
        max_points=6,
        explanation="Найдена часть слоёв.",
    )
    check.evidence = [EvidenceORM(kind="source", path="src/app.py", line_start=4, line_end=5)]
    check.recommendation = RecommendationORM(text="Разделите слои.")
    analysis.checks = [check]
    report = report_response(analysis)
    assert report.analysis.score == 75
    assert report.recommendations[0].recommendation == "Разделите слои."
    assert report.checks[0].evidence[0].url.endswith("/src/app.py#L4-L5")
