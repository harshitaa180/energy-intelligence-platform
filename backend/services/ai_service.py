"""Generative AI assistant, grounded in the platform's own computed context.

The assistant is a *presentation* layer over data this platform already produced. It is
handed a structured snapshot from :mod:`backend.services.context_service` and is
instructed to use nothing else. Deterministic explanations and recommendations exist
independently of it, so the platform still explains itself when no LLM is configured.

Provider support: Anthropic via the official SDK (default), OpenAI and Gemini via their
REST endpoints. All calls happen server-side; the key never reaches the browser.
"""

from __future__ import annotations

import json
import logging

import httpx

from backend.config import get_settings
from backend.services import context_service, energy_service, ml_service
from ml.explanation import explain_site_summary

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the energy analyst inside an energy-management platform.

You are given a JSON snapshot of one site, assembled by the platform from meter
readings, a trained inefficiency model, live weather, a forecaster and a tariff
optimiser. Answer strictly from that snapshot.

Rules, in order of importance:

1. Never invent a number. Every measurement, cost, prediction, weather value, saving,
   appliance specification and model result must come from the snapshot. If a figure is
   not there, say it is not available and say why -- the snapshot usually contains the
   reason.
2. Distinguish what kind of number you are quoting. Energy readings are measured. Costs
   and carbon are estimates from configured rates. Forecasts are predictions with a
   stated error. Solar, battery and EV figures do not exist in this dataset unless the
   snapshot says otherwise.
3. Respect model reliability. When an appliance's `model_reliability` is not "good",
   do not present its classifier probability as a verdict; rely on the expected-versus-
   actual comparison and say that the classifier is not reliable for that appliance.
4. Never recommend switching off or delaying a load listed under
   `critical_loads_never_shifted`.
5. Weather is already accounted for in the expected-energy baseline. A hot day raises
   the expectation, so "it was hot" does not by itself excuse a deviation -- the
   deviation is already weather-adjusted. Say so when it is relevant.
6. Be concise and specific. Lead with the direct answer, quote the figures with units,
   then give the reasoning. Use plain prose and short lists. Do not pad.
7. If the question is outside what the snapshot covers, say so plainly rather than
   speculating.
"""

DAILY_INSIGHT_PROMPT = """Write a short daily energy insight for this site, in at most
four sentences plus one recommended action.

Cover: total consumption for the day, which appliance dominated and by how much,
whether anything exceeded its weather-adjusted expectation, and what the reader should
do next. Use only figures from the snapshot, with units. Do not use headings or
markdown formatting -- plain sentences only.
"""

SUGGESTED_PROMPTS = [
    "Why is my energy consumption high?",
    "Which appliance consumes the most?",
    "Is today's usage normal for this weather?",
    "How much can I save?",
    "What should I run tomorrow?",
    "When should I use my water heater?",
    "How can I reduce my carbon footprint?",
    "Which appliance should I replace?",
    "How reliable is the model behind these numbers?",
]


class LLMUnavailable(RuntimeError):
    """Raised when no LLM is configured or the provider call fails."""


def status() -> dict:
    settings = get_settings()
    return {
        "configured": settings.llm_configured,
        "provider": settings.llm_provider,
        "model": settings.llm_model if settings.llm_configured else None,
        "reason": (
            None
            if settings.llm_configured
            else (
                "No LLM is configured. Set LLM_PROVIDER and LLM_API_KEY in .env to "
                "enable conversational answers. Deterministic explanations, "
                "recommendations and daily insights remain available without it."
            )
        ),
        "suggested_prompts": SUGGESTED_PROMPTS,
    }


def ask(site_id: str, question: str, date: str | None = None, history: list | None = None) -> dict:
    """Answer a question about a site, grounded in the platform's context."""
    settings = get_settings()
    context = context_service.build_context(site_id, date)

    if not settings.llm_configured:
        return {
            "site_id": site_id,
            "question": question,
            "answer": _deterministic_answer(site_id, question, context),
            "source": "deterministic",
            "llm_available": False,
            "note": status()["reason"],
            "context_included": _context_keys(context),
        }

    prompt = (
        f"Site snapshot:\n```json\n{json.dumps(context, default=str)}\n```\n\n"
        f"Question: {question}"
    )

    try:
        answer = _call_llm(prompt, SYSTEM_PROMPT, history)
    except LLMUnavailable as exc:
        logger.warning("LLM call failed: %s", exc)
        return {
            "site_id": site_id,
            "question": question,
            "answer": _deterministic_answer(site_id, question, context),
            "source": "deterministic_fallback",
            "llm_available": False,
            "note": (
                f"AI assistant temporarily unavailable ({exc}). Core energy analysis "
                "remains available, and the answer below is generated from the same "
                "data without a language model."
            ),
            "context_included": _context_keys(context),
        }

    return {
        "site_id": site_id,
        "question": question,
        "answer": answer,
        "source": f"llm:{settings.llm_provider}",
        "model": settings.llm_model,
        "llm_available": True,
        "context_included": _context_keys(context),
        "grounding_note": (
            "Generated from the platform's computed context only. Figures come from "
            "meter readings, the trained model, the forecaster and the configured "
            "tariff."
        ),
    }


def daily_insight(site_id: str, date: str | None = None) -> dict:
    """The dashboard's insight card. Always returns something useful."""
    settings = get_settings()
    date = date or energy_service.latest_date(site_id)
    context = context_service.compact_context(site_id, date)
    deterministic = _deterministic_insight(context)

    if not settings.llm_configured:
        return {
            "site_id": site_id,
            "date": date,
            "insight": deterministic,
            "source": "deterministic",
            "llm_available": False,
        }

    prompt = (
        f"Site snapshot:\n```json\n{json.dumps(context, default=str)}\n```\n\n"
        f"{DAILY_INSIGHT_PROMPT}"
    )
    try:
        insight = _call_llm(prompt, SYSTEM_PROMPT, None)
    except LLMUnavailable as exc:
        logger.warning("Daily insight LLM call failed: %s", exc)
        return {
            "site_id": site_id,
            "date": date,
            "insight": deterministic,
            "source": "deterministic_fallback",
            "llm_available": False,
            "note": f"AI assistant temporarily unavailable ({exc}).",
        }

    return {
        "site_id": site_id,
        "date": date,
        "insight": insight,
        "source": f"llm:{settings.llm_provider}",
        "llm_available": True,
        "deterministic_insight": deterministic,
    }


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, system: str, history: list | None) -> str:
    settings = get_settings()
    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        return _call_anthropic(prompt, system, history)
    if provider == "openai":
        return _call_openai(prompt, system, history)
    if provider == "gemini":
        return _call_gemini(prompt, system, history)
    raise LLMUnavailable(f"unknown provider {provider!r}")


def _messages(prompt: str, history: list | None) -> list[dict]:
    messages: list[dict] = []
    for turn in (history or [])[-6:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": prompt})
    if messages[0]["role"] != "user":
        messages.pop(0)
    return messages


def _call_anthropic(prompt: str, system: str, history: list | None) -> str:
    settings = get_settings()
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise LLMUnavailable("the `anthropic` package is not installed") from exc

    client = anthropic.Anthropic(
        api_key=settings.llm_api_key, timeout=settings.llm_timeout_seconds
    )
    try:
        response = client.messages.create(
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            messages=_messages(prompt, history),
        )
    except anthropic.AuthenticationError as exc:
        raise LLMUnavailable("the API key was rejected") from exc
    except anthropic.RateLimitError as exc:
        raise LLMUnavailable("rate limited by the provider") from exc
    except anthropic.APIStatusError as exc:
        raise LLMUnavailable(f"provider returned HTTP {exc.status_code}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMUnavailable("could not reach the provider") from exc

    if response.stop_reason == "refusal":
        raise LLMUnavailable("the model declined to answer this request")

    text = "".join(block.text for block in response.content if block.type == "text")
    if not text.strip():
        raise LLMUnavailable("the model returned an empty response")
    return text.strip()


def _call_openai(prompt: str, system: str, history: list | None) -> str:
    settings = get_settings()
    payload = {
        "model": settings.llm_model,
        "messages": [{"role": "system", "content": system}, *_messages(prompt, history)],
        "max_tokens": settings.llm_max_tokens,
    }
    try:
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            response = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise LLMUnavailable(f"provider returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise LLMUnavailable("could not reach the provider") from exc

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as exc:
        raise LLMUnavailable("unexpected response shape") from exc


def _call_gemini(prompt: str, system: str, history: list | None) -> str:
    settings = get_settings()
    contents = [
        {
            "role": "user" if turn["role"] == "user" else "model",
            "parts": [{"text": turn["content"]}],
        }
        for turn in _messages(prompt, history)
    ]
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": settings.llm_max_tokens},
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.llm_model}:generateContent"
    )
    try:
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            response = client.post(
                url, params={"key": settings.llm_api_key}, json=payload
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise LLMUnavailable(f"provider returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise LLMUnavailable("could not reach the provider") from exc

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as exc:
        raise LLMUnavailable("unexpected response shape") from exc


# ---------------------------------------------------------------------------
# Deterministic fallbacks
# ---------------------------------------------------------------------------


def _context_keys(context: dict) -> list[str]:
    return sorted(context.keys())


def _deterministic_insight(context: dict) -> str:
    today = context["today"]
    appliances = context.get("appliances", [])
    top = max(appliances, key=lambda a: a["energy_kwh"], default=None)
    channels = today.get("channels", [])
    top_channel = channels[0] if channels else None

    abnormal = [a["label"] for a in appliances if a["status"] == "abnormal"]
    summary = explain_site_summary(
        site_label=context["site"]["display_name"],
        total_kwh=today["total_energy_kwh"],
        top_appliance=top_channel["label"] if top_channel else None,
        top_share_pct=top_channel["share_pct"] if top_channel else None,
        abnormal=abnormal,
    )

    extras = []
    comparison = today.get("vs_trailing_week") or {}
    if comparison.get("available") and comparison.get("change_pct") is not None:
        direction = "above" if comparison["change_pct"] >= 0 else "below"
        extras.append(
            f"That is {abs(comparison['change_pct']):.0f}% {direction} the trailing "
            f"{comparison['baseline_days']}-day average."
        )

    # The forecast is anchored to the last *observed* day, so quoting it beside a
    # historical day would mix timeframes. Only mention it when they coincide.
    forecast = context.get("forecast", {})
    if forecast.get("available") and context["site"].get("is_latest_day"):
        tomorrow = forecast["tomorrow"]
        extras.append(
            f"Tomorrow ({tomorrow['date']}) is forecast at "
            f"{tomorrow['energy_kwh']:.1f} kWh, plus or minus "
            f"{forecast['mae_kwh']:.1f} kWh."
        )

    recommendations = context.get("recommendations", [])
    if recommendations:
        extras.append(f"Recommended action: {recommendations[0]['recommendation']}")

    return " ".join([summary, *extras])


def _deterministic_answer(site_id: str, question: str, context: dict) -> str:
    """Answer common questions from the context without a language model.

    This is intentionally simple keyword routing. It exists so the platform is never
    silent, not to imitate a conversational model.
    """
    lowered = question.lower()
    today = context["today"]
    appliances = context.get("appliances", [])

    def top_channel_text() -> str:
        channels = today.get("channels", [])
        if not channels:
            return "No appliance-level consumption was recorded for this day."
        top = channels[0]
        return (
            f"{top['label']} used the most: {top['energy_kwh']:.2f} kWh, "
            f"{top['share_pct']:.0f}% of the day's {today['total_energy_kwh']:.2f} kWh."
        )

    if any(word in lowered for word in ("most", "biggest", "highest consumer", "top")):
        return top_channel_text()

    if "replace" in lowered:
        items = [r for r in context.get("recommendations", []) if "upgrad" in r["title"].lower()]
        if items:
            return f"{items[0]['recommendation']} {items[0]['reason']}"
        return (
            "No replacement is indicated from the available data. Replacement analysis "
            "needs appliance star ratings, which exist only for the Jaipur homes, and a "
            "purchase price, which is not in this dataset."
        )

    if "carbon" in lowered or "emission" in lowered:
        carbon = context["carbon"]
        return (
            f"This day's estimated carbon is {carbon['daily_kg']:.2f} kg CO2e, at a grid "
            f"factor of {carbon['emission_factor']} kg/kWh ({carbon['emission_factor_source']}). "
            "The factor is configured, not measured, so this is an estimate."
        )

    if "save" in lowered or "cheaper" in lowered or "bill" in lowered:
        totals = context["optimisation"]["totals"]
        if totals["saving_per_day"] > 0:
            return (
                f"Shifting flexible loads to cheaper hours is estimated to save "
                f"{totals['saving_per_day']:.2f} a day, about "
                f"{totals['saving_per_month']:.0f} a month, under the configured tariff. "
                "This assumes the appliances can actually run in the proposed windows."
            )
        return (
            "No material saving was found: the flexible loads at this site already run "
            "in low-cost hours under the configured tariff."
        )

    if "tomorrow" in lowered or "forecast" in lowered or "predict" in lowered:
        forecast = context["forecast"]
        if not forecast.get("available"):
            return f"A forecast is not available: {forecast.get('reason')}"
        tomorrow = forecast["tomorrow"]
        return (
            f"Tomorrow ({tomorrow['date']}) is forecast at {tomorrow['energy_kwh']:.2f} kWh, "
            f"between {tomorrow['lower_kwh']:.2f} and {tomorrow['upper_kwh']:.2f} kWh. "
            f"The model's measured mean absolute error is {forecast['mae_kwh']:.2f} kWh."
        )

    if "geyser" in lowered or "water heater" in lowered or "when should" in lowered:
        shiftable = [p for p in context["optimisation"]["plans"] if p["shiftable"]]
        if shiftable:
            plan = shiftable[0]
            hours = ", ".join(f"{h:02d}:00" for h in plan["recommended_hours"])
            return (
                f"Run {plan['appliance']} at {hours}. It currently runs at "
                f"{', '.join(f'{h:02d}:00' for h in plan['current_hours'])}, and the "
                f"proposed window saves about {plan['saving_per_day']:.2f} a day."
            )
        return "No load at this site can be usefully shifted under the configured tariff."

    if "high" in lowered or "why" in lowered:
        abnormal = [a for a in appliances if a["status"] == "abnormal"]
        if abnormal:
            return " ".join(entry["explanation"] for entry in abnormal[:2])
        comparison = today.get("vs_trailing_week") or {}
        if comparison.get("available"):
            direction = "above" if (comparison["change_pct"] or 0) >= 0 else "below"
            return (
                f"This day used {today['total_energy_kwh']:.2f} kWh, "
                f"{abs(comparison['change_pct']):.0f}% {direction} the trailing "
                f"{comparison['baseline_days']}-day average of "
                f"{comparison['baseline_kwh']:.2f} kWh. No appliance exceeded its "
                "weather-adjusted expectation on this day."
            )
        return _deterministic_insight(context)

    if "model" in lowered or "reliable" in lowered or "accurate" in lowered:
        registry = context["model_registry"]
        lines = [
            f"{registry['pairs_with_classifier']} of {registry['pairs_attempted']} "
            "site/appliance pairs have a trained classifier."
        ]
        for entry in appliances:
            lines.append(
                f"{entry['label']}: model reliability is "
                f"{entry['model_reliability']} -- {entry['model_reliability_note']}"
            )
        return " ".join(lines)

    return _deterministic_insight(context)
