"""Application settings, loaded from the environment.

Anything that is a policy choice rather than a measurement lives here: tariffs, the
grid emission factor, which weather provider to call, which LLM to use. Nothing in
this file is derived from the dataset, and the API labels every figure that depends on
these values as an estimate.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Model used when ``LLM_MODEL`` is unset. ``gemini-2.5-flash`` is on Google's free
#: tier, which makes the assistant usable without a paid account.
DEFAULT_LLM_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-5",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
}

#: Used to spot a model configured for a different provider than the one selected.
MODEL_PREFIXES: dict[str, str] = {
    "anthropic": "claude",
    "gemini": "gemini",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # -- application ------------------------------------------------------------
    app_name: str = "Energy Intelligence Platform"
    app_env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # -- database ---------------------------------------------------------------
    database_url: str = "sqlite:///./energy_platform.db"

    # -- tariff -----------------------------------------------------------------
    currency: str = "INR"
    currency_symbol: str = "₹"
    #: Flat rate used when ``tariff_mode`` is ``flat``.
    default_tariff_per_kwh: float = 8.0
    #: ``flat`` or ``tou`` (time-of-use).
    tariff_mode: str = "tou"
    tou_peak_rate: float = 11.0
    tou_offpeak_rate: float = 5.0
    tou_shoulder_rate: float = 8.0
    #: Hours of day charged at the peak rate.
    tou_peak_hours: str = "18,19,20,21,22"
    #: Hours of day charged at the off-peak rate.
    tou_offpeak_hours: str = "0,1,2,3,4,5,10,11,12,13,14,15"

    # -- carbon -----------------------------------------------------------------
    #: kg CO2e per kWh. Default is the Indian grid average (CEA). Configure per
    #: deployment; the API always labels carbon figures as estimated.
    grid_emission_factor: float = 0.71
    grid_emission_factor_source: str = "CEA India grid average (configured default)"
    #: Optional per-country overrides, ``Country:factor`` separated by commas.
    grid_emission_factor_overrides: str = "Singapore:0.417"

    # -- weather ----------------------------------------------------------------
    #: ``open-meteo`` needs no key. ``openweather`` and ``weatherapi`` do.
    weather_provider: str = "open-meteo"
    weather_api_key: str = ""
    weather_cache_seconds: int = 900
    weather_timeout_seconds: float = 8.0

    # -- LLM --------------------------------------------------------------------
    #: ``anthropic`` | ``openai`` | ``gemini`` | ``none``
    llm_provider: str = "anthropic"
    llm_api_key: str = ""
    #: Leave empty to take the provider's default from :data:`DEFAULT_LLM_MODELS`.
    llm_model: str = ""
    llm_max_tokens: int = 2000
    llm_timeout_seconds: float = 60.0

    # -- optional asset modules -------------------------------------------------
    #: All default off. The dataset contains no solar, battery or EV measurements,
    #: so these enable *interfaces and optimisation logic*, never invented readings.
    solar_enabled: bool = False
    solar_capacity_kw: float = 0.0
    battery_enabled: bool = False
    battery_capacity_kwh: float = 0.0
    battery_reserve_pct: float = 20.0
    battery_max_charge_kw: float = 0.0
    battery_max_discharge_kw: float = 0.0
    ev_enabled: bool = False
    ev_battery_kwh: float = 0.0
    ev_charger_kw: float = 0.0
    #: When true, solar/battery figures may be *modelled* and are tagged
    #: ``simulated`` everywhere they appear. Never tagged ``measured``.
    allow_simulation: bool = False

    # -- demo -------------------------------------------------------------------
    #: Site the dashboard opens on. House_4 has the longest history (116 days) and
    #: the only classifier that validates well.
    demo_site_id: str = "House_4"

    @model_validator(mode="before")
    @classmethod
    def _blank_non_text_means_default(cls, data):
        """Treat a blank value in ``.env`` as "use the default" for non-text settings.

        Writing ``LLM_MAX_TOKENS=`` with nothing after it is a natural thing to do when
        you don't want to override something. Without this, the empty string reaches
        pydantic as an int and the whole application refuses to start -- a
        disproportionate failure for a blank line in a config file.

        Text settings keep the empty string, because there it is a real value: an unset
        API key, or an ``LLM_MODEL`` that means "use the provider's default".
        """
        if not isinstance(data, dict):
            return data

        kept = {}
        for key, value in data.items():
            field = cls.model_fields.get(str(key).lower())
            blank = isinstance(value, str) and not value.strip()
            if blank and field is not None and field.annotation is not str:
                continue  # fall through to the field's default
            kept[key] = value
        return kept

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def peak_hours(self) -> set[int]:
        return _parse_hours(self.tou_peak_hours)

    @property
    def offpeak_hours(self) -> set[int]:
        return _parse_hours(self.tou_offpeak_hours)

    @property
    def emission_overrides(self) -> dict[str, float]:
        overrides: dict[str, float] = {}
        for chunk in self.grid_emission_factor_overrides.split(","):
            if ":" not in chunk:
                continue
            country, _, value = chunk.partition(":")
            try:
                overrides[country.strip()] = float(value)
            except ValueError:
                continue
        return overrides

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_provider != "none" and self.llm_api_key)

    @property
    def resolved_llm_model(self) -> str:
        """The model to actually call.

        Falls back to the provider's default when ``LLM_MODEL`` is unset, and ignores a
        model that belongs to a different provider. Switching ``LLM_PROVIDER`` without
        also changing ``LLM_MODEL`` is an easy mistake, and the result would otherwise
        be a confusing 404 from the provider rather than a clear fallback.
        """
        provider = self.llm_provider.lower()
        default = DEFAULT_LLM_MODELS.get(provider, "")
        if not self.llm_model:
            return default

        prefix = MODEL_PREFIXES.get(provider)
        if prefix and not self.llm_model.lower().startswith(prefix):
            return default
        return self.llm_model


def _parse_hours(raw: str) -> set[int]:
    hours: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            hour = int(chunk)
        except ValueError:
            continue
        if 0 <= hour <= 23:
            hours.add(hour)
    return hours


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
