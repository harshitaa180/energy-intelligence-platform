"""AI assistant endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from backend.schemas.common import AssistantRequest
from backend.services import ai_service, context_service
from backend.database import conversations
from backend.utils.errors import ensure_date, ensure_site

router = APIRouter(tags=["assistant"])


@router.get("/assistant/status")
def assistant_status() -> dict:
    """Whether an LLM is configured, and the suggested prompts."""
    return ai_service.status()


@router.post("/assistant")
def ask(request: AssistantRequest) -> dict:
    """Answer a question grounded in the platform's computed context."""
    ensure_site(request.site_id)
    date = ensure_date(request.site_id, request.date)
    history = [turn.model_dump() for turn in request.history]
    answer = ai_service.ask(request.site_id, request.question, date, history)
    conversations.record(request.site_id, request.question, answer["answer"], answer["source"])
    return answer


@router.get("/assistant/insight")
def insight(site_id: str, date: str | None = None) -> dict:
    """The daily insight card. Falls back to a deterministic summary without an LLM."""
    ensure_site(site_id)
    return ai_service.daily_insight(site_id, ensure_date(site_id, date))


@router.get("/assistant/context")
def context(site_id: str, date: str | None = None) -> dict:
    """The exact snapshot the assistant is given. Exposed so answers are auditable."""
    ensure_site(site_id)
    return context_service.build_context(site_id, ensure_date(site_id, date))


@router.get("/assistant/history/{site_id}")
def history(site_id: str, limit: int = 20) -> dict:
    ensure_site(site_id)
    return {"site_id": site_id, "conversations": conversations.recent(site_id, limit)}
