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
from functools import lru_cache

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
   then give the reasoning. Do not pad.
7. Keep formatting simple: short paragraphs, and "- " bullets where a list genuinely
   helps. **bold** is fine for a key figure. No headings, tables, or nested lists.
8. If the question is outside what the snapshot covers, say so plainly rather than
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


def _not_configured_reason() -> str:
    """Explain where to set the key, for wherever this is actually running.

    Telling someone to edit ``.env`` is useless on a deployed server: there is no
    ``.env`` in the image, because it is gitignored precisely so keys never ship.
    """
    settings = get_settings()
    if settings.app_env.lower() in ("production", "prod"):
        where = (
            "Set LLM_API_KEY in this host's environment variables (on Render: the "
            "service's Environment tab). A local .env file is not deployed -- it is "
            "gitignored so that keys never reach the image."
        )
    else:
        where = "Set LLM_PROVIDER and LLM_API_KEY in .env."
    return (
        f"No LLM is configured. {where} Deterministic explanations, recommendations "
        "and daily insights remain available without it."
    )


def status() -> dict:
    settings = get_settings()
    return {
        "configured": settings.llm_configured,
        "provider": settings.llm_provider,
        "model": settings.resolved_llm_model if settings.llm_configured else None,
        "reason": (
            None
            if settings.llm_configured
            else _not_configured_reason()
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
        "model": settings.resolved_llm_model,
        "llm_available": True,
        "context_included": _context_keys(context),
        "grounding_note": (
            "Generated from the platform's computed context only. Figures come from "
            "meter readings, the trained model, the forecaster and the configured "
            "tariff."
        ),
    }


def daily_insight(site_id: str, date: str | None = None) -> dict:
    """The dashboard's insight card. Always returns something useful.

    The generated text is cached per site and date. Every dashboard load asks for this,
    and the underlying figures for a past day never change, so without a cache each page
    view would spend an LLM call and add its latency to the page. On a free provider
    tier that also exhausts the request quota within a few minutes of ordinary browsing.
    """
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

    # Keyed on the model too, so switching provider or model produces fresh text.
    cached, error = _cached_llm_insight(
        site_id, date, settings.llm_provider, settings.resolved_llm_model
    )
    if cached is None:
        return {
            "site_id": site_id,
            "date": date,
            "insight": deterministic,
            "source": "deterministic_fallback",
            "llm_available": False,
            "note": f"AI assistant temporarily unavailable ({error}).",
        }

    return {
        "site_id": site_id,
        "date": date,
        "insight": cached,
        "source": f"llm:{settings.llm_provider}",
        "llm_available": True,
        "deterministic_insight": deterministic,
    }


@lru_cache(maxsize=256)
def _cached_llm_insight(
    site_id: str, date: str, provider: str, model: str
) -> tuple[str | None, str | None]:
    """Generate one day's insight. Returns ``(text, None)`` or ``(None, reason)``.

    A failure is deliberately *not* cached as a permanent result -- the cache is
    cleared for this key so a transient rate limit or outage is retried on the next
    request rather than freezing the fallback in place until restart.
    """
    context = context_service.compact_context(site_id, date)
    prompt = (
        f"Site snapshot:\n```json\n{json.dumps(context, default=str)}\n```\n\n"
        f"{DAILY_INSIGHT_PROMPT}"
    )
    try:
        return _call_llm(prompt, SYSTEM_PROMPT, None), None
    except LLMUnavailable as exc:
        logger.warning("Daily insight LLM call failed: %s", exc)
        _cached_llm_insight.cache_clear()
        return None, str(exc)


def clear_insight_cache() -> None:
    _cached_llm_insight.cache_clear()


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
            model=settings.resolved_llm_model,
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
        "model": settings.resolved_llm_model,
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
        "generationConfig": {
            "maxOutputTokens": settings.llm_max_tokens,
            # Gemini 2.5+ models think by default and those tokens are drawn from
            # maxOutputTokens, so a modest budget can be consumed entirely by
            # thinking and return empty text. This task is rephrasing figures the
            # platform already computed, not reasoning, so thinking is turned off.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.resolved_llm_model}:generateContent"
    )
    try:
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            response = client.post(
                url, params={"key": settings.llm_api_key}, json=payload
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            # Verified against the quota metadata Google returns: the free-tier limit is
            # GenerateRequestsPerDayPerProjectPerModel, value 20 -- per DAY, not per
            # minute. Saying "rate limited" alone leads people to wait a minute and try
            # again all day.
            raise LLMUnavailable(
                "the free-tier daily quota is exhausted (HTTP 429). Google allows about "
                "20 requests per day per model on a free key, and it resets daily. The "
                "quota is per model, so setting LLM_MODEL to a different Gemini model "
                "gives a separate allowance"
            ) from exc
        if exc.response.status_code == 404:
            # Almost always a retired or misspelled model rather than a bad key, so
            # name it: "HTTP 404" alone sends people looking at their credentials.
            raise LLMUnavailable(
                f"the model {settings.resolved_llm_model!r} was not found. It may be "
                "retired or unavailable to this key; set LLM_MODEL to a current one"
            ) from exc
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
    """Answer a question from the context without a language model.

    This is intent matching, not a conversation: it exists so the platform is never
    silent when no LLM is configured or the provider fails. Intents are ordered from
    most specific to least, because the phrasings overlap -- "how much can I save" and
    "how much did today cost" both contain "how much", and only the extra word
    separates them.

    Anything unmatched falls through to the daily summary, which is always true but is
    identical for every question. Widening the intents below is what stops one generic
    answer standing in for several different ones.
    """
    lowered = question.lower()

    def has(*terms: str) -> bool:
        return any(term in lowered for term in terms)

    for matches, handler in _INTENTS:
        if matches(has, lowered):
            answer = handler(context)
            if answer:
                return answer

    return _deterministic_insight(context)


# --- intent handlers -------------------------------------------------------


def _answer_savings(context: dict) -> str:
    totals = context["optimisation"]["totals"]
    if totals["saving_per_day"] <= 0:
        return (
            "No material saving was found: the flexible loads at this site already run "
            "in low-cost hours under the configured tariff."
        )
    lines = [
        f"Shifting flexible loads to cheaper hours is estimated to save "
        f"{totals['saving_per_day']:.2f} a day, about "
        f"{totals['saving_per_month']:.0f} a month, which is "
        f"{totals['saving_pct']:.0f}% of the current cost."
    ]
    for plan in context["optimisation"]["plans"]:
        if not plan["shiftable"]:
            continue
        current = _hours(plan["current_hours"]) or "its current window"
        lines.append(
            f"{plan['appliance']}: move from {current} to "
            f"{_hours(plan['recommended_hours'])} for about "
            f"{plan['saving_per_day']:.2f} a day."
        )
    lines.append("Costs are estimates from the configured tariff, not a real bill.")
    return " ".join(lines)


def _answer_cost(context: dict) -> str:
    today = context["today"]
    lines = [
        f"On {today['date']} this site used {today['total_energy_kwh']:.2f} kWh, "
        f"costing an estimated {today['cost']:.2f} {today['cost_currency']} at the "
        "configured tariff."
    ]
    channels = today.get("channels", [])
    if channels:
        lines.append(
            "By appliance: "
            + ", ".join(f"{c['label']} {c['cost']:.2f}" for c in channels[:3])
            + "."
        )
    tariff = context["tariff"]
    if tariff["mode"] == "tou":
        lines.append(
            f"Peak hours ({_hours(tariff['peak_hours'])}) cost {tariff['peak_rate']} "
            f"against {tariff['offpeak_rate']} off-peak."
        )
    lines.append("The tariff is configuration, so this is an estimate, not a bill.")
    return " ".join(lines)


def _answer_consumption(context: dict) -> str:
    today = context["today"]
    lines = [
        f"On {today['date']} this site used {today['total_energy_kwh']:.2f} kWh, "
        f"peaking at {today['peak_power_w']:.0f} W."
    ]
    channels = today.get("channels", [])
    if channels:
        lines.append(
            "Breakdown: "
            + ", ".join(
                f"{c['label']} {c['energy_kwh']:.2f} kWh ({c['share_pct']:.0f}%)"
                for c in channels
            )
            + "."
        )
    comparison = today.get("vs_trailing_week") or {}
    if comparison.get("available") and comparison.get("change_pct") is not None:
        direction = "above" if comparison["change_pct"] >= 0 else "below"
        lines.append(
            f"That is {abs(comparison['change_pct']):.0f}% {direction} the trailing "
            f"{comparison['baseline_days']}-day average of "
            f"{comparison['baseline_kwh']:.2f} kWh."
        )
    lines.append("These figures are measured from the meter readings.")
    return " ".join(lines)


def _answer_top_appliance(context: dict) -> str:
    channels = context["today"].get("channels", [])
    if not channels:
        return "No appliance-level consumption was recorded for this day."
    top = channels[0]
    return (
        f"{top['label']} used the most: {top['energy_kwh']:.2f} kWh, "
        f"{top['share_pct']:.0f}% of the day's "
        f"{context['today']['total_energy_kwh']:.2f} kWh, costing an estimated "
        f"{top['cost']:.2f}."
    )


def _answer_forecast(context: dict) -> str:
    forecast = context["forecast"]
    if not forecast.get("available"):
        return f"A forecast is not available for this site: {forecast.get('reason')}"
    tomorrow = forecast["tomorrow"]
    answer = (
        f"Tomorrow ({tomorrow['date']}) is forecast at "
        f"{tomorrow['energy_kwh']:.2f} kWh, between {tomorrow['lower_kwh']:.2f} and "
        f"{tomorrow['upper_kwh']:.2f} kWh, costing an estimated "
        f"{tomorrow['cost']:.2f}. The model's measured mean absolute error is "
        f"{forecast['mae_kwh']:.2f} kWh."
    )
    if forecast.get("warning"):
        answer += f" {forecast['warning']}"
    return answer


def _answer_schedule(context: dict) -> str:
    plans = context["optimisation"]["plans"]
    shiftable = [p for p in plans if p["shiftable"]]
    if not shiftable:
        blocked = [p for p in plans if p.get("reason")]
        if blocked:
            return (
                f"Nothing can usefully be shifted at this site. "
                f"{blocked[0]['appliance']}: {blocked[0]['reason']}"
            )
        return "No load at this site can be usefully shifted under the configured tariff."

    lines = [
        f"Run {plan['appliance']} at {_hours(plan['recommended_hours'])} instead of "
        f"{_hours(plan['current_hours']) or 'its current window'}, saving about "
        f"{plan['saving_per_day']:.2f} a day."
        for plan in shiftable
    ]
    critical = context["optimisation"].get("critical_loads_never_shifted") or []
    if critical:
        lines.append(
            f"{', '.join(critical)} are critical loads and are never proposed for "
            "shifting."
        )
    return " ".join(lines)


def _answer_carbon(context: dict) -> str:
    carbon = context["carbon"]
    return (
        f"This day's estimated carbon is {carbon['daily_kg']:.2f} kg CO2e, and "
        f"{carbon['month_to_date_kg']:.1f} kg month to date, at a grid factor of "
        f"{carbon['emission_factor']} kg/kWh ({carbon['emission_factor_source']}). "
        "Carbon tracks consumption exactly here, so reducing it means reducing or "
        "shifting energy use. The factor is configured rather than measured, so this "
        "is an estimate."
    )


def _answer_replacement(context: dict) -> str:
    items = [r for r in context.get("recommendations", []) if "upgrad" in r["title"].lower()]
    if items:
        return f"{items[0]['recommendation']} {items[0]['reason']}"
    return (
        "No replacement is indicated from the available data. Replacement analysis needs "
        "appliance star ratings, which exist only for the Jaipur homes, and a purchase "
        "price, which is not in this dataset."
    )


def _answer_why_high(context: dict) -> str:
    abnormal = [a for a in context.get("appliances", []) if a["status"] == "abnormal"]
    if abnormal:
        return " ".join(entry["explanation"] for entry in abnormal[:2])

    today = context["today"]
    comparison = today.get("vs_trailing_week") or {}
    if comparison.get("available") and comparison.get("change_pct") is not None:
        direction = "above" if comparison["change_pct"] >= 0 else "below"
        return (
            f"This day used {today['total_energy_kwh']:.2f} kWh, "
            f"{abs(comparison['change_pct']):.0f}% {direction} the trailing "
            f"{comparison['baseline_days']}-day average of "
            f"{comparison['baseline_kwh']:.2f} kWh. No appliance exceeded its "
            "weather-adjusted expectation, so nothing is flagged as abnormal."
        )
    return ""


def _answer_weather(context: dict) -> str:
    recorded = context["weather"].get("recorded_with_readings", {})
    if not recorded.get("available"):
        return ""
    abnormal = [a for a in context.get("appliances", []) if a["status"] == "abnormal"]
    verdict = (
        " ".join(entry["explanation"] for entry in abnormal[:1])
        if abnormal
        else "No appliance exceeded its weather-adjusted expectation on this day."
    )
    return (
        f"On {recorded['date']} the mean temperature was "
        f"{recorded['temperature_mean_c']:.0f} C at "
        f"{recorded['humidity_mean_pct']:.0f}% humidity, giving a heat index of "
        f"{recorded['heat_index']:.1f}. That heat index is an input to the "
        f"expected-energy baseline, so the comparison is already weather-adjusted. "
        f"{verdict}"
    )


def _answer_model(context: dict) -> str:
    registry = context["model_registry"]
    lines = [
        f"{registry['pairs_with_classifier']} of {registry['pairs_attempted']} "
        "site/appliance pairs have a trained classifier."
    ]
    for entry in context.get("appliances", []):
        lines.append(
            f"{entry['label']}: model reliability is {entry['model_reliability']} -- "
            f"{entry['model_reliability_note']}"
        )
    return " ".join(lines)


def _answer_score(context: dict) -> str:
    score = context["sustainability_score"]
    if score["overall"] is None:
        return "A sustainability score could not be computed for this site."
    parts = [
        f"{c['label']} {c['score']:.0f}"
        for c in score["components"]
        if c["available"] and c["score"] is not None
    ]
    answer = (
        f"The sustainability score is {score['overall']:.0f} out of 100 "
        f"({score['grade']})."
    )
    if parts:
        answer += " Components: " + ", ".join(parts) + "."
    return (
        answer
        + " Components whose inputs are unavailable are excluded rather than scored zero."
    )


def _hours(hours: list[int]) -> str:
    return ", ".join(f"{hour:02d}:00" for hour in hours)


#: Ordered most specific first: earlier entries win when phrasings overlap.
_INTENTS = [
    # "how much can I save" must beat the cost intent, which also matches "how much".
    (
        lambda has, q: has("save", "saving", "cheaper", "reduce my bill", "lower my bill"),
        _answer_savings,
    ),
    (lambda has, q: has("replace", "upgrade", "new appliance", "worth buying"), _answer_replacement),
    (lambda has, q: has("carbon", "emission", "co2", "footprint"), _answer_carbon),
    (
        lambda has, q: has("tomorrow", "forecast", "predict", "next week", "next day"),
        _answer_forecast,
    ),
    (
        lambda has, q: has(
            "when should", "what time", "best time", "schedule", "shift", "should i run"
        ),
        _answer_schedule,
    ),
    (lambda has, q: has("reliable", "accurate", "trust", "model", "confidence"), _answer_model),
    (lambda has, q: has("score", "sustainab", "rating", "grade"), _answer_score),
    (lambda has, q: has("weather", "hot", "temperature", "humid", "climate"), _answer_weather),
    (
        lambda has, q: has("most", "biggest", "highest", "top consumer", "largest"),
        _answer_top_appliance,
    ),
    # Cost before consumption: "how much did today cost" expresses both ideas.
    (
        lambda has, q: has(
            "cost", "bill", "expensive", "price", "spend", "money", "rupee", "how much will",
            "how much did",
        ),
        _answer_cost,
    ),
    (
        lambda has, q: has(
            "consumption", "consume", "usage", "used", "kwh", "energy today", "how much energy"
        ),
        _answer_consumption,
    ),
    (
        lambda has, q: has("why", "high", "abnormal", "anomal", "normal", "wrong", "spike"),
        _answer_why_high,
    ),
]
