import ast
import re
from collections.abc import Callable
from dataclasses import dataclass

from repo_evidence.analysis.context import AnalysisContext
from repo_evidence.domain.models import Category, CheckOutcome, CheckStatus, Evidence, Framework


@dataclass(slots=True, frozen=True)
class Evaluation:
    fraction: float | None
    explanation: str
    evidence: tuple[Evidence, ...] = ()


Evaluator = Callable[[AnalysisContext], Evaluation]


@dataclass(slots=True, frozen=True)
class Rule:
    id: str
    category: Category
    title: str
    points: float
    recommendation: str
    evaluate: Evaluator
    version: str = "1.0"

    def run(self, context: AnalysisContext) -> CheckOutcome:
        result = self.evaluate(context)
        if result.fraction is None:
            status = CheckStatus.NOT_APPLICABLE
            awarded = 0.0
        else:
            fraction = max(0.0, min(1.0, result.fraction))
            awarded = round(self.points * fraction, 2)
            status = (
                CheckStatus.PASSED
                if fraction >= 1.0
                else CheckStatus.PARTIAL
                if fraction > 0
                else CheckStatus.FAILED
            )
        return CheckOutcome(
            check_id=self.id,
            version=self.version,
            category=self.category,
            title=self.title,
            status=status,
            points=awarded,
            max_points=self.points,
            explanation=result.explanation,
            recommendation=None if status is CheckStatus.PASSED else self.recommendation,
            evidence=result.evidence[:8],
        )


def _path_evidence(paths: list[str], message: str | None = None) -> tuple[Evidence, ...]:
    return tuple(Evidence("file", path, message=message) for path in paths[:8])


def _exists(context: AnalysisContext, pattern: str, success: str, failure: str) -> Evaluation:
    paths = context.paths(pattern)
    return Evaluation(1.0 if paths else 0.0, success if paths else failure, _path_evidence(paths))


def _contains(context: AnalysisContext, pattern: str, success: str, failure: str) -> Evaluation:
    evidence = tuple(context.containing(pattern))
    return Evaluation(1.0 if evidence else 0.0, success if evidence else failure, evidence[:8])


def _src_layout(context: AnalysisContext) -> Evaluation:
    src = [path for path in context.files if path.startswith("src/") and path.endswith(".py")]
    packages = [
        path for path in context.files if path.count("/") == 1 and path.endswith("/__init__.py")
    ]
    evidence = _path_evidence(src[:1] or packages[:1])
    return Evaluation(
        1.0 if src else 0.5 if packages else 0.0, "Определена структура Python-пакета.", evidence
    )


def _entrypoint(context: AnalysisContext) -> Evaluation:
    patterns = {
        Framework.FASTAPI: r"\bFastAPI\s*\(",
        Framework.DJANGO: r"(DJANGO_SETTINGS_MODULE|urlpatterns\s*=)",
        Framework.FLASK: r"\bFlask\s*\(",
        Framework.GENERIC: r"\b(ASGI|WSGI|application\s*=|app\s*=)",
    }
    evidence = tuple(context.containing(patterns[context.framework], python_only=True))
    return Evaluation(
        1.0 if evidence else 0.0, "Найдена точка входа backend-приложения.", evidence[:8]
    )


def _layers(context: AnalysisContext) -> Evaluation:
    groups = [
        r"(^|/)(domain|models?)/",
        r"(^|/)(application|services?|use_cases?)/",
        r"(^|/)(infrastructure|repositories|adapters?)/",
        r"(^|/)(presentation|api|routes?|views?)/",
    ]
    matches = [next(iter(context.paths(pattern)), None) for pattern in groups]
    found = [path for path in matches if path]
    return Evaluation(
        min(1.0, len(found) / 3),
        f"Обнаружено архитектурных границ: {len(found)} из рекомендуемых 4.",
        _path_evidence(found),
    )


def _domain_imports(context: AnalysisContext) -> Evaluation:
    domain = [source for source in context.python_files if re.search(r"(^|/)domain/", source.path)]
    if not domain:
        return Evaluation(None, "Отдельный domain-слой не обнаружен.")
    forbidden = re.compile(r"^\s*(from|import)\s+(fastapi|django|flask|sqlalchemy)", re.MULTILINE)
    bad: list[Evidence] = []
    for source in domain:
        match = forbidden.search(source.text)
        if match:
            line = source.text.count("\n", 0, match.start()) + 1
            bad.append(Evidence("source", source.path, line, line))
    return Evaluation(
        0.0 if bad else 1.0, "Проверено направление зависимостей domain-слоя.", tuple(bad)
    )


def _layered_config(context: AnalysisContext) -> Evaluation:
    evidence = tuple(
        context.containing(
            r"(BaseSettings|pydantic_settings|os\.getenv|environ\[)", python_only=True
        )
    )
    config_paths = context.paths(r"(^|/)(config|settings)(\.py|/)")
    fraction = 1.0 if evidence and config_paths else 0.5 if evidence or config_paths else 0.0
    return Evaluation(
        fraction,
        "Проверена изоляция конфигурации приложения.",
        (*evidence[:4], *_path_evidence(config_paths[:4])),
    )


def _test_functions(context: AnalysisContext) -> Evaluation:
    count = 0
    evidence: list[Evidence] = []
    for source in context.python_files:
        if not re.search(r"(^|/)(tests?|test_)|_test\.py$", source.path):
            continue
        if source.tree:
            for node in ast.walk(source.tree):
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and node.name.startswith("test_"):
                    count += 1
                    evidence.append(Evidence("source", source.path, node.lineno, node.end_lineno))
    fraction = 1.0 if count >= 5 else 0.5 if count else 0.0
    return Evaluation(fraction, f"Найдено тестовых функций: {count}.", tuple(evidence[:8]))


def _async_tests(context: AnalysisContext) -> Evaluation:
    if context.framework is not Framework.FASTAPI:
        return Evaluation(None, "Async-проверка не обязательна для этого профиля.")
    evidence = tuple(
        context.containing(
            r"(@pytest\.mark\.(asyncio|anyio)|async\s+def\s+test_)", python_only=True
        )
    )
    return Evaluation(1.0 if evidence else 0.0, "Проверена поддержка async-тестов.", evidence[:8])


def _annotations(context: AnalysisContext) -> Evaluation:
    functions = 0
    annotated = 0
    evidence: list[Evidence] = []
    for source in context.python_files:
        if "/test" in source.path or source.path.startswith("test"):
            continue
        if source.tree:
            for node in ast.walk(source.tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions += 1
                    if node.returns is not None:
                        annotated += 1
                        evidence.append(Evidence("source", source.path, node.lineno, node.lineno))
    ratio = annotated / functions if functions else 0.0
    fraction = 1.0 if ratio >= 0.7 else 0.5 if ratio >= 0.3 else 0.0
    return Evaluation(
        fraction,
        f"Аннотация возвращаемого типа: {annotated} из {functions} функций.",
        tuple(evidence[:8]),
    )


def _broad_exceptions(context: AnalysisContext) -> Evaluation:
    bad: list[Evidence] = []
    for source in context.python_files:
        if source.tree:
            for node in ast.walk(source.tree):
                if isinstance(node, ast.ExceptHandler) and (
                    node.type is None
                    or (
                        isinstance(node.type, ast.Name)
                        and node.type.id in {"Exception", "BaseException"}
                    )
                ):
                    bad.append(Evidence("source", source.path, node.lineno, node.end_lineno))
    fraction = 1.0 if not bad else 0.5 if len(bad) <= 2 else 0.0
    return Evaluation(fraction, f"Широких обработчиков исключений: {len(bad)}.", tuple(bad[:8]))


def _secrets(context: AnalysisContext) -> Evaluation:
    pattern = re.compile(r"(?im)^\s*(api[_-]?key|secret|token|password)\s*=\s*['\"][^'\"]{8,}['\"]")
    bad: list[Evidence] = []
    for source in context.files.values():
        if source.path.endswith((".md", ".example")) or "/test" in source.path:
            continue
        match = pattern.search(source.text)
        if match:
            line = source.text.count("\n", 0, match.start()) + 1
            bad.append(Evidence("source", source.path, line, line, "Возможный секрет"))
    return Evaluation(
        1.0 if not bad else 0.0, f"Потенциальных встроенных секретов: {len(bad)}.", tuple(bad[:8])
    )


def _unsafe_calls(context: AnalysisContext) -> Evaluation:
    bad: list[Evidence] = []
    dangerous = {"eval", "exec"}
    for source in context.python_files:
        if source.tree:
            for node in ast.walk(source.tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id in dangerous:
                        bad.append(Evidence("source", source.path, node.lineno, node.end_lineno))
                    if isinstance(node.func, ast.Attribute) and node.func.attr in {
                        "Popen",
                        "run",
                        "call",
                    }:
                        for keyword in node.keywords:
                            if (
                                keyword.arg == "shell"
                                and isinstance(keyword.value, ast.Constant)
                                and keyword.value.value is True
                            ):
                                bad.append(
                                    Evidence("source", source.path, node.lineno, node.end_lineno)
                                )
    return Evaluation(1.0 if not bad else 0.0, f"Опасных вызовов: {len(bad)}.", tuple(bad[:8]))


def _nonroot(context: AnalysisContext) -> Evaluation:
    dockerfiles = context.paths(r"(^|/)Dockerfile$")
    if not dockerfiles:
        return Evaluation(None, "Dockerfile отсутствует.")
    evidence = tuple(context.containing(r"^USER\s+(?!root\b)\S+"))
    return Evaluation(
        1.0 if evidence else 0.0, "Проверен непривилегированный пользователь контейнера.", evidence
    )


def _migrations(context: AnalysisContext) -> Evaluation:
    db_signal = context.containing(r"\b(sqlalchemy|django\.db|alembic|asyncpg|psycopg)\b")
    if not db_signal:
        return Evaluation(None, "Признаки реляционной БД не обнаружены.")
    paths = context.paths(r"(^|/)(alembic|migrations?)/")
    return Evaluation(
        1.0 if paths else 0.0, "Проверено наличие миграций БД.", _path_evidence(paths)
    )


def _license_contributing(context: AnalysisContext) -> Evaluation:
    license_paths = context.paths(r"(^|/)(LICENSE|COPYING)(\.|$)")
    contributing = context.paths(r"(^|/)CONTRIBUTING\.md$")
    fraction = (bool(license_paths) + bool(contributing)) / 2
    return Evaluation(
        fraction,
        "Проверены лицензия и руководство для участников.",
        _path_evidence(license_paths + contributing),
    )


def default_rules() -> tuple[Rule, ...]:
    return (
        Rule(
            "architecture.src-layout",
            Category.ARCHITECTURE,
            "Структура Python-пакета",
            3,
            "Используйте src-layout или явный пакет приложения.",
            _src_layout,
        ),
        Rule(
            "architecture.entrypoint",
            Category.ARCHITECTURE,
            "Точка входа",
            3,
            "Добавьте явную точку входа backend-приложения.",
            _entrypoint,
        ),
        Rule(
            "architecture.layers",
            Category.ARCHITECTURE,
            "Архитектурные границы",
            6,
            "Разделите API, сценарии приложения, домен и инфраструктуру.",
            _layers,
        ),
        Rule(
            "architecture.domain-independence",
            Category.ARCHITECTURE,
            "Независимость domain",
            5,
            "Уберите зависимости web/ORM-фреймворков из domain-слоя.",
            _domain_imports,
        ),
        Rule(
            "architecture.config",
            Category.ARCHITECTURE,
            "Изоляция конфигурации",
            3,
            "Соберите environment-настройки в отдельном модуле.",
            _layered_config,
        ),
        Rule(
            "testing.suite",
            Category.TESTING,
            "Тестовая структура",
            4,
            "Добавьте каталог tests и базовые сценарии.",
            lambda c: _exists(
                c,
                r"(^|/)tests?(/|$)|(^|/)test_.*\.py$",
                "Тестовые файлы найдены.",
                "Тестовые файлы не найдены.",
            ),
        ),
        Rule(
            "testing.pytest-config",
            Category.TESTING,
            "Конфигурация pytest",
            3,
            "Зафиксируйте настройки pytest в pyproject.toml или pytest.ini.",
            lambda c: _contains(
                c,
                r"(\[tool\.pytest|\[pytest\])",
                "Конфигурация pytest найдена.",
                "Конфигурация pytest не найдена.",
            ),
        ),
        Rule(
            "testing.functions",
            Category.TESTING,
            "Набор тестов",
            4,
            "Добавьте не менее пяти содержательных test-функций.",
            _test_functions,
        ),
        Rule(
            "testing.fixtures",
            Category.TESTING,
            "Fixtures и изоляция",
            3,
            "Используйте pytest fixtures для подготовки зависимостей.",
            lambda c: _contains(
                c,
                r"(@pytest\.fixture|\bfixture\s*\()",
                "Fixtures найдены.",
                "Pytest fixtures не найдены.",
            ),
        ),
        Rule(
            "testing.async",
            Category.TESTING,
            "Async-тесты",
            3,
            "Покройте асинхронные сценарии через pytest-anyio или pytest-asyncio.",
            _async_tests,
        ),
        Rule(
            "testing.integration",
            Category.TESTING,
            "Интеграционные тесты",
            3,
            "Выделите интеграционные тесты или соответствующий marker.",
            lambda c: _exists(
                c,
                r"(^|/)(integration|e2e)(/|_)|test_.*integration",
                "Интеграционные тесты найдены.",
                "Интеграционные тесты не выделены.",
            ),
        ),
        Rule(
            "quality.pyproject",
            Category.CODE_QUALITY,
            "Единая конфигурация проекта",
            3,
            "Добавьте pyproject.toml.",
            lambda c: _exists(
                c, r"^pyproject\.toml$", "pyproject.toml найден.", "pyproject.toml не найден."
            ),
        ),
        Rule(
            "quality.linter",
            Category.CODE_QUALITY,
            "Линтер",
            3,
            "Настройте Ruff, Flake8 или Pylint.",
            lambda c: _contains(
                c,
                r"(\[tool\.ruff|\bflake8\b|\bpylint\b)",
                "Конфигурация линтера найдена.",
                "Линтер не настроен.",
            ),
        ),
        Rule(
            "quality.types",
            Category.CODE_QUALITY,
            "Статическая типизация",
            3,
            "Настройте mypy или Pyright.",
            lambda c: _contains(
                c,
                r"(\[tool\.mypy|\bpyright\b)",
                "Type checker найден.",
                "Type checker не настроен.",
            ),
        ),
        Rule(
            "quality.annotations",
            Category.CODE_QUALITY,
            "Аннотации типов",
            4,
            "Добавьте возвращаемые типы публичным функциям.",
            _annotations,
        ),
        Rule(
            "quality.exceptions",
            Category.CODE_QUALITY,
            "Обработка исключений",
            2,
            "Замените широкие except на конкретные типы исключений.",
            _broad_exceptions,
        ),
        Rule(
            "security.secrets",
            Category.SECURITY,
            "Секреты в коде",
            4,
            "Перенесите секреты в переменные окружения и отзовите найденные значения.",
            _secrets,
        ),
        Rule(
            "security.environment",
            Category.SECURITY,
            "Environment-конфигурация",
            3,
            "Получайте чувствительные настройки из environment.",
            lambda c: _contains(
                c,
                r"(BaseSettings|pydantic_settings|os\.getenv|environ\[)",
                "Environment-конфигурация найдена.",
                "Environment-конфигурация не найдена.",
            ),
        ),
        Rule(
            "security.gitignore-env",
            Category.SECURITY,
            "Исключение .env",
            2,
            "Добавьте .env в .gitignore и оставьте безопасный .env.example.",
            lambda c: _contains(
                c, r"(?m)^\.env$", ".env исключён из Git.", ".env не найден в .gitignore."
            ),
        ),
        Rule(
            "security.lock",
            Category.SECURITY,
            "Фиксация зависимостей",
            2,
            "Добавьте lock-файл или закрепите версии зависимостей.",
            lambda c: _exists(
                c,
                r"(^|/)(uv\.lock|poetry\.lock|Pipfile\.lock|requirements.*\.txt)$",
                "Фиксация зависимостей найдена.",
                "Lock-файл не найден.",
            ),
        ),
        Rule(
            "security.unsafe-calls",
            Category.SECURITY,
            "Опасные вызовы",
            2,
            "Уберите eval/exec и subprocess с shell=True.",
            _unsafe_calls,
        ),
        Rule(
            "security.production-flags",
            Category.SECURITY,
            "Production-настройки",
            2,
            "Не включайте DEBUG и wildcard CORS без environment-ограничений.",
            lambda c: (
                Evaluation(
                    0.0,
                    "Найдены потенциально опасные production-настройки.",
                    tuple(
                        c.containing(
                            r"(DEBUG\s*=\s*True|allow_origins\s*=\s*\[?['\"]\*['\"])",
                            python_only=True,
                        )
                    ),
                )
                if c.containing(
                    r"(DEBUG\s*=\s*True|allow_origins\s*=\s*\[?['\"]\*['\"])", python_only=True
                )
                else Evaluation(1.0, "Явные опасные production-настройки не найдены.")
            ),
        ),
        Rule(
            "delivery.dockerfile",
            Category.DELIVERY,
            "Dockerfile",
            3,
            "Добавьте воспроизводимый Dockerfile.",
            lambda c: _exists(
                c, r"(^|/)Dockerfile$", "Dockerfile найден.", "Dockerfile не найден."
            ),
        ),
        Rule(
            "delivery.nonroot",
            Category.DELIVERY,
            "Непривилегированный контейнер",
            2,
            "Запускайте приложение в контейнере не от root.",
            _nonroot,
        ),
        Rule(
            "delivery.healthcheck",
            Category.DELIVERY,
            "Healthcheck",
            2,
            "Добавьте healthcheck контейнера и приложения.",
            lambda c: _contains(
                c,
                r"(HEALTHCHECK|/health|health_check)",
                "Healthcheck найден.",
                "Healthcheck не найден.",
            ),
        ),
        Rule(
            "delivery.compose",
            Category.DELIVERY,
            "Docker Compose",
            2,
            "Добавьте compose-файл для локального окружения.",
            lambda c: _exists(
                c,
                r"(^|/)(docker-)?compose(\.[^.]+)?\.ya?ml$",
                "Compose-файл найден.",
                "Compose-файл не найден.",
            ),
        ),
        Rule(
            "delivery.ci",
            Category.DELIVERY,
            "Continuous Integration",
            3,
            "Добавьте GitHub Actions или другой CI.",
            lambda c: _exists(
                c,
                r"^\.github/workflows/.*\.ya?ml$|(^|/)\.gitlab-ci\.yml$",
                "CI-конфигурация найдена.",
                "CI-конфигурация не найдена.",
            ),
        ),
        Rule(
            "delivery.migrations",
            Category.DELIVERY,
            "Миграции БД",
            3,
            "Добавьте версионируемые миграции схемы БД.",
            _migrations,
        ),
        Rule(
            "docs.readme",
            Category.DOCUMENTATION,
            "README",
            3,
            "Добавьте README с назначением проекта.",
            lambda c: _exists(c, r"(^|/)README(\.[^.]+)?$", "README найден.", "README не найден."),
        ),
        Rule(
            "docs.run",
            Category.DOCUMENTATION,
            "Инструкция запуска",
            3,
            "Опишите установку и локальный запуск.",
            lambda c: _contains(
                c,
                r"(?i)(установ|запуск|install|getting started|quickstart|docker compose up)",
                "Инструкция запуска найдена.",
                "Инструкция запуска не найдена.",
            ),
        ),
        Rule(
            "docs.api",
            Category.DOCUMENTATION,
            "Документация API",
            2,
            "Опишите API или добавьте ссылку на OpenAPI.",
            lambda c: _contains(
                c,
                r"(?i)(openapi|swagger|/docs|api reference)",
                "Документация API найдена.",
                "Документация API не найдена.",
            ),
        ),
        Rule(
            "docs.community",
            Category.DOCUMENTATION,
            "Лицензия и вклад",
            2,
            "Добавьте LICENSE и CONTRIBUTING.md.",
            _license_contributing,
        ),
        Rule(
            "observability.logging",
            Category.OBSERVABILITY,
            "Логирование",
            2,
            "Настройте стандартный logging или structlog.",
            lambda c: _contains(
                c,
                r"\b(import logging|structlog|logging\.getLogger)\b",
                "Логирование найдено.",
                "Логирование не обнаружено.",
            ),
        ),
        Rule(
            "observability.structured",
            Category.OBSERVABILITY,
            "Структурированные события",
            2,
            "Добавьте JSON-логи и correlation/trace ID.",
            lambda c: _contains(
                c,
                r"(?i)(JSONRenderer|json.*log|correlation.?id|trace.?id|opentelemetry)",
                "Structured logging или tracing найден.",
                "Структурированные логи и trace ID не обнаружены.",
            ),
        ),
        Rule(
            "observability.health",
            Category.OBSERVABILITY,
            "Liveness и readiness",
            1,
            "Добавьте отдельные liveness и readiness endpoints.",
            lambda c: _contains(
                c,
                r"(/health/(live|ready)|liveness|readiness)",
                "Liveness/readiness найдены.",
                "Liveness/readiness не найдены.",
            ),
        ),
    )


def run_rules(
    context: AnalysisContext, rules: tuple[Rule, ...] | None = None
) -> list[CheckOutcome]:
    return [rule.run(context) for rule in rules or default_rules()]
