from repo_evidence.infrastructure.db_models import AnalysisORM, CheckResultORM, RepositoryORM
from repo_evidence.presentation.schemas import (
    AnalysisResponse,
    CategoryResponse,
    CheckResponse,
    EvidenceResponse,
    ReportResponse,
    RepositoryResponse,
)


def repository_response(repository: RepositoryORM) -> RepositoryResponse:
    return RepositoryResponse(
        owner=repository.owner,
        name=repository.name,
        html_url=repository.html_url,
        default_branch=repository.default_branch,
    )


def analysis_response(analysis: AnalysisORM) -> AnalysisResponse:
    return AnalysisResponse(
        id=analysis.id,
        repository=repository_response(analysis.repository),
        commit_sha=analysis.commit_sha,
        analyzer_version=analysis.analyzer_version,
        framework=analysis.framework,
        status=analysis.status,
        score=analysis.score,
        maturity=analysis.maturity,
        coverage=analysis.coverage,
        error_code=analysis.error_code,
        error_detail=analysis.error_detail,
        created_at=analysis.created_at,
        started_at=analysis.started_at,
        finished_at=analysis.finished_at,
    )


def check_response(analysis: AnalysisORM, check: CheckResultORM) -> CheckResponse:
    base_url = f"{analysis.repository.html_url}/blob/{analysis.commit_sha}"
    evidence = []
    for item in sorted(check.evidence, key=lambda value: (value.path, value.line_start or 0)):
        anchor = ""
        if item.line_start:
            anchor = f"#L{item.line_start}"
            if item.line_end and item.line_end != item.line_start:
                anchor += f"-L{item.line_end}"
        evidence.append(
            EvidenceResponse(
                kind=item.kind,
                path=item.path,
                line_start=item.line_start,
                line_end=item.line_end,
                message=item.message,
                url=f"{base_url}/{item.path}{anchor}",
            )
        )
    return CheckResponse(
        check_id=check.check_id,
        version=check.version,
        category=check.category,
        title=check.title,
        status=check.status,
        points=check.points,
        max_points=check.max_points,
        explanation=check.explanation,
        recommendation=check.recommendation.text if check.recommendation else None,
        evidence=evidence,
    )


def report_response(analysis: AnalysisORM) -> ReportResponse:
    checks = [
        check_response(analysis, check)
        for check in sorted(analysis.checks, key=lambda value: (value.category, value.check_id))
    ]
    return ReportResponse(
        analysis=analysis_response(analysis),
        categories=[
            CategoryResponse(
                category=item.category,
                title=item.title,
                score=item.score,
                max_score=item.max_score,
                applicable_points=item.applicable_points,
                registry_points=item.registry_points,
            )
            for item in sorted(analysis.categories, key=lambda value: value.category)
        ],
        checks=checks,
        recommendations=[item for item in checks if item.recommendation],
    )
