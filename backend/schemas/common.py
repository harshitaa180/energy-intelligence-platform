"""Shared response and request models.

Response models use ``extra="allow"`` deliberately: they document and validate the
fields the frontend depends on, without a service adding one useful key turning into a
500. Request models are strict -- bad input is rejected at the edge.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Granularity = Literal["hourly", "daily", "weekly", "monthly"]
ProvenanceLiteral = Literal["measured", "predicted", "estimated", "simulated", "unavailable"]


class ApiModel(BaseModel):
    """Base for permissive response models."""

    model_config = ConfigDict(extra="allow")


class StrictModel(BaseModel):
    """Base for request bodies. Unknown fields are an error."""

    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    app: str
    environment: str
    data: dict[str, Any]
    model_registry: dict[str, Any]
    services: dict[str, Any]


class SiteResponse(ApiModel):
    site_id: str
    display_name: str
    location: str
    kind: str
    first_reading: str
    last_reading: str
    reading_count: int
    day_count: int
    total_energy_kwh: float
    channel_count: int
    ml_appliances: list[str]
    latest_date: str
    showcase_date: str


class ChannelCapabilityResponse(ApiModel):
    key: str
    label: str
    category: str
    flexibility: str
    has_power_signal: bool
    has_state_signal: bool
    has_metadata: bool
    has_baseline: bool
    has_classifier: bool
    notes: list[str] = Field(default_factory=list)


class ConsumptionPoint(ApiModel):
    timestamp: str
    label: str
    energy_kwh: float
    cost: float
    carbon_kg: float


class ConsumptionResponse(ApiModel):
    site_id: str
    granularity: str
    points: list[ConsumptionPoint]


class DashboardResponse(ApiModel):
    site: dict[str, Any]
    date: str
    available_dates: list[str]
    totals: dict[str, Any]
    comparison: dict[str, Any]
    appliances: list[dict[str, Any]]
    anomalies: list[dict[str, Any]]
    weather: dict[str, Any]
    forecast: dict[str, Any]
    optimization: dict[str, Any]
    carbon: dict[str, Any]
    sustainability_score: dict[str, Any]
    recommendations: dict[str, Any]
    insight: dict[str, Any]
    energy_flow: dict[str, Any]
    capabilities: list[dict[str, Any]]


class ApplianceAnalysisResponse(ApiModel):
    site_id: str
    appliance: str
    appliance_label: str
    available: bool


class ForecastResponse(ApiModel):
    site_id: str
    available: bool


class RecommendationsResponse(ApiModel):
    site_id: str
    recommendations: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class AnalyzeRequest(StrictModel):
    site_id: str = Field(min_length=1)
    appliance: str = Field(min_length=1)
    date: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="ISO date, YYYY-MM-DD"
    )


class ChatTurn(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class AssistantRequest(StrictModel):
    site_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=2000)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class OptimizationRequest(StrictModel):
    site_id: str = Field(min_length=1)
    quiet_hours: list[int] | None = Field(default=None)
    work_hours: list[int] | None = Field(default=None)


class EVChargeRequest(StrictModel):
    site_id: str = Field(min_length=1)
    current_soc_pct: float = Field(ge=0, le=100)
    target_soc_pct: float = Field(ge=0, le=100)
    departure_hour: int = Field(ge=0, le=23)


class ReplacementRequest(StrictModel):
    site_id: str = Field(min_length=1)
    appliance: str = Field(min_length=1)
    target_star_rating: float | None = Field(default=None, ge=1, le=5)
    replacement_cost: float | None = Field(default=None, gt=0)


class PreferencesRequest(StrictModel):
    site_id: str = Field(min_length=1)
    preferred_temperature_c: float | None = Field(default=None, ge=16, le=32)
    work_hours: list[int] | None = None
    sleep_hours: list[int] | None = None
    monthly_budget: float | None = Field(default=None, ge=0)
    comfort_priority: Literal["comfort", "balanced", "savings"] | None = None
    sustainability_priority: Literal["low", "medium", "high"] | None = None
    ev_departure_hour: int | None = Field(default=None, ge=0, le=23)
    battery_reserve_pct: float | None = Field(default=None, ge=0, le=100)
