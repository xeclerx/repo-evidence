import ast
import re
from dataclasses import dataclass
from pathlib import Path

from repo_evidence.application.errors import UnsupportedProject
from repo_evidence.domain.models import Evidence, Framework

TEXT_SUFFIXES = {
    ".py",
    ".toml",
    ".ini",
    ".cfg",
    ".yaml",
    ".yml",
    ".json",
    ".md",
    ".txt",
    ".env",
}
TEXT_FILENAMES = {
    "Dockerfile",
    "Makefile",
    "LICENSE",
    ".gitignore",
    ".dockerignore",
    "requirements.txt",
}


@dataclass(slots=True, frozen=True)
class SourceFile:
    path: str
    text: str
    tree: ast.AST | None


@dataclass(slots=True)
class AnalysisContext:
    root: Path
    files: dict[str, SourceFile]
    framework: Framework

    @classmethod
    def build(cls, root: Path, max_file_bytes: int) -> "AnalysisContext":
        files: dict[str, SourceFile] = {}
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            if path.stat().st_size > max_file_bytes:
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in TEXT_FILENAMES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            tree: ast.AST | None = None
            if path.suffix == ".py":
                try:
                    tree = ast.parse(text, filename=relative)
                except SyntaxError:
                    tree = None
            files[relative] = SourceFile(relative, text, tree)
        framework = detect_framework(files)
        return cls(root=root, files=files, framework=framework)

    def paths(self, pattern: str) -> list[str]:
        expression = re.compile(pattern, re.IGNORECASE)
        return [path for path in self.files if expression.search(path)]

    def containing(self, pattern: str, *, python_only: bool = False) -> list[Evidence]:
        expression = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        evidence: list[Evidence] = []
        for source in self.files.values():
            if python_only and not source.path.endswith(".py"):
                continue
            match = expression.search(source.text)
            if match:
                line = source.text.count("\n", 0, match.start()) + 1
                evidence.append(Evidence("source", source.path, line, line))
        return evidence

    @property
    def python_files(self) -> list[SourceFile]:
        return [source for source in self.files.values() if source.path.endswith(".py")]


def _all_imports(files: dict[str, SourceFile]) -> set[str]:
    imports: set[str] = set()
    for source in files.values():
        if source.tree is None:
            continue
        for node in ast.walk(source.tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
    return imports


def detect_framework(files: dict[str, SourceFile]) -> Framework:
    if not any(path.endswith(".py") for path in files):
        raise UnsupportedProject("В репозитории не найден Python-код.")
    imports = _all_imports(files)
    joined_configs = "\n".join(
        source.text.lower()
        for source in files.values()
        if source.path.endswith((".toml", ".txt", ".cfg", ".ini"))
    )
    for framework, module in (
        (Framework.FASTAPI, "fastapi"),
        (Framework.DJANGO, "django"),
        (Framework.FLASK, "flask"),
    ):
        if module in imports or re.search(rf"\b{module}\b", joined_configs):
            return framework
    generic_signals = {"starlette", "litestar", "sanic", "falcon", "aiohttp", "tornado"}
    if imports & generic_signals or re.search(r"\b(uvicorn|gunicorn|asgi|wsgi)\b", joined_configs):
        return Framework.GENERIC
    raise UnsupportedProject("Не обнаружены признаки поддерживаемого Python backend-проекта.")
