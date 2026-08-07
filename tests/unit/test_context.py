from pathlib import Path

import pytest

from repo_evidence.analysis.context import AnalysisContext
from repo_evidence.application.errors import UnsupportedProject
from repo_evidence.domain.models import Framework


def test_detects_fastapi_and_indexes_ast(fastapi_project: Path) -> None:
    context = AnalysisContext.build(fastapi_project, 2 * 1024 * 1024)
    assert context.framework is Framework.FASTAPI
    assert context.files["src/app/main.py"].tree is not None
    assert context.paths(r"Dockerfile$") == ["Dockerfile"]


@pytest.mark.parametrize(
    ("dependency", "source", "expected"),
    [
        ("django", "from django.urls import path\nurlpatterns = []", Framework.DJANGO),
        ("flask", "from flask import Flask\napp = Flask(__name__)", Framework.FLASK),
        ("litestar", "from litestar import Litestar\napp = Litestar([])", Framework.GENERIC),
    ],
)
def test_detects_supported_frameworks(
    tmp_path: Path, dependency: str, source: str, expected: Framework
) -> None:
    (tmp_path / "app.py").write_text(source, encoding="utf-8")
    (tmp_path / "requirements.txt").write_text(dependency, encoding="utf-8")
    assert AnalysisContext.build(tmp_path, 1_000_000).framework is expected


def test_rejects_non_backend_python_project(tmp_path: Path) -> None:
    (tmp_path / "script.py").write_text("print('hello')", encoding="utf-8")
    with pytest.raises(UnsupportedProject):
        AnalysisContext.build(tmp_path, 1_000_000)


def test_skips_oversized_and_invalid_python(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("fastapi", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def broken(", encoding="utf-8")
    (tmp_path / "large.py").write_text("x" * 100, encoding="utf-8")
    context = AnalysisContext.build(tmp_path, 50)
    assert context.files["broken.py"].tree is None
    assert "large.py" not in context.files
