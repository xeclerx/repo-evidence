from pathlib import Path

from repo_evidence.analysis.context import AnalysisContext
from repo_evidence.analysis.rules import default_rules, run_rules
from repo_evidence.domain.models import CATEGORY_WEIGHTS, Category, CheckStatus


def test_registry_has_unique_stable_ids_and_expected_weights() -> None:
    rules = default_rules()
    assert len({rule.id for rule in rules}) == len(rules)
    for category in Category:
        assert (
            sum(rule.points for rule in rules if rule.category is category)
            == CATEGORY_WEIGHTS[category]
        )


def test_all_rules_are_deterministic(fastapi_project: Path) -> None:
    context = AnalysisContext.build(fastapi_project, 2 * 1024 * 1024)
    assert run_rules(context) == run_rules(context)
    assert all(outcome.version == "1.0" for outcome in run_rules(context))


def test_strong_fixture_passes_core_checks(fastapi_project: Path) -> None:
    outcomes = {
        item.check_id: item for item in run_rules(AnalysisContext.build(fastapi_project, 2_000_000))
    }
    expected = {
        "architecture.src-layout",
        "architecture.entrypoint",
        "architecture.domain-independence",
        "testing.suite",
        "testing.functions",
        "quality.pyproject",
        "security.secrets",
        "delivery.dockerfile",
        "delivery.nonroot",
        "delivery.ci",
        "docs.readme",
        "observability.logging",
    }
    assert all(outcomes[check_id].status is CheckStatus.PASSED for check_id in expected)


def test_detects_security_and_domain_violations(fastapi_project: Path) -> None:
    (fastapi_project / "src/app/domain/order.py").write_text(
        "from sqlalchemy import String\nAPI_KEY = 'secret-value-123'\n", encoding="utf-8"
    )
    outcomes = {
        item.check_id: item for item in run_rules(AnalysisContext.build(fastapi_project, 2_000_000))
    }
    assert outcomes["architecture.domain-independence"].status is CheckStatus.FAILED
    assert outcomes["security.secrets"].status is CheckStatus.FAILED
    assert outcomes["security.secrets"].evidence[0].line_start == 2
