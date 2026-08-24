"""FastAPI application entry point.

Run from the project root::

    uvicorn backend.main:app --reload

Data and models are warmed at startup so the first request is not the one that pays for
loading 22,084 readings and four model artefacts.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api import (
    analysis,
    appliances,
    assistant,
    carbon,
    dashboard,
    forecast,
    optimization,
    recommendations,
    weather,
)
from backend.config import get_settings
from backend.database import healthy as db_healthy, init_db
from backend.schemas.common import HealthResponse
from backend.services import energy_service, ml_service
from data.loaders import get_readings, get_validation_report, list_sites

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
logger = logging.getLogger("backend")

settings = get_settings()

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load the dataset, the model registry and the database once, at boot."""
    init_db()
    started = time.perf_counter()
    get_readings()
    registry = ml_service.registry_summary()
    elapsed = (time.perf_counter() - started) * 1000
    logger.info(
        "Warm-up complete in %.0f ms: %d sites, %d trained pair(s)",
        elapsed,
        len(list_sites()),
        registry["pairs_with_classifier"],
    )
    if registry["pairs_attempted"] == 0:
        logger.warning(
            "No model artefacts found. Run `python -m ml.train` to enable inefficiency "
            "detection; the rest of the platform works without it."
        )
    yield


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    version="1.0.0",
    description=(
        "AI-powered smart energy management and renewable optimisation.\n\n"
        "Every figure this API returns carries a `provenance` tag: `measured`, "
        "`predicted`, `estimated`, `simulated`, or `unavailable`. Nothing is "
        "fabricated -- where the data cannot support an answer, the response says so "
        "and explains why."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - started) * 1000
    response.headers["X-Response-Time-Ms"] = f"{elapsed:.1f}"
    if elapsed > 2000:
        logger.warning("%s %s took %.0f ms", request.method, request.url.path, elapsed)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a structured error rather than a bare stack trace."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": (
                "The request could not be completed. This has been logged; other "
                "endpoints are unaffected."
            ),
            "detail": type(exc).__name__,
        },
    )


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def health() -> dict:
    """Liveness plus a full account of what is and is not available."""
    from backend.services import ai_service

    registry = ml_service.registry_summary()
    stats = energy_service.platform_stats()
    validation = get_validation_report()
    database = db_healthy()

    degraded = registry["pairs_with_classifier"] == 0 or not database["available"]

    return {
        "status": "degraded" if degraded else "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
        "data": {
            **stats,
            "validation": validation,
            "sites": list(list_sites()),
        },
        "model_registry": {
            "pipeline_version": registry["pipeline_version"],
            "trained_at": registry["trained_at"],
            "pairs_attempted": registry["pairs_attempted"],
            "pairs_with_classifier": registry["pairs_with_classifier"],
            "pairs_with_baseline": registry["pairs_with_baseline"],
        },
        "services": {
            "database": database,
            "weather_provider": settings.weather_provider,
            "weather_requires_key": settings.weather_provider != "open-meteo",
            "llm": ai_service.status(),
            "tariff_mode": settings.tariff_mode,
            "solar_enabled": settings.solar_enabled,
            "battery_enabled": settings.battery_enabled,
            "ev_enabled": settings.ev_enabled,
            "simulation_allowed": settings.allow_simulation,
        },
    }


@app.get("/api/demo", tags=["system"])
def demo() -> dict:
    """Everything the frontend needs to open on a populated dashboard.

    The demo site is the one with the longest history and the only classifier that
    validates well, so the product opens on real, defensible analysis.
    """
    site_id = settings.demo_site_id
    if site_id not in list_sites():
        site_id = max(
            list_sites(), key=lambda s: energy_service.get_site_summary(s).day_count
        )
    date = energy_service.showcase_date(site_id)
    return {
        "site_id": site_id,
        "date": date,
        "latest_date": energy_service.latest_date(site_id),
        "reason": (
            "This site has the longest continuous history in the dataset and the only "
            "inefficiency classifier that validates well, so the dashboard opens on "
            "analysis that can be defended. The opening day is the most recent complete "
            "day on which an appliance could actually be assessed -- at this site the "
            "air conditioning stops running in October, so the very last day has "
            "nothing to analyse."
        ),
        "sites": [
            {
                "site_id": summary.site_id,
                "display_name": summary.display_name,
                "location": summary.location,
                "kind": summary.kind,
                "days": summary.day_count,
                "ml_appliances": summary.ml_appliances,
            }
            for summary in energy_service.list_site_summaries()
        ],
    }


for router in (
    dashboard.router,
    appliances.router,
    analysis.router,
    weather.router,
    forecast.router,
    optimization.router,
    recommendations.router,
    carbon.router,
):
    app.include_router(router, prefix="/api")

app.include_router(assistant.router, prefix="/api")


# ---------------------------------------------------------------------------
# Static frontend
#
# In production the built React app is served from this same process, so the
# deployment is one container on one origin and CORS never enters the picture. In
# development the frontend runs on Vite's dev server instead and this block is a
# no-op, because ``frontend/dist`` does not exist.
#
# This is registered last on purpose: FastAPI matches routes in order, so every
# API route, ``/docs`` and ``/openapi.json`` are already claimed before the
# catch-all below can see the request.
# ---------------------------------------------------------------------------

FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def _mount_frontend() -> None:
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        logger.info(
            "No built frontend at %s; serving the API only. Run `npm run build` in "
            "frontend/ to serve the dashboard from this process.",
            FRONTEND_DIST,
        )
        return

    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        # Hashed filenames, so these are safe to cache hard.
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{requested_path:path}", include_in_schema=False)
    def serve_frontend(requested_path: str) -> FileResponse:
        """Serve a real file if it exists, otherwise the SPA entry point.

        The client uses history routing, so a cold load of ``/appliances/ac`` must
        return ``index.html`` and let the router resolve it.
        """
        if requested_path.startswith("api/"):
            raise HTTPException(status_code=404, detail={"error": "unknown_endpoint"})

        candidate = (FRONTEND_DIST / requested_path).resolve()
        # Reject anything that escapes the build directory.
        if (
            requested_path
            and candidate.is_file()
            and candidate.is_relative_to(FRONTEND_DIST.resolve())
        ):
            return FileResponse(candidate)

        return FileResponse(index)

    logger.info("Serving the built frontend from %s", FRONTEND_DIST)


_mount_frontend()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host=settings.api_host, port=settings.api_port, reload=True)
