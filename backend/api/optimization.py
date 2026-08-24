"""Optimisation, demand response, tariff and renewable endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from backend.schemas.common import EVChargeRequest, OptimizationRequest
from backend.services import (
    energy_service,
    optimization_service,
    renewable_service,
    tariff_service,
)
from backend.utils.errors import ensure_site

router = APIRouter(tags=["optimization"])


@router.get("/optimization")
def optimization(site_id: str) -> dict:
    """Current versus optimised schedule for every shiftable load."""
    ensure_site(site_id)
    return optimization_service.optimize_site(site_id)


@router.post("/optimization")
def optimization_with_constraints(request: OptimizationRequest) -> dict:
    """Same, honouring the caller's quiet hours."""
    ensure_site(request.site_id)
    constraints = {}
    if request.quiet_hours is not None:
        constraints["quiet_hours"] = set(request.quiet_hours)
    return optimization_service.optimize_site(request.site_id, constraints)


@router.get("/demand-response")
def demand_response(site_id: str) -> dict:
    """Where load sits against the price curve, and what could move."""
    ensure_site(site_id)
    return optimization_service.demand_response(site_id)


@router.get("/tariff")
def tariff() -> dict:
    """The configured tariff schedule."""
    return tariff_service.describe()


@router.get("/renewable")
def renewable(site_id: str) -> dict:
    """Solar, battery and EV status, plus the energy-flow graph."""
    ensure_site(site_id)
    date = energy_service.latest_date(site_id)
    totals = energy_service.day_totals(site_id, date)
    return renewable_service.energy_flow(site_id, totals["total_energy_kwh"])


@router.post("/optimization/ev")
def ev_charging(request: EVChargeRequest) -> dict:
    """Cheapest charging window that still meets the departure requirement."""
    ensure_site(request.site_id)
    return optimization_service.optimize_ev_charging(
        request.site_id,
        request.current_soc_pct,
        request.target_soc_pct,
        request.departure_hour,
    )
