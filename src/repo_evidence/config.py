from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "RepoEvidence"
    app_env: str = "development"
    app_debug: bool = False
    database_url: str = (
        "postgresql+asyncpg://repo_evidence:repo_evidence@localhost:5432/repo_evidence"
    )
    redis_url: str = "redis://localhost:6379/0"
    github_token: str | None = None
    log_level: str = "INFO"
    otel_enabled: bool = False
    analysis_temp_root: Path = Path(".repo-evidence-tmp")
    analysis_timeout_seconds: int = Field(default=120, ge=10, le=600)
    max_archive_bytes: int = 25 * 1024 * 1024
    max_extracted_bytes: int = 100 * 1024 * 1024
    max_files: int = 10_000
    max_text_file_bytes: int = 2 * 1024 * 1024
    analyzer_version: str = "1.0.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
