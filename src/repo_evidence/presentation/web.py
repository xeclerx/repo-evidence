import uuid
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=PACKAGE_ROOT / "templates")
router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@router.get("/reports/{analysis_id}", response_class=HTMLResponse)
async def report_page(request: Request, analysis_id: uuid.UUID) -> HTMLResponse:
    return templates.TemplateResponse(request, "report.html", {"analysis_id": str(analysis_id)})


@router.get("/comparisons/{base}/{head}", response_class=HTMLResponse)
async def comparison_page(request: Request, base: uuid.UUID, head: uuid.UUID) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "comparison.html", {"base_id": str(base), "head_id": str(head)}
    )
