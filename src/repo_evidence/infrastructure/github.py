import os
import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import httpx

from repo_evidence.application.errors import (
    GitHubRateLimited,
    InvalidRepositoryUrl,
    RepositoryNotFound,
    RepositoryTooLarge,
)
from repo_evidence.config import Settings

REPOSITORY_PART = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
EXCLUDED_PARTS = {".git", ".venv", "node_modules", "vendor", "build", "dist"}


@dataclass(slots=True, frozen=True)
class RepositoryRef:
    owner: str
    name: str

    @property
    def html_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}"


@dataclass(slots=True, frozen=True)
class GitHubRepository:
    ref: RepositoryRef
    default_branch: str
    commit_sha: str


def parse_repository_url(value: str) -> RepositoryRef:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise InvalidRepositoryUrl("Поддерживаются только HTTPS-ссылки на github.com.")
    if parsed.query or parsed.fragment or parsed.params:
        raise InvalidRepositoryUrl("Ссылка не должна содержать query, fragment или параметры.")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise InvalidRepositoryUrl("Ожидается ссылка вида https://github.com/owner/repository.")
    owner, name = parts
    if name.endswith(".git"):
        name = name[:-4]
    if not REPOSITORY_PART.fullmatch(owner) or not REPOSITORY_PART.fullmatch(name):
        raise InvalidRepositoryUrl("Имя владельца или репозитория содержит недопустимые символы.")
    return RepositoryRef(owner=owner, name=name)


class GitHubClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._external_client = client

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "RepoEvidence/0.1",
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        return headers

    async def resolve(self, ref: RepositoryRef) -> GitHubRepository:
        own_client = self._external_client is None
        client = self._external_client or httpx.AsyncClient(timeout=20, follow_redirects=True)
        try:
            response = await client.get(
                f"https://api.github.com/repos/{ref.owner}/{ref.name}", headers=self._headers()
            )
            self._raise_for_status(response)
            payload = response.json()
            if payload.get("private"):
                raise RepositoryNotFound("Приватные репозитории в MVP не поддерживаются.")
            default_branch = str(payload["default_branch"])
            commit = await client.get(
                f"https://api.github.com/repos/{ref.owner}/{ref.name}/commits/{default_branch}",
                headers=self._headers(),
            )
            self._raise_for_status(commit)
            sha = str(commit.json()["sha"])
            return GitHubRepository(ref=ref, default_branch=default_branch, commit_sha=sha)
        finally:
            if own_client:
                await client.aclose()

    async def download_and_extract(
        self, repository: GitHubRepository
    ) -> tempfile.TemporaryDirectory[str]:
        self.settings.analysis_temp_root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(
            prefix="analysis-", dir=self.settings.analysis_temp_root
        )
        root = Path(temporary.name)
        archive_path = root / "repository.zip"
        own_client = self._external_client is None
        client = self._external_client or httpx.AsyncClient(timeout=60, follow_redirects=True)
        try:
            url = (
                f"https://api.github.com/repos/{repository.ref.owner}/{repository.ref.name}"
                f"/zipball/{repository.commit_sha}"
            )
            total = 0
            async with client.stream("GET", url, headers=self._headers()) as response:
                self._raise_for_status(response)
                with archive_path.open("wb") as target:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self.settings.max_archive_bytes:
                            raise RepositoryTooLarge("GitHub-архив превышает лимит 25 МБ.")
                        target.write(chunk)
            source_root = root / "source"
            source_root.mkdir()
            self._safe_extract(archive_path, source_root)
            archive_path.unlink(missing_ok=True)
            return temporary
        except Exception:
            temporary.cleanup()
            raise
        finally:
            if own_client:
                await client.aclose()

    def _safe_extract(self, archive_path: Path, destination: Path) -> None:
        extracted_bytes = 0
        extracted_files = 0
        destination_resolved = destination.resolve()
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            roots = {PurePosixPath(item.filename).parts[0] for item in members if item.filename}
            root_prefix = next(iter(roots)) if len(roots) == 1 else None
            for item in members:
                posix_path = PurePosixPath(item.filename)
                parts = list(posix_path.parts)
                if root_prefix and parts and parts[0] == root_prefix:
                    parts = parts[1:]
                if not parts or any(part in {"", ".", ".."} for part in parts):
                    continue
                if any(part in EXCLUDED_PARTS for part in parts):
                    continue
                unix_mode = item.external_attr >> 16
                if stat.S_ISLNK(unix_mode):
                    continue
                target = destination.joinpath(*parts)
                resolved = target.resolve()
                if (
                    destination_resolved != resolved
                    and destination_resolved not in resolved.parents
                ):
                    raise RepositoryTooLarge("Архив содержит небезопасный путь.")
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                extracted_files += 1
                extracted_bytes += item.file_size
                if extracted_files > self.settings.max_files:
                    raise RepositoryTooLarge("В репозитории больше 10 000 файлов.")
                if extracted_bytes > self.settings.max_extracted_bytes:
                    raise RepositoryTooLarge("Распакованный репозиторий превышает 100 МБ.")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 404:
            raise RepositoryNotFound("Репозиторий не найден или недоступен без авторизации.")
        remaining = response.headers.get("x-ratelimit-remaining")
        if response.status_code in {403, 429} and remaining == "0":
            raise GitHubRateLimited("Исчерпан лимит GitHub API. Настройте GITHUB_TOKEN.")
        if response.status_code >= 400:
            response.raise_for_status()


def repository_source_path(temporary: tempfile.TemporaryDirectory[str]) -> Path:
    return Path(os.fspath(temporary.name)) / "source"
