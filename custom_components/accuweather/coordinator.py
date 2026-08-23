"""DataUpdateCoordinator for AccuWeather."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_UPDATE_INTERVAL, SLOW_REFRESH_EVERY
from .i18n import FALLBACK_LANGUAGE, text
from .utils import (
    EMPTY_AIR_QUALITY,
    BlockedError,
    get_current_weather, get_daily_forecast, get_hourly_forecast,
    get_air_quality, crawl_all_health_activities, get_minutecast_data,
    is_night_at, night_variant, parse_clock_minutes,
    slugify,
)
from .fetcher import HtmlFetcher
from .windy import EMPTY_STORMS, get_alerts, get_storms

_LOGGER = logging.getLogger(__name__)


class AccuWeatherDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching AccuWeather data."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        location_key: str,
        location_name: str,
        config_entry: ConfigEntry,
        update_interval: int = DEFAULT_UPDATE_INTERVAL,
        language: str = FALLBACK_LANGUAGE,
    ) -> None:
        """Initialize."""
        self.location_key = location_key
        self.location_name = location_name
        self.location_slug = slugify(location_name)
        self.session = session
        # Which AccuWeather locale to read, and which language the sensors
        # write in. Already resolved: "auto" was turned into a real language
        # when the entry was set up.
        self.language = language
        # AccuWeather needs a browser TLS fingerprint to get past its bot
        # protection; Windy is happy with the plain Home Assistant session.
        self.fetcher = HtmlFetcher(session)
        # Filled in from the page's own currentLocation object; falls back to the
        # Home Assistant location so storm tracking still works if it is missing.
        self.latitude: float | None = hass.config.latitude
        self.longitude: float | None = hass.config.longitude
        # Pages that only need refreshing every few cycles, and the cycle counter
        # that decides when.
        self._slow_data: dict[str, Any] = {}
        self._cycle = 0
        # Last storm and alert data that actually came back, kept so a Windy
        # outage does not read as "the storm is gone".
        self._storms_cache: dict[str, Any] = {}
        self._alerts_cache: list[dict[str, Any]] = []

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
            config_entry=config_entry,
        )

    @staticmethod
    def _apply_night_conditions(
        current: dict[str, Any], hourly: list[dict[str, Any]]
    ) -> None:
        """Turn daylight conditions into night ones after sunset.

        AccuWeather uses the same wording ("Trời quang") around the clock, so a
        22:00 forecast came out as `sunny` with a sun icon.
        """
        sunrise = parse_clock_minutes(current.get("sunrise"))
        sunset = parse_clock_minutes(current.get("sunset"))
        if sunrise is None or sunset is None:
            return

        observed = parse_clock_minutes(current.get("time"))
        if is_night_at(observed, sunrise, sunset):
            current["condition"] = night_variant(current.get("condition"), True)

        for hour in hourly:
            hour_of_day = hour.get("hour")
            if hour_of_day is None:
                continue
            if is_night_at(hour_of_day * 60, sunrise, sunset):
                hour["condition"] = night_variant(hour.get("condition"), True)

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library."""
        try:
            # Run requests sequentially with delays to avoid triggering bot detection.
            # Sending many concurrent requests is a strong bot signal.
            await asyncio.sleep(0.5)

            current_weather = await get_current_weather(
                self.fetcher, self.location_key, self.location_slug, self.language
            )
            if isinstance(current_weather, Exception):
                _LOGGER.debug(
                    "Exception getting current weather: %s: %s",
                    type(current_weather).__name__,
                    current_weather,
                )
                current_weather = None
            elif current_weather is None:
                _LOGGER.debug(
                    "Current weather returned None (HTML structure may have changed "
                    "or page unavailable for %s)",
                    self.location_key,
                )

            # Forecasts, air quality and health indices change on the scale of
            # hours, and together they are six of the eight page loads. Refreshing
            # them every few cycles instead of every cycle lets the interval be
            # short — so current conditions and storms show up quickly — while the
            # total request rate goes down, which is what keeps the bot protection
            # from kicking in.
            refresh_slow = (
                self._cycle % SLOW_REFRESH_EVERY == 0 or not self._slow_data
            )
            self._cycle += 1

            if refresh_slow:
                await asyncio.sleep(0.5)

                daily_forecast = await get_daily_forecast(
                    self.fetcher, self.location_key, self.location_slug,
                    self.language,
                )
                if isinstance(daily_forecast, Exception):
                    _LOGGER.debug(
                        "Exception getting daily forecast: %s: %s",
                        type(daily_forecast).__name__,
                        daily_forecast,
                    )
                    daily_forecast = []

                await asyncio.sleep(0.5)

                hourly_forecast = await get_hourly_forecast(
                    self.fetcher, self.location_key, self.location_slug,
                    language=self.language,
                )
                if isinstance(hourly_forecast, Exception):
                    _LOGGER.debug(
                        "Exception getting hourly forecast: %s: %s",
                        type(hourly_forecast).__name__,
                        hourly_forecast,
                    )
                    hourly_forecast = []

                await asyncio.sleep(0.5)

                air_quality = await get_air_quality(
                    self.fetcher, self.location_key, self.location_slug,
                    self.language,
                )
                if isinstance(air_quality, Exception):
                    _LOGGER.debug(
                        "Exception getting air quality: %s: %s",
                        type(air_quality).__name__,
                        air_quality,
                    )
                    air_quality = dict(EMPTY_AIR_QUALITY)

                await asyncio.sleep(0.5)

                health_activities = await crawl_all_health_activities(
                    self.fetcher, self.location_key, self.location_slug,
                    self.language,
                )
                if isinstance(health_activities, Exception):
                    _LOGGER.debug(
                        "Exception getting health activities: %s: %s",
                        type(health_activities).__name__,
                        health_activities,
                    )
                    health_activities = {}

                # Keep whatever came back, but never overwrite good data with an
                # empty result from a single failed page.
                self._slow_data = {
                    "daily_forecast": daily_forecast or self._slow_data.get("daily_forecast") or [],
                    "hourly_forecast": hourly_forecast or self._slow_data.get("hourly_forecast") or [],
                    "air_quality": air_quality if air_quality.get("aqi") is not None
                    else (self._slow_data.get("air_quality") or air_quality),
                    "health_activities": health_activities or self._slow_data.get("health_activities") or {},
                }

            daily_forecast = self._slow_data.get("daily_forecast") or []
            hourly_forecast = self._slow_data.get("hourly_forecast") or []
            air_quality = self._slow_data.get("air_quality") or dict(EMPTY_AIR_QUALITY)
            health_activities = self._slow_data.get("health_activities") or {}

            await asyncio.sleep(0.5)

            minutecast = await get_minutecast_data(
                self.fetcher, self.location_key, self.location_slug, self.language
            )
            if isinstance(minutecast, Exception):
                _LOGGER.debug(
                    "Exception getting MinuteCast: %s: %s",
                    type(minutecast).__name__,
                    minutecast,
                )
                minutecast = None

            if not current_weather:
                raise UpdateFailed("Failed to get current weather data")

            # The page reports its own coordinates; keep them for Windy.
            location = current_weather.get("location") or {}
            if location.get("latitude") is not None:
                self.latitude = location["latitude"]
                self.longitude = location["longitude"]

            # The current-conditions page carries no UV index. Take it from the
            # matching forecast hour instead; AccuWeather omits the row overnight,
            # when the index is zero by definition.
            if current_weather.get("uv_index") is None and hourly_forecast:
                current_weather["uv_index"] = hourly_forecast[0].get("uv_index") or 0

            self._apply_night_conditions(current_weather, hourly_forecast)

            # Windy is a separate, undocumented source: a bad field or a changed
            # endpoint must never take the weather data down with it.
            storms = dict(EMPTY_STORMS)
            alerts: list[dict[str, Any]] = self._alerts_cache
            try:
                storms = await get_storms(
                    self.session, self.latitude, self.longitude,
                    language=self.language,
                )
                if self.latitude is not None and self.longitude is not None:
                    alerts = await get_alerts(
                        self.session, self.latitude, self.longitude,
                        self.language,
                    )
                    self._alerts_cache = alerts
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug(
                    "Windy data unavailable this cycle: %s: %s",
                    type(err).__name__, err,
                )

            # If Windy could not be reached, keep showing the last known storms
            # rather than announcing "no storms" — during an actual typhoon that
            # would be the worst possible time to go quiet.
            if storms.get("available"):
                self._storms_cache = storms
            elif self._storms_cache.get("count"):
                storms = dict(self._storms_cache)
                storms["stale"] = True
                _LOGGER.debug(
                    "Keeping last known storm data (%d storms) while Windy is "
                    "unreachable", storms.get("count", 0),
                )

            return {
                "current": current_weather,
                "daily_forecast": daily_forecast or [],
                "hourly_forecast": hourly_forecast or [],
                "air_quality": air_quality or dict(EMPTY_AIR_QUALITY),
                "health_activities": health_activities or {},
                "minutecast": minutecast,
                "storms": storms,
                "alerts": alerts,
                "latitude": self.latitude,
                "longitude": self.longitude,
                "location_key": self.location_key,
                "location_name": self.location_name,
            }

        except BlockedError as err:
            # Akamai refused the request. Say so plainly, and say which of the
            # two remedies applies: without curl_cffi the requests do not look
            # like a browser at all, which is what gets blocked first on
            # datacenter and VPN addresses.
            hint = text(
                self.language,
                "blocked_hint_impersonated"
                if self.fetcher.using_impersonation
                else "blocked_hint_plain",
            )
            raise UpdateFailed(
                text(self.language, "blocked", status=err.status, hint=hint)
            ) from err
        except UpdateFailed:
            # Re-raise UpdateFailed without wrapping
            raise
        except Exception as exception:
            _LOGGER.debug(
                "Unexpected error in accuweather update: %s: %s",
                type(exception).__name__,
                exception,
                exc_info=True,
            )
            raise UpdateFailed(f"Unexpected error: {exception}") from exception
