import io
import zipfile
from pathlib import Path

import httpx
import pytest

from repo_evidence.application.errors import (
    GitHubRateLimited,
    InvalidRepositoryUrl,
    RepositoryNotFound,
    RepositoryTooLarge,
)
from repo_evidence.config import Settings
from repo_evidence.infrastructure.github import (
    GitHubClient,
    GitHubRepository,
    RepositoryRef,
    parse_repository_url,
    repository_source_path,
)


@pytest.mark.parametrize(
    ("url", "owner", "name"),
    [
        ("https://github.com/openai/openai-python", "openai", "openai-python"),
        ("https://github.com/example/repo.git", "example", "repo"),
        ("https://github.com/a.b/repo_name/", "a.b", "repo_name"),
    ],
)
def test_parse_repository_url(url: str, owner: str, name: str) -> None:
    assert parse_repository_url(url) == RepositoryRef(owner, name)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "https://gitlab.com/a/b",
        "https://github.com/a/b/tree/main",
        "https://github.com/a/b?tab=readme",
        "https://github.com/a",
    ],
)
def test_rejects_non_repository_urls(url: str) -> None:
    with pytest.raises(InvalidRepositoryUrl):
        parse_repository_url(url)


@pytest.mark.asyncio
async def test_resolve_public_repository() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": "a" * 40})
        return httpx.Response(200, json={"default_branch": "main", "private": False})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await GitHubClient(Settings(), client).resolve(RepositoryRef("owner", "repo"))
    assert result.commit_sha == "a" * 40
    assert result.default_branch == "main"


@pytest.mark.asyncio
async def test_resolve_maps_not_found() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(404))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RepositoryNotFound):
            await GitHubClient(Settings(), client).resolve(RepositoryRef("owner", "missing"))


@pytest.mark.asyncio
async def test_resolve_rejects_private_and_maps_rate_limit() -> None:
    private = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"default_branch": "main", "private": True})
    )
    async with httpx.AsyncClient(transport=private) as client:
        with pytest.raises(RepositoryNotFound):
            await GitHubClient(Settings(), client).resolve(RepositoryRef("owner", "private"))
    limited = httpx.MockTransport(
        lambda _: httpx.Response(403, headers={"x-ratelimit-remaining": "0"})
    )
    async with httpx.AsyncClient(transport=limited) as client:
        with pytest.raises(GitHubRateLimited):
            await GitHubClient(Settings(), client).resolve(RepositoryRef("owner", "repo"))


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_safe_extract_strips_github_root(tmp_path: Path) -> None:
    archive = tmp_path / "repo.zip"
    archive.write_bytes(_zip({"owner-repo-sha/src/app.py": b"print('ok')"}))
    destination = tmp_path / "out"
    destination.mkdir()
    GitHubClient(Settings())._safe_extract(archive, destination)
    assert (destination / "src/app.py").read_text() == "print('ok')"


def test_safe_extract_rejects_size_limit(tmp_path: Path) -> None:
    archive = tmp_path / "repo.zip"
    archive.write_bytes(_zip({"root/large.py": b"x" * 32}))
    destination = tmp_path / "out"
    destination.mkdir()
    client = GitHubClient(Settings(max_extracted_bytes=10))
    with pytest.raises(RepositoryTooLarge):
        client._safe_extract(archive, destination)


def test_safe_extract_does_not_escape_destination(tmp_path: Path) -> None:
    archive = tmp_path / "repo.zip"
    archive.write_bytes(_zip({"root/../../escape.py": b"bad"}))
    destination = tmp_path / "out"
    destination.mkdir()
    GitHubClient(Settings())._safe_extract(archive, destination)
    assert not (tmp_path / "escape.py").exists()


@pytest.mark.asyncio
async def test_download_and_extract_stream(tmp_path: Path) -> None:
    content = _zip({"owner-repo-sha/app.py": b"from fastapi import FastAPI"})
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=content))
    settings = Settings(analysis_temp_root=tmp_path)
    async with httpx.AsyncClient(transport=transport) as client:
        temporary = await GitHubClient(settings, client).download_and_extract(
            GitHubRepository(RepositoryRef("owner", "repo"), "main", "a" * 40)
        )
        try:
            assert (repository_source_path(temporary) / "app.py").exists()
        finally:
            temporary.cleanup()


@pytest.mark.asyncio
async def test_download_enforces_compressed_limit(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"too large"))
    settings = Settings(analysis_temp_root=tmp_path, max_archive_bytes=3)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RepositoryTooLarge):
            await GitHubClient(settings, client).download_and_extract(
                GitHubRepository(RepositoryRef("owner", "repo"), "main", "a" * 40)
            )
