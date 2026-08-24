"""Service-layer behaviour: tariffs, optimisation, scoring, carbon, and AI grounding."""

from __future__ import annotations

import pytest

from backend.config import get_settings
from backend.services import (
    ai_service,
    carbon_service,
    context_service,
    energy_service,
    forecast_service,
    optimization_service,
    recommendation_service,
    renewable_service,
    score_service,
    tariff_service,
)
from data.schema import Flexibility
from tests.conftest import INDUSTRIAL_SITE, NO_STATE_SITE, PRIMARY_SITE


# --- tariff ----------------------------------------------------------------


def test_tariff_schedule_covers_the_whole_day():
    schedule = tariff_service.schedule()
    assert len(schedule) == 24
    assert {slot.hour for slot in schedule} == set(range(24))


def test_peak_costs_more_than_off_peak():
    settings = get_settings()
    peak_hour = sorted(settings.peak_hours)[0]
    offpeak_hour = sorted(settings.offpeak_hours)[0]
    assert tariff_service.rate_for_hour(peak_hour)[0] > tariff_service.rate_for_hour(offpeak_hour)[0]


def test_cheapest_hours_respects_exclusions():
    excluded = {0, 1, 2, 3, 4, 5}
    hours = tariff_service.cheapest_hours(3, exclude=excluded)
    assert not set(hours) & excluded
    assert len(hours) == 3


def test_cost_scales_linearly_with_energy():
    assert tariff_service.cost_of_kwh(2.0) == pytest.approx(2 * tariff_service.cost_of_kwh(1.0))


# --- energy ----------------------------------------------------------------


def test_day_totals_channels_sum_to_the_total():
    date = energy_service.latest_date(PRIMARY_SITE)
    totals = energy_service.day_totals(PRIMARY_SITE, date)
    channel_sum = sum(channel["energy_kwh"] for channel in totals["channels"])
    assert channel_sum == pytest.approx(totals["total_energy_kwh"], abs=1e-3)


def test_channel_shares_sum_to_100():
    date = energy_service.latest_date(PRIMARY_SITE)
    totals = energy_service.day_totals(PRIMARY_SITE, date)
    if totals["total_energy_kwh"] > 0:
        assert sum(c["share_pct"] for c in totals["channels"]) == pytest.approx(100, abs=0.5)


def test_latest_date_prefers_a_complete_day():
    for site in ("House_4", "House_1", INDUSTRIAL_SITE):
        date = energy_service.latest_date(site)
        assert energy_service.day_completeness(site, date)["complete"], site


def test_showcase_date_is_assessable_where_possible():
    """The demo must open on a day the analysis can actually speak about."""
    from backend.services import ml_service

    date = energy_service.showcase_date(PRIMARY_SITE)
    statuses = [
        ml_service.day_payload(PRIMARY_SITE, appliance, date).get("status")
        for appliance in ml_service.ml_appliances(PRIMARY_SITE)
    ]
    assert any(status in ("normal", "abnormal") for status in statuses)


def test_hourly_profile_has_every_hour_with_a_tariff():
    profile = energy_service.hourly_profile(PRIMARY_SITE)
    assert len(profile) == 24
    assert all(entry["rate"] > 0 for entry in profile)


# --- optimisation ----------------------------------------------------------


def test_critical_loads_are_never_shiftable():
    plan = optimization_service.optimize_site(INDUSTRIAL_SITE)
    for entry in plan["plans"]:
        if entry["flexibility"] == Flexibility.CRITICAL.value:
            assert entry["shiftable"] is False
            assert entry["recommended_hours"] == []
            assert entry["saving"] == 0.0


def test_quiet_hours_are_excluded_from_recommendations():
    quiet = {22, 23, 0, 1, 2, 3, 4, 5, 6}
    plan = optimization_service.optimize_site(PRIMARY_SITE, {"quiet_hours": quiet})
    for entry in plan["plans"]:
        assert not set(entry["recommended_hours"]) & quiet


def test_optimised_cost_never_exceeds_current_cost():
    for site in (PRIMARY_SITE, INDUSTRIAL_SITE, NO_STATE_SITE):
        plan = optimization_service.optimize_site(site)
        for entry in plan["plans"]:
            assert entry["optimized_cost"] <= entry["current_cost"] + 1e-6, entry["label"]


def test_partially_flexible_loads_move_only_their_peak_hour_portion():
    settings = get_settings()
    plan = optimization_service.optimize_site(PRIMARY_SITE)
    for entry in plan["plans"]:
        if entry["flexibility"] == Flexibility.LESS_FLEXIBLE.value and entry["shiftable"]:
            # The hours reported as "current" must be the peak hours actually occupied,
            # not the appliance's busiest hours overall.
            assert set(entry["current_hours"]) <= settings.peak_hours


def test_demand_response_peak_share_is_a_fraction():
    response = optimization_service.demand_response(PRIMARY_SITE)
    assert 0 <= response["peak_share_pct"] <= 100
    assert 0 <= response["peak_cost_share_pct"] <= 100


def test_ev_optimisation_is_disabled_without_configuration():
    result = optimization_service.optimize_ev_charging(PRIMARY_SITE, 30, 80, 8)
    assert result["available"] is False
    assert result["provenance"] == "unavailable"


# --- renewables ------------------------------------------------------------


def test_renewable_never_reports_measured_generation():
    profile = renewable_service.generation_profile(PRIMARY_SITE)
    assert profile["provenance"] != "measured"
    assert profile["available"] is False
    assert profile["integration_ready"] is True


def test_energy_flow_has_no_solar_edge_without_an_asset():
    flow = renewable_service.energy_flow(PRIMARY_SITE, 10.0)
    assert not [edge for edge in flow["edges"] if edge["from"] == "solar"]
    grid = [edge for edge in flow["edges"] if edge["from"] == "grid"][0]
    assert grid["provenance"] == "measured"
    assert grid["energy_kwh"] == pytest.approx(10.0)


def test_battery_state_is_unavailable_without_a_feed():
    state = renewable_service.battery_state()
    assert state["available"] is False
    assert state["provenance"] == "unavailable"


# --- carbon ----------------------------------------------------------------


def test_carbon_is_energy_times_the_factor():
    factor = carbon_service.emission_factor(PRIMARY_SITE)
    assert carbon_service.carbon_for(PRIMARY_SITE, 10.0) == pytest.approx(10.0 * factor)


def test_singapore_uses_its_own_emission_factor():
    assert carbon_service.emission_factor(INDUSTRIAL_SITE) != carbon_service.emission_factor(
        PRIMARY_SITE
    )


def test_carbon_summary_channel_totals_do_not_exceed_the_day():
    date = energy_service.latest_date(PRIMARY_SITE)
    summary = carbon_service.carbon_summary(PRIMARY_SITE, date)
    channel_sum = sum(entry["carbon_kg"] for entry in summary["by_channel"])
    assert channel_sum <= summary["daily"]["carbon_kg"] + 1e-3


# --- scoring ---------------------------------------------------------------


def test_score_weights_renormalise_to_100():
    for site in (PRIMARY_SITE, NO_STATE_SITE, INDUSTRIAL_SITE):
        score = score_service.sustainability_score(site)
        available = [c for c in score["components"] if c["available"]]
        if not available:
            assert score["overall"] is None
            continue
        assert sum(c["effective_weight_pct"] for c in available) == pytest.approx(100, abs=0.5)


def test_every_score_component_documents_its_formula():
    score = score_service.sustainability_score(PRIMARY_SITE)
    for component in score["components"]:
        assert component["formula"]
        assert component["detail"]


def test_scores_stay_inside_the_range():
    for site in (PRIMARY_SITE, NO_STATE_SITE, INDUSTRIAL_SITE):
        score = score_service.sustainability_score(site)
        for component in score["components"]:
            if component["score"] is not None:
                assert 0 <= component["score"] <= 100


# --- forecast --------------------------------------------------------------


def test_forecast_band_always_contains_the_point_estimate():
    result = forecast_service.forecast(PRIMARY_SITE, 7)
    assert result["available"]
    for point in result["points"]:
        assert point["lower_kwh"] <= point["energy_kwh"] <= point["upper_kwh"]
        assert point["lower_kwh"] >= 0


def test_forecast_band_widens_with_horizon():
    """Uncertainty must grow further out.

    The lower edge is clamped at zero, since energy cannot be negative, so the *total*
    width is not monotonic. The half-width above the point estimate is the unclamped
    quantity and it must increase.
    """
    result = forecast_service.forecast(PRIMARY_SITE, 7)
    half_widths = [point["upper_kwh"] - point["energy_kwh"] for point in result["points"]]
    assert half_widths == sorted(half_widths)
    assert half_widths[-1] > half_widths[0]


def test_forecast_warns_when_it_does_not_beat_a_flat_average():
    result = forecast_service.forecast(NO_STATE_SITE, 7)
    if result["available"] and not result["accuracy"]["beats_constant_baseline"]:
        assert result["warning"]


# --- recommendations -------------------------------------------------------


def test_recommendations_never_shift_a_critical_load():
    critical = set(recommendation_service.critical_loads(INDUSTRIAL_SITE))
    assert critical, "the industrial site has critical loads"
    result = recommendation_service.build_recommendations(INDUSTRIAL_SITE)
    for entry in result["recommendations"]:
        if entry["category"] == "load_shifting":
            assert entry["title"].replace("Shift ", "").split(" to ")[0] not in critical


def test_every_recommendation_carries_its_evidence():
    result = recommendation_service.build_recommendations(PRIMARY_SITE)
    for entry in result["recommendations"]:
        assert entry["reason"]
        assert entry["confidence"] in ("high", "medium", "low")
        assert entry["confidence_reason"]
        if entry["estimated_saving"] is None:
            assert entry["saving_period"] is None


def test_instrumentation_gaps_surface_as_recommendations():
    result = recommendation_service.build_recommendations(NO_STATE_SITE)
    data_quality = [r for r in result["recommendations"] if r["category"] == "data_quality"]
    assert data_quality
    assert data_quality[0]["provenance"] == "unavailable"


# --- AI grounding ----------------------------------------------------------


def test_context_contains_every_section_the_prompt_relies_on():
    context = context_service.build_context(PRIMARY_SITE)
    for key in (
        "site",
        "today",
        "appliances",
        "anomalies",
        "weather",
        "forecast",
        "tariff",
        "optimisation",
        "renewable",
        "carbon",
        "sustainability_score",
        "recommendations",
        "model_registry",
        "data_limitations",
    ):
        assert key in context, key


def test_context_names_the_loads_that_must_never_be_shifted():
    context = context_service.build_context(INDUSTRIAL_SITE)
    assert context["optimisation"]["critical_loads_never_shifted"]


def test_context_states_what_the_data_cannot_support():
    context = context_service.build_context(PRIMARY_SITE)
    limitations = " ".join(context["data_limitations"]).lower()
    assert "solar" in limitations
    assert "estimate" in limitations


def test_assistant_answers_are_grounded_without_an_llm():
    context = context_service.build_context(PRIMARY_SITE)
    answer = ai_service._deterministic_answer(
        PRIMARY_SITE, "Which appliance consumes the most?", context
    )
    top = context["today"]["channels"][0]
    assert top["label"] in answer
    assert f"{top['energy_kwh']:.2f}" in answer


def test_deterministic_insight_does_not_mix_timeframes():
    """A forecast anchored to the last observed day must not be quoted beside an older day."""
    historical = energy_service.showcase_date(PRIMARY_SITE)
    latest = energy_service.latest_date(PRIMARY_SITE)
    assert historical != latest, "this test needs a site whose showcase day is not the last day"

    old_insight = ai_service._deterministic_insight(
        context_service.compact_context(PRIMARY_SITE, historical)
    )
    latest_insight = ai_service._deterministic_insight(
        context_service.compact_context(PRIMARY_SITE, latest)
    )
    assert "forecast" not in old_insight.lower()
    assert "forecast" in latest_insight.lower()


def test_assistant_reports_llm_status_honestly():
    status = ai_service.status()
    assert status["suggested_prompts"]
    if not status["configured"]:
        assert status["reason"]
        assert status["model"] is None
