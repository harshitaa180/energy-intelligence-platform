"""Live weather, fetched server-side.

The API key never reaches the browser: the frontend calls this backend, and this
backend calls the provider. Open-Meteo is the default because it needs no key at all.

Weather failure is never fatal. On any error the service returns a payload with
``available: false`` and the reason, and every other part of the platform keeps
working -- the historical analysis uses the temperature and humidity recorded
alongside each meter reading, not this live feed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from backend.config import get_settings
from data.schema import Provenance, site_profile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Coordinates:
    latitude: float
    longitude: float
    label: str
    timezone: str


#: Locations present in the dataset. Derived from the site identifiers, not guessed
#: per-site: every ``*_Jaipur`` site resolves to Jaipur, and so on.
LOCATIONS: dict[str, Coordinates] = {
    "Jaipur": Coordinates(26.9124, 75.7873, "Jaipur, India", "Asia/Kolkata"),
    "Delhi": Coordinates(28.6139, 77.2090, "Delhi, India", "Asia/Kolkata"),
    "Hyderabad": Coordinates(17.3850, 78.4867, "Hyderabad, India", "Asia/Kolkata"),
    "Singapore": Coordinates(1.3521, 103.8198, "Singapore", "Asia/Singapore"),
}

_cache: dict[str, tuple[float, dict]] = {}

WMO_CONDITIONS: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


def coordinates_for(site_id: str) -> Coordinates:
    location = site_profile(site_id).location
    return LOCATIONS.get(location, LOCATIONS["Jaipur"])


def _unavailable(reason: str, coordinates: Coordinates) -> dict:
    return {
        "available": False,
        "reason": reason,
        "location": coordinates.label,
        "provider": get_settings().weather_provider,
        "provenance": Provenance.UNAVAILABLE.value,
        "message": (
            "Weather unavailable. Energy analysis remains available -- historical "
            "analysis uses the temperature and humidity recorded with each meter "
            "reading."
        ),
    }


def get_weather(site_id: str, force_refresh: bool = False) -> dict:
    """Current conditions and a short forecast for a site's location."""
    settings = get_settings()
    coordinates = coordinates_for(site_id)
    cache_key = f"{settings.weather_provider}:{coordinates.latitude},{coordinates.longitude}"

    if not force_refresh:
        cached = _cache.get(cache_key)
        if cached and time.time() - cached[0] < settings.weather_cache_seconds:
            return cached[1]

    try:
        if settings.weather_provider == "open-meteo":
            payload = _fetch_open_meteo(coordinates)
        elif settings.weather_provider == "openweather":
            payload = _fetch_openweather(coordinates, settings.weather_api_key)
        elif settings.weather_provider == "weatherapi":
            payload = _fetch_weatherapi(coordinates, settings.weather_api_key)
        else:
            return _unavailable(
                f"Unknown weather provider {settings.weather_provider!r}", coordinates
            )
    except httpx.TimeoutException:
        logger.warning("Weather request timed out for %s", coordinates.label)
        return _unavailable("The weather provider did not respond in time.", coordinates)
    except httpx.HTTPStatusError as exc:
        logger.warning("Weather provider returned %s", exc.response.status_code)
        reason = (
            "The weather provider rejected the request. Check WEATHER_API_KEY."
            if exc.response.status_code in (401, 403)
            else f"The weather provider returned HTTP {exc.response.status_code}."
        )
        return _unavailable(reason, coordinates)
    except Exception as exc:  # noqa: BLE001 - weather must never break the app
        logger.exception("Weather lookup failed")
        return _unavailable(f"Weather lookup failed: {exc}", coordinates)

    _cache[cache_key] = (time.time(), payload)
    return payload


def _fetch_open_meteo(coordinates: Coordinates) -> dict:
    settings = get_settings()
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": coordinates.latitude,
        "longitude": coordinates.longitude,
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,"
            "precipitation,weather_code,wind_speed_10m"
        ),
        "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability",
        "daily": (
            "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
        ),
        "forecast_days": 7,
        "timezone": coordinates.timezone,
    }
    with httpx.Client(timeout=settings.weather_timeout_seconds) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    current = data.get("current", {})
    code = int(current.get("weather_code", 0) or 0)
    hourly = data.get("hourly", {})
    daily = data.get("daily", {})

    precipitation_probability = None
    probabilities = hourly.get("precipitation_probability") or []
    if probabilities:
        precipitation_probability = probabilities[0]

    return {
        "available": True,
        "provider": "open-meteo",
        "location": coordinates.label,
        "observed_at": current.get("time"),
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "humidity_pct": current.get("relative_humidity_2m"),
        "wind_speed_kmh": current.get("wind_speed_10m"),
        "precipitation_mm": current.get("precipitation"),
        "precipitation_probability_pct": precipitation_probability,
        "condition": WMO_CONDITIONS.get(code, "Unknown"),
        "condition_code": code,
        "hourly": _open_meteo_hourly(hourly),
        "forecast": _open_meteo_daily(daily),
        "provenance": Provenance.MEASURED.value,
        "forecast_provenance": Provenance.PREDICTED.value,
        "note": (
            "Live conditions from Open-Meteo for the site's city. This feed provides "
            "current context only; the historical analysis uses the weather recorded "
            "with each meter reading."
        ),
    }


def _open_meteo_hourly(hourly: dict) -> list[dict]:
    times = hourly.get("time") or []
    temperatures = hourly.get("temperature_2m") or []
    humidity = hourly.get("relative_humidity_2m") or []
    probability = hourly.get("precipitation_probability") or []
    out = []
    for index in range(min(24, len(times))):
        out.append(
            {
                "time": times[index],
                "temperature_c": _at(temperatures, index),
                "humidity_pct": _at(humidity, index),
                "precipitation_probability_pct": _at(probability, index),
            }
        )
    return out


def _open_meteo_daily(daily: dict) -> list[dict]:
    days = daily.get("time") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    probability = daily.get("precipitation_probability_max") or []
    codes = daily.get("weather_code") or []
    out = []
    for index in range(len(days)):
        code = int(_at(codes, index) or 0)
        out.append(
            {
                "date": days[index],
                "temperature_max_c": _at(highs, index),
                "temperature_min_c": _at(lows, index),
                "precipitation_probability_pct": _at(probability, index),
                "condition": WMO_CONDITIONS.get(code, "Unknown"),
            }
        )
    return out


def _at(values: list, index: int):
    return values[index] if index < len(values) else None


def _fetch_openweather(coordinates: Coordinates, api_key: str) -> dict:
    if not api_key:
        return _unavailable("WEATHER_API_KEY is not set for OpenWeather.", coordinates)
    settings = get_settings()
    with httpx.Client(timeout=settings.weather_timeout_seconds) as client:
        response = client.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "lat": coordinates.latitude,
                "lon": coordinates.longitude,
                "appid": api_key,
                "units": "metric",
            },
        )
        response.raise_for_status()
        data = response.json()

    main = data.get("main", {})
    weather = (data.get("weather") or [{}])[0]
    return {
        "available": True,
        "provider": "openweather",
        "location": coordinates.label,
        "observed_at": None,
        "temperature_c": main.get("temp"),
        "feels_like_c": main.get("feels_like"),
        "humidity_pct": main.get("humidity"),
        "wind_speed_kmh": round((data.get("wind", {}).get("speed", 0) or 0) * 3.6, 1),
        "precipitation_mm": (data.get("rain", {}) or {}).get("1h"),
        "precipitation_probability_pct": None,
        "condition": (weather.get("description") or "Unknown").title(),
        "condition_code": weather.get("id"),
        "hourly": [],
        "forecast": [],
        "provenance": Provenance.MEASURED.value,
        "forecast_provenance": Provenance.UNAVAILABLE.value,
        "note": "Current conditions from OpenWeather. Forecast requires the One Call API.",
    }


def _fetch_weatherapi(coordinates: Coordinates, api_key: str) -> dict:
    if not api_key:
        return _unavailable("WEATHER_API_KEY is not set for WeatherAPI.", coordinates)
    settings = get_settings()
    with httpx.Client(timeout=settings.weather_timeout_seconds) as client:
        response = client.get(
            "https://api.weatherapi.com/v1/forecast.json",
            params={
                "key": api_key,
                "q": f"{coordinates.latitude},{coordinates.longitude}",
                "days": 7,
                "aqi": "no",
                "alerts": "no",
            },
        )
        response.raise_for_status()
        data = response.json()

    current = data.get("current", {})
    forecast_days = (data.get("forecast", {}) or {}).get("forecastday", [])
    return {
        "available": True,
        "provider": "weatherapi",
        "location": coordinates.label,
        "observed_at": current.get("last_updated"),
        "temperature_c": current.get("temp_c"),
        "feels_like_c": current.get("feelslike_c"),
        "humidity_pct": current.get("humidity"),
        "wind_speed_kmh": current.get("wind_kph"),
        "precipitation_mm": current.get("precip_mm"),
        "precipitation_probability_pct": (
            forecast_days[0]["day"].get("daily_chance_of_rain") if forecast_days else None
        ),
        "condition": (current.get("condition", {}) or {}).get("text", "Unknown"),
        "condition_code": (current.get("condition", {}) or {}).get("code"),
        "hourly": [],
        "forecast": [
            {
                "date": day.get("date"),
                "temperature_max_c": day["day"].get("maxtemp_c"),
                "temperature_min_c": day["day"].get("mintemp_c"),
                "precipitation_probability_pct": day["day"].get("daily_chance_of_rain"),
                "condition": (day["day"].get("condition", {}) or {}).get("text"),
            }
            for day in forecast_days
        ],
        "provenance": Provenance.MEASURED.value,
        "forecast_provenance": Provenance.PREDICTED.value,
        "note": "Current conditions and forecast from WeatherAPI.",
    }


def observed_weather_context(site_id: str, date: str) -> dict:
    """Weather as recorded *in the dataset* for a given day.

    This is what the ML baseline actually used, so it is the honest thing to show
    beside an analysis of a historical day.
    """
    from data.transformers import site_interval_energy  # local import avoids a cycle
    import pandas as pd

    start = pd.Timestamp(date)
    frame = site_interval_energy(
        site_id, start, start + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    )
    if frame.empty:
        return {"available": False, "provenance": Provenance.UNAVAILABLE.value}
    return {
        "available": True,
        "date": date,
        "temperature_mean_c": round(float(frame["Temperature"].mean()), 1),
        "temperature_max_c": round(float(frame["Temperature"].max()), 1),
        "temperature_min_c": round(float(frame["Temperature"].min()), 1),
        "humidity_mean_pct": round(float(frame["Humidity"].mean()), 1),
        "heat_index": round(
            float(frame["Temperature"].mean()) + 0.1 * float(frame["Humidity"].mean()), 2
        ),
        "provenance": Provenance.MEASURED.value,
        "note": "Recorded alongside the meter readings; this is what the model used.",
    }
