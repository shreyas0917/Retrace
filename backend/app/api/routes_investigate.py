"""Investigation, rule catalog, and runbook APIs for the Phase 8 UI."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.core.security import require_api_key
from app.db.session import get_db
from app.services.diagnosis.rule_catalog import (
    RUNBOOK_BY_FAILURE,
    RUNBOOK_BY_SIGNAL,
    get_rule,
    list_rules,
)
from app.services.investigation import build_investigation

router = APIRouter(
    prefix="/api/v1",
    tags=["investigation"],
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


def _runbook_dirs() -> list[Path]:
    here = Path(__file__).resolve()
    # Docker mount + local monorepo layouts
    candidates = [
        Path("/app/runbooks"),
        here.parents[3] / "docs" / "runbooks",  # .../retrace/docs/runbooks
        here.parents[2] / "configs" / "runbooks",
    ]
    return [p for p in candidates if p.is_dir()]


def _list_runbook_files() -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for root in _runbook_dirs():
        for path in sorted(root.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            slug = path.stem
            if slug in seen:
                continue
            seen.add(slug)
            title = slug.replace("-", " ").title()
            first = path.read_text(encoding="utf-8").strip().splitlines()
            if first and first[0].startswith("#"):
                title = first[0].lstrip("# ").strip()
            out.append({"slug": slug, "title": title, "filename": path.name})
    return out


def _read_runbook(slug: str) -> str:
    if not _SLUG_RE.match(slug):
        raise AppError(
            code="INVALID_REQUEST",
            message="Invalid runbook slug",
            status_code=400,
        )
    for root in _runbook_dirs():
        path = root / f"{slug}.md"
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise NotFoundError(f"Runbook not found: {slug}")


@router.get(
    "/investigations/{execution_id}",
    dependencies=[Depends(require_api_key)],
)
def get_investigation(execution_id: str, db: Session = Depends(get_db)) -> dict:
    """Full evidence chain for one execution (retrieval → generation → judges → diagnosis)."""
    return build_investigation(db, execution_id)


@router.get("/rules", dependencies=[Depends(require_api_key)])
def get_rules() -> dict:
    return {"rules": list_rules()}


@router.get("/rules/{rule_id}", dependencies=[Depends(require_api_key)])
def get_rule_detail(rule_id: str) -> dict:
    rule = get_rule(rule_id)
    if not rule:
        raise NotFoundError(f"Rule not found: {rule_id}")
    return rule


@router.get("/runbooks")
def get_runbooks() -> dict:
    """Runbook index + failure/signal mappings (no auth — ops convenience)."""
    return {
        "runbooks": _list_runbook_files(),
        "by_failure_code": RUNBOOK_BY_FAILURE,
        "by_signal": RUNBOOK_BY_SIGNAL,
    }


@router.get("/runbooks/{slug}")
def get_runbook(slug: str) -> PlainTextResponse:
    body = _read_runbook(slug)
    return PlainTextResponse(body, media_type="text/markdown; charset=utf-8")
