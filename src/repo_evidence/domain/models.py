from dataclasses import dataclass, field
from enum import StrEnum


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CheckStatus(StrEnum):
    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class Framework(StrEnum):
    FASTAPI = "fastapi"
    DJANGO = "django"
    FLASK = "flask"
    GENERIC = "generic"


class Category(StrEnum):
    ARCHITECTURE = "architecture"
    TESTING = "testing"
    CODE_QUALITY = "code_quality"
    SECURITY = "security"
    DELIVERY = "delivery"
    DOCUMENTATION = "documentation"
    OBSERVABILITY = "observability"


CATEGORY_WEIGHTS: dict[Category, float] = {
    Category.ARCHITECTURE: 20.0,
    Category.TESTING: 20.0,
    Category.CODE_QUALITY: 15.0,
    Category.SECURITY: 15.0,
    Category.DELIVERY: 15.0,
    Category.DOCUMENTATION: 10.0,
    Category.OBSERVABILITY: 5.0,
}

CATEGORY_TITLES: dict[Category, str] = {
    Category.ARCHITECTURE: "Архитектура",
    Category.TESTING: "Тестирование",
    Category.CODE_QUALITY: "Качество кода",
    Category.SECURITY: "Безопасность",
    Category.DELIVERY: "Доставка",
    Category.DOCUMENTATION: "Документация",
    Category.OBSERVABILITY: "Наблюдаемость",
}


@dataclass(slots=True, frozen=True)
class Evidence:
    kind: str
    path: str
    line_start: int | None = None
    line_end: int | None = None
    message: str | None = None


@dataclass(slots=True, frozen=True)
class CheckOutcome:
    check_id: str
    version: str
    category: Category
    title: str
    status: CheckStatus
    points: float
    max_points: float
    explanation: str
    recommendation: str | None = None
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)


@dataclass(slots=True, frozen=True)
class CategoryScore:
    category: Category
    title: str
    score: float
    max_score: float
    applicable_points: float
    registry_points: float


@dataclass(slots=True, frozen=True)
class ScoreCard:
    score: float | None
    maturity: str | None
    coverage: float
    categories: tuple[CategoryScore, ...]
    checks: tuple[CheckOutcome, ...]


def maturity_for(score: float) -> str:
    if score < 40:
        return "Начальный"
    if score < 60:
        return "Развивающийся"
    if score < 75:
        return "Устойчивый"
    if score < 90:
        return "Сильный"
    return "Образцовый"
