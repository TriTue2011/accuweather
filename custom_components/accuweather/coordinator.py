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

from .const import DOMAIN, DEFAULT_UPDATE_INTERVAL
from .utils import (
    EMPTY_AIR_QUALITY,
    BlockedError,
    get_current_weather, get_daily_forecast, get_hourly_forecast,
    get_air_quality, crawl_all_health_activities, get_minutecast_data,
    slugify,
)
from .windy import get_alerts, get_storms

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
    ) -> None:
        """Initialize."""
        self.location_key = location_key
        self.location_name = location_name
        self.location_slug = slugify(location_name)
        self.session = session
        # Filled in from the page's own currentLocation object; falls back to the
        # Home Assistant location so storm tracking still works if it is missing.
        self.latitude: float | None = hass.config.latitude
        self.longitude: float | None = hass.config.longitude

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
            config_entry=config_entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library."""
        try:
            # Run requests sequentially with delays to avoid triggering bot detection.
            # Sending many concurrent requests is a strong bot signal.
            await asyncio.sleep(0.5)

            current_weather = await get_current_weather(self.session, self.location_key, self.location_slug)
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

            await asyncio.sleep(0.5)

            daily_forecast = await get_daily_forecast(self.session, self.location_key, self.location_slug)
            if isinstance(daily_forecast, Exception):
                _LOGGER.debug(
                    "Exception getting daily forecast: %s: %s",
                    type(daily_forecast).__name__,
                    daily_forecast,
                )
                daily_forecast = []

            await asyncio.sleep(0.5)

            hourly_forecast = await get_hourly_forecast(self.session, self.location_key, self.location_slug)
            if isinstance(hourly_forecast, Exception):
                _LOGGER.debug(
                    "Exception getting hourly forecast: %s: %s",
                    type(hourly_forecast).__name__,
                    hourly_forecast,
                )
                hourly_forecast = []

            await asyncio.sleep(0.5)

            air_quality = await get_air_quality(self.session, self.location_key, self.location_slug)
            if isinstance(air_quality, Exception):
                _LOGGER.debug(
                    "Exception getting air quality: %s: %s",
                    type(air_quality).__name__,
                    air_quality,
                )
                air_quality = dict(EMPTY_AIR_QUALITY)

            await asyncio.sleep(0.5)

            health_activities = await crawl_all_health_activities(self.session, self.location_key, self.location_slug)
            if isinstance(health_activities, Exception):
                _LOGGER.debug(
                    "Exception getting health activities: %s: %s",
                    type(health_activities).__name__,
                    health_activities,
                )
                health_activities = {}

            await asyncio.sleep(0.5)

            minutecast = await get_minutecast_data(self.session, self.location_key, self.location_slug)
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

            storms = await get_storms(self.session, self.latitude, self.longitude)

            alerts: list[dict[str, Any]] = []
            if self.latitude is not None and self.longitude is not None:
                alerts = await get_alerts(self.session, self.latitude, self.longitude)

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
            # Akamai refused the request. Say so plainly: this is a very
            # different problem from a layout change, and the log is the only
            # place the user can find out which one they have.
            raise UpdateFailed(
                f"AccuWeather từ chối yêu cầu (HTTP {err.status}) — trang web đang "
                "chặn truy cập tự động từ địa chỉ IP này. Dữ liệu sẽ trở lại khi "
                "hết chặn; nếu kéo dài, thử đổi mạng/DNS hoặc tăng thời gian cập nhật."
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
