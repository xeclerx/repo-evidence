from pathlib import Path

import pytest


@pytest.fixture
def fastapi_project(tmp_path: Path) -> Path:
    files = {
        "pyproject.toml": """
[project]
dependencies = ["fastapi", "sqlalchemy", "structlog"]
[tool.pytest.ini_options]
asyncio_mode = "auto"
[tool.ruff]
line-length = 100
[tool.mypy]
strict = true
""",
        "src/app/__init__.py": "",
        "src/app/main.py": """from fastapi import FastAPI
from app.api.health import router
app = FastAPI()
app.include_router(router)
""",
        "src/app/domain/order.py": """from dataclasses import dataclass
@dataclass
class Order:
    id: str
""",
        "src/app/application/service.py": """def create_order(order_id: str) -> str:
    return order_id
""",
        "src/app/infrastructure/repository.py": """class OrderRepository:
    def save(self, order_id: str) -> None:
        return None
""",
        "src/app/api/health.py": """from fastapi import APIRouter
router = APIRouter()
@router.get('/health/live')
async def live() -> dict[str, str]:
    return {'status': 'ok'}
@router.get('/health/ready')
async def ready() -> dict[str, str]:
    return {'status': 'ready'}
""",
        "src/app/config.py": """from pydantic_settings import BaseSettings
class Settings(BaseSettings):
    database_url: str
""",
        "tests/conftest.py": """import pytest
@pytest.fixture
def client():
    return object()
""",
        "tests/test_orders.py": """import pytest
@pytest.mark.anyio
async def test_one(): assert True
def test_two(): assert True
def test_three(): assert True
def test_four(): assert True
def test_five(): assert True
""",
        "tests/integration/test_api.py": "def test_integration_api(): assert True\n",
        "Dockerfile": "FROM python:3.12-slim\nRUN useradd app\nUSER app\nHEALTHCHECK CMD true\n",
        "docker-compose.yml": "services:\n  api:\n    build: .\n",
        ".github/workflows/ci.yml": "name: CI\n",
        ".gitignore": ".env\n",
        "uv.lock": "version = 1\n",
        "alembic/versions/001.py": "revision = '001'\n",
        "README.md": "# Demo\n## Запуск\n`docker compose up`\nOpenAPI доступен в `/docs`.\n",
        "LICENSE": "MIT\n",
        "CONTRIBUTING.md": "# Вклад\n",
        "src/app/logging.py": "import structlog\nfrom opentelemetry import trace\n",
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path
