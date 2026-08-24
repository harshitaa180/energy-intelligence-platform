"""API surface: happy paths, error handling and graceful degradation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import INDUSTRIAL_SITE, NO_STATE_SITE, PRIMARY_APPLIANCE, PRIMARY_SITE

ALL_SITES = (
    "House_1",
    "House_2",
    "House_4",
    "House1_Delhi",
    "House1_Hyderabad",
    INDUSTRIAL_SITE,
)


def test_health(client: TestClient):
    body = client.get("/api/health").json()
    assert body["status"] in ("ok", "degraded")
    assert body["data"]["readings"] == 22084
    assert body["data"]["sites"]
    assert body["model_registry"]["pairs_with_classifier"] >= 1
    assert "llm" in body["services"]


def test_demo_opens_on_a_populated_site(client: TestClient):
    body = client.get("/api/demo").json()
    assert body["site_id"]
    assert body["date"]
    assert body["reason"]
    dashboard = client.get(
        f"/api/houses/{body['site_id']}/dashboard", params={"date": body["date"]}
    )
    assert dashboard.status_code == 200
    assert dashboard.json()["totals"]["total_energy_kwh"] > 0


def test_list_houses(client: TestClient):
    houses = client.get("/api/houses").json()
    assert len(houses) == 10
    for house in houses:
        assert house["reading_count"] > 0
        assert house["latest_date"]


@pytest.mark.parametrize("site_id", ALL_SITES)
def test_dashboard_renders_for_every_site(client: TestClient, site_id: str):
    """Including sites with no state signal and the industrial site."""
    response = client.get(f"/api/houses/{site_id}/dashboard")
    assert response.status_code == 200
    body = response.json()
    for key in (
        "totals",
        "appliances",
        "weather",
        "forecast",
        "optimization",
        "carbon",
        "sustainability_score",
        "recommendations",
        "insight",
        "energy_flow",
        "capabilities",
    ):
        assert key in body, f"{key} missing for {site_id}"


def test_unknown_site_returns_404_naming_what_exists(client: TestClient):
    response = client.get("/api/houses/Atlantis")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["error"] == "unknown_site"
    assert "House_4" in detail["available_sites"]


def test_unknown_appliance_returns_404(client: TestClient):
    response = client.get(f"/api/appliances/{PRIMARY_SITE}/toaster/analysis")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "unknown_appliance"


def test_unknown_date_returns_404_with_the_valid_range(client: TestClient):
    response = client.get(f"/api/houses/{PRIMARY_SITE}/dashboard", params={"date": "1999-01-01"})
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["error"] == "unknown_date"
    assert detail["first_date"] and detail["last_date"]


def test_invalid_body_is_rejected_at_the_edge(client: TestClient):
    assert client.post("/api/analyze", json={"site_id": PRIMARY_SITE}).status_code == 422
    assert (
        client.post(
            "/api/optimization/ev",
            json={
                "site_id": PRIMARY_SITE,
                "current_soc_pct": 300,
                "target_soc_pct": 80,
                "departure_hour": 8,
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/analyze",
            json={"site_id": PRIMARY_SITE, "appliance": "ac", "unexpected": 1},
        ).status_code
        == 422
    )


def test_consumption_granularities(client: TestClient):
    for granularity in ("hourly", "daily", "weekly", "monthly"):
        body = client.get(
            f"/api/houses/{PRIMARY_SITE}/consumption", params={"granularity": granularity}
        ).json()
        assert body["points"], granularity
        point = body["points"][0]
        assert {"timestamp", "label", "energy_kwh", "cost", "carbon_kg"} <= set(point)


def test_invalid_granularity_is_rejected(client: TestClient):
    response = client.get(
        f"/api/houses/{PRIMARY_SITE}/consumption", params={"granularity": "fortnightly"}
    )
    assert response.status_code == 422


def test_appliance_analysis_shape(client: TestClient, primary_date: str):
    body = client.get(
        f"/api/appliances/{PRIMARY_SITE}/{PRIMARY_APPLIANCE}/analysis",
        params={"date": primary_date},
    ).json()
    assert body["day"]["available"]
    assert body["model_card"]["available"]
    assert body["series"]
    assert body["weather"]["available"]
    assert "limitations" in body["model_card"]


def test_analyze_endpoint(client: TestClient, primary_date: str):
    body = client.post(
        "/api/analyze",
        json={"site_id": PRIMARY_SITE, "appliance": PRIMARY_APPLIANCE, "date": primary_date},
    ).json()
    assert body["available"]
    assert body["provenance"] == "measured"
    assert body["cost_provenance"] == "estimated"


def test_weather_is_server_side_and_never_leaks_a_key(client: TestClient):
    body = client.get("/api/weather", params={"site_id": PRIMARY_SITE}).json()
    assert "api_key" not in str(body).lower().replace("weather_api_key", "")
    if body["available"]:
        assert body["temperature_c"] is not None
        assert body["provenance"] == "measured"
    else:
        assert body["reason"], "an unavailable weather feed must explain itself"
        assert "remains available" in body["message"]


def test_forecast_reports_its_own_error(client: TestClient):
    body = client.get("/api/forecast", params={"site_id": PRIMARY_SITE}).json()
    assert body["available"]
    assert body["provenance"] == "predicted"
    assert body["accuracy"]["mae_kwh"] > 0
    assert body["accuracy"]["backtest_days"] > 0
    assert body["assumptions"], "assumptions must be stated"
    for point in body["points"]:
        assert point["lower_kwh"] <= point["energy_kwh"] <= point["upper_kwh"]


def test_forecast_unavailable_is_explained(client: TestClient):
    body = client.get("/api/forecast", params={"site_id": "House_2"}).json()
    assert body["available"] is False
    assert "history" in body["reason"]


def test_optimization_never_shifts_a_critical_load(client: TestClient):
    body = client.get("/api/optimization", params={"site_id": INDUSTRIAL_SITE}).json()
    critical = [p for p in body["plans"] if p["flexibility"] == "critical"]
    assert critical, "the industrial site has critical loads"
    for plan in critical:
        assert plan["shiftable"] is False
        assert plan["saving"] == 0.0
        assert plan["recommended_hours"] == []
    assert body["constraints"]["critical_loads_excluded"]


def test_optimization_savings_are_internally_consistent(client: TestClient):
    body = client.get("/api/optimization", params={"site_id": PRIMARY_SITE}).json()
    for plan in body["plans"]:
        assert plan["saving"] == pytest.approx(
            plan["current_cost"] - plan["optimized_cost"], abs=0.02
        )


def test_recommendations_are_ranked_and_justified(client: TestClient):
    body = client.get("/api/recommendations", params={"site_id": PRIMARY_SITE}).json()
    priorities = [r["priority"] for r in body["recommendations"]]
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    assert priorities == sorted(priorities, key=lambda p: order[p])
    for entry in body["recommendations"]:
        assert entry["reason"]
        assert entry["confidence_reason"]
        if entry["estimated_saving"] is not None:
            assert entry["saving_period"]


def test_recommendations_never_target_a_critical_load(client: TestClient):
    body = client.get("/api/recommendations", params={"site_id": INDUSTRIAL_SITE}).json()
    for entry in body["recommendations"]:
        if entry["category"] == "load_shifting":
            assert "chamber" not in (entry["appliance"] or "")


def test_carbon_states_its_factor_and_source(client: TestClient):
    body = client.get("/api/carbon", params={"site_id": PRIMARY_SITE}).json()
    assert body["provenance"] == "estimated"
    assert body["emission_factor"] > 0
    assert body["emission_factor_source"]
    assert body["renewable"]["available"] is False
    assert body["renewable"]["note"]


def test_carbon_factor_override_applies_to_singapore(client: TestClient):
    india = client.get("/api/carbon", params={"site_id": PRIMARY_SITE}).json()
    singapore = client.get("/api/carbon", params={"site_id": INDUSTRIAL_SITE}).json()
    assert singapore["emission_factor"] != india["emission_factor"]


def test_score_is_reconstructible(client: TestClient):
    body = client.get(f"/api/score/{PRIMARY_SITE}").json()
    assert body["overall"] is not None
    weights = sum(
        c["effective_weight_pct"] for c in body["components"] if c["available"]
    )
    assert weights == pytest.approx(100.0, abs=0.5)
    total = sum(
        c["score"] * c["effective_weight_pct"] / 100
        for c in body["components"]
        if c["available"]
    )
    assert total == pytest.approx(body["overall"], abs=0.5)
    for component in body["components"]:
        assert component["formula"]
        assert component["detail"]


def test_score_excludes_rather_than_zeroes_unavailable_components(client: TestClient):
    body = client.get(f"/api/score/{PRIMARY_SITE}").json()
    excluded = body["excluded_components"]
    assert "renewable_utilisation" in excluded
    for component in body["components"]:
        if component["key"] in excluded:
            assert component["score"] is None
            assert component["effective_weight_pct"] == 0.0


def test_renewable_reports_integration_ready_not_fake_data(client: TestClient):
    body = client.get("/api/renewable", params={"site_id": PRIMARY_SITE}).json()
    assert body["status"] == "renewable_integration_ready"
    assert body["solar"]["available"] is False
    assert body["battery"]["available"] is False
    assert body["ev"]["available"] is False
    grid_edges = [e for e in body["edges"] if e["from"] == "grid"]
    assert grid_edges and grid_edges[0]["provenance"] == "measured"
    assert not [e for e in body["edges"] if e["from"] == "solar"]


def test_ev_module_is_disabled_by_default_and_says_so(client: TestClient):
    body = client.post(
        "/api/optimization/ev",
        json={
            "site_id": PRIMARY_SITE,
            "current_soc_pct": 30,
            "target_soc_pct": 80,
            "departure_hour": 8,
        },
    ).json()
    assert body["available"] is False
    assert "EV" in body["reason"]
    assert body["provenance"] == "unavailable"


def test_replacement_reports_payback_as_unavailable_without_a_price(client: TestClient):
    body = client.post(
        "/api/appliances/replacement",
        json={"site_id": PRIMARY_SITE, "appliance": PRIMARY_APPLIANCE},
    ).json()
    assert body["available"]
    assert body["payback_years"] is None
    assert "price" in body["payback_note"].lower()
    assert body["assumptions"]


def test_replacement_computes_payback_when_given_a_price(client: TestClient):
    body = client.post(
        "/api/appliances/replacement",
        json={
            "site_id": PRIMARY_SITE,
            "appliance": PRIMARY_APPLIANCE,
            "replacement_cost": 35000,
        },
    ).json()
    assert body["payback_years"] is not None
    assert body["payback_years"] == pytest.approx(
        35000 / body["savings"]["annual_cost"], rel=0.02
    )


def test_replacement_unavailable_without_metadata(client: TestClient):
    body = client.post(
        "/api/appliances/replacement",
        json={"site_id": NO_STATE_SITE, "appliance": "ac"},
    ).json()
    assert body["available"] is False
    assert "metadata" in body["reason"]


def test_anomalies_separate_their_types(client: TestClient):
    body = client.get(f"/api/anomalies/{PRIMARY_SITE}").json()
    assert body["count"] > 0
    assert body["types_detected"]
    for anomaly in body["anomalies"]:
        assert anomaly["types"]
        assert anomaly["explanation"]
        assert anomaly["severity"] in ("high", "medium", "low", "info")


def test_site_without_state_signal_reports_no_anomalies_and_explains(client: TestClient):
    body = client.get(f"/api/anomalies/{NO_STATE_SITE}").json()
    assert body["count"] == 0
    capabilities = client.get(f"/api/houses/{NO_STATE_SITE}").json()["capabilities"]
    assert any(not c["has_state_signal"] and c["notes"] for c in capabilities)


def test_models_registry_exposes_metrics(client: TestClient):
    body = client.get("/api/models").json()
    assert body["pairs_attempted"] >= 4
    for pair in body["pairs"]:
        assert pair["status"]


def test_assistant_answers_without_an_llm(client: TestClient):
    body = client.post(
        "/api/assistant",
        json={"site_id": PRIMARY_SITE, "question": "Which appliance consumes the most?"},
    ).json()
    assert body["answer"]
    assert body["source"] in ("deterministic", "deterministic_fallback") or body[
        "source"
    ].startswith("llm:")
    assert body["context_included"]


def test_assistant_context_is_auditable(client: TestClient):
    body = client.get("/api/assistant/context", params={"site_id": PRIMARY_SITE}).json()
    for key in ("site", "today", "appliances", "forecast", "tariff", "carbon"):
        assert key in body
    assert body["data_limitations"], "the snapshot must state what it cannot support"


def test_assistant_history_is_recorded(client: TestClient):
    client.post(
        "/api/assistant",
        json={"site_id": PRIMARY_SITE, "question": "How much can I save?"},
    )
    body = client.get(f"/api/assistant/history/{PRIMARY_SITE}").json()
    assert body["conversations"]


def test_insight_always_returns_something(client: TestClient):
    for site_id in ALL_SITES:
        body = client.get("/api/assistant/insight", params={"site_id": site_id}).json()
        assert body["insight"], site_id


def test_preferences_round_trip(client: TestClient):
    client.put(
        "/api/preferences",
        json={
            "site_id": PRIMARY_SITE,
            "sleep_hours": [23, 0, 1, 2, 3, 4, 5],
            "comfort_priority": "savings",
        },
    )
    body = client.get(f"/api/preferences/{PRIMARY_SITE}").json()
    assert body["preferences"]["comfort_priority"] == "savings"
    # Sleep hours become quiet hours, which the optimiser must respect.
    assert body["preferences"]["quiet_hours"] == [23, 0, 1, 2, 3, 4, 5]

    plan = client.post(
        "/api/optimization",
        json={"site_id": PRIMARY_SITE, "quiet_hours": [23, 0, 1, 2, 3, 4, 5]},
    ).json()
    for entry in plan["plans"]:
        assert not set(entry["recommended_hours"]) & {23, 0, 1, 2, 3, 4, 5}


def test_tariff_is_labelled_as_configuration(client: TestClient):
    body = client.get("/api/tariff").json()
    assert body["provenance"] == "estimated"
    assert "not measured" in body["note"]
    assert len(body["schedule"]) == 24


# --- static frontend -------------------------------------------------------
#
# In production one process serves both the API and the built React app. These
# guard the boundary between them. They pass whether or not frontend/dist exists,
# because the invariant that matters -- the SPA must never swallow an API route --
# holds either way.


def test_unknown_api_path_returns_json_not_the_app_shell(client: TestClient):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_api_docs_are_not_shadowed_by_the_catch_all(client: TestClient):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_history_routes_serve_the_app_shell_when_built(client: TestClient):
    """A cold load of a client-side route must return index.html, not a 404."""
    from backend.main import FRONTEND_DIST

    if not (FRONTEND_DIST / "index.html").is_file():
        pytest.skip("frontend is not built; run `npm run build` in frontend/")

    for path in ("/", "/appliances", "/appliances/ac", "/forecast"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("text/html"), path
        assert "<div id=\"root\">" in response.text, path
