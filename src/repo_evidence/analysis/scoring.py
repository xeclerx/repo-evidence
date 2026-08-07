from collections import defaultdict

from repo_evidence.domain.models import (
    CATEGORY_TITLES,
    CATEGORY_WEIGHTS,
    Category,
    CategoryScore,
    CheckOutcome,
    CheckStatus,
    ScoreCard,
    maturity_for,
)


def build_scorecard(checks: list[CheckOutcome]) -> ScoreCard:
    grouped: dict[Category, list[CheckOutcome]] = defaultdict(list)
    for check in checks:
        grouped[check.category].append(check)

    categories: list[CategoryScore] = []
    total_registry = sum(check.max_points for check in checks)
    total_applicable = sum(
        check.max_points for check in checks if check.status is not CheckStatus.NOT_APPLICABLE
    )
    for category, category_weight in CATEGORY_WEIGHTS.items():
        category_checks = grouped[category]
        registry_points = sum(check.max_points for check in category_checks)
        applicable = [
            check for check in category_checks if check.status is not CheckStatus.NOT_APPLICABLE
        ]
        applicable_points = sum(check.max_points for check in applicable)
        earned = sum(check.points for check in applicable)
        normalized = category_weight * earned / applicable_points if applicable_points else 0.0
        categories.append(
            CategoryScore(
                category=category,
                title=CATEGORY_TITLES[category],
                score=round(normalized, 2),
                max_score=category_weight,
                applicable_points=applicable_points,
                registry_points=registry_points,
            )
        )
    coverage = 100 * total_applicable / total_registry if total_registry else 0.0
    raw_score = round(sum(category.score for category in categories), 2)
    score = raw_score if coverage >= 60 else None
    return ScoreCard(
        score=score,
        maturity=maturity_for(score) if score is not None else None,
        coverage=round(coverage, 2),
        categories=tuple(categories),
        checks=tuple(checks),
    )
