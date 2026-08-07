from hypothesis import given
from hypothesis import strategies as st

from repo_evidence.analysis.scoring import build_scorecard
from repo_evidence.domain.models import Category, CheckOutcome, CheckStatus, maturity_for


def outcome(
    check_id: str,
    category: Category,
    points: float,
    maximum: float,
    status: CheckStatus,
) -> CheckOutcome:
    return CheckOutcome(check_id, "1.0", category, check_id, status, points, maximum, "result")


def test_normalizes_category_after_not_applicable() -> None:
    card = build_scorecard(
        [
            outcome("a", Category.ARCHITECTURE, 5, 5, CheckStatus.PASSED),
            outcome("b", Category.ARCHITECTURE, 0, 5, CheckStatus.NOT_APPLICABLE),
        ]
    )
    architecture = next(item for item in card.categories if item.category is Category.ARCHITECTURE)
    assert architecture.score == 20
    assert card.coverage == 50
    assert card.score is None


def test_full_registry_produces_score_and_maturity() -> None:
    checks = [
        outcome(category.value, category, maximum, maximum, CheckStatus.PASSED)
        for category, maximum in {
            Category.ARCHITECTURE: 20,
            Category.TESTING: 20,
            Category.CODE_QUALITY: 15,
            Category.SECURITY: 15,
            Category.DELIVERY: 15,
            Category.DOCUMENTATION: 10,
            Category.OBSERVABILITY: 5,
        }.items()
    ]
    card = build_scorecard(checks)
    assert card.score == 100
    assert card.coverage == 100
    assert card.maturity == "Образцовый"


@given(st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False))
def test_maturity_is_total(score: float) -> None:
    assert maturity_for(score) in {
        "Начальный",
        "Развивающийся",
        "Устойчивый",
        "Сильный",
        "Образцовый",
    }
