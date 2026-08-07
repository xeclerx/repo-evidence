import uuid
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class AnalysisCreate(BaseModel):
    repository_url: HttpUrl


class AnalysisRequestResponse(BaseModel):
    analysis_id: uuid.UUID
    status: str
    cached: bool
    status_url: str
    report_url: str


class RepositoryResponse(BaseModel):
    owner: str
    name: str
    html_url: str
    default_branch: str


class AnalysisResponse(BaseModel):
    id: uuid.UUID
    repository: RepositoryResponse
    commit_sha: str
    analyzer_version: str
    framework: str | None
    status: str
    score: float | None
    maturity: str | None
    coverage: float | None
    error_code: str | None
    error_detail: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class EvidenceResponse(BaseModel):
    kind: str
    path: str
    line_start: int | None
    line_end: int | None
    message: str | None
    url: str


class CheckResponse(BaseModel):
    check_id: str
    version: str
    category: str
    title: str
    status: str
    points: float
    max_points: float
    explanation: str
    recommendation: str | None
    evidence: list[EvidenceResponse]


class CategoryResponse(BaseModel):
    category: str
    title: str
    score: float
    max_score: float
    applicable_points: float
    registry_points: float


class ReportResponse(BaseModel):
    analysis: AnalysisResponse
    categories: list[CategoryResponse]
    checks: list[CheckResponse]
    recommendations: list[CheckResponse]


class HistoryResponse(BaseModel):
    repository: RepositoryResponse
    analyses: list[AnalysisResponse]


class CheckChange(BaseModel):
    check_id: str
    title: str
    before_status: str
    after_status: str
    points_delta: float


class ComparisonResponse(BaseModel):
    base: AnalysisResponse
    head: AnalysisResponse
    score_delta: float | None
    category_deltas: dict[str, float]
    improved: list[CheckChange]
    regressed: list[CheckChange]
    unchanged_count: int = Field(ge=0)
