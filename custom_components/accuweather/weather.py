"""Weather entity for AccuWeather integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.weather import (
    ATTR_CONDITION_CLEAR_NIGHT,
    ATTR_CONDITION_CLOUDY,
    ATTR_CONDITION_FOG,
    ATTR_CONDITION_HAIL,
    ATTR_CONDITION_LIGHTNING,
    ATTR_CONDITION_LIGHTNING_RAINY,
    ATTR_CONDITION_PARTLYCLOUDY,
    ATTR_CONDITION_POURING,
    ATTR_CONDITION_RAINY,
    ATTR_CONDITION_SNOWY,
    ATTR_CONDITION_SNOWY_RAINY,
    ATTR_CONDITION_SUNNY,
    ATTR_CONDITION_WINDY,
    WeatherEntity,
    WeatherEntityFeature,
    Forecast,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import AccuWeatherDataUpdateCoordinator
from .device import get_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AccuWeather weather entity."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    
    async_add_entities([AccuWeatherEntity(coordinator)], False)


class AccuWeatherEntity(CoordinatorEntity[AccuWeatherDataUpdateCoordinator], WeatherEntity):
    """Implementation of AccuWeather weather entity."""

    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    # The main entity of the device: no name of its own, so Home Assistant
    # displays the device name ("AccuWeather <location>") on its own.
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: AccuWeatherDataUpdateCoordinator) -> None:
        """Initialize the weather entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"accuweather_{coordinator.location_key}"
        self._attr_device_info = get_device_info(coordinator.location_key, coordinator.location_name)

    @property
    def condition(self) -> str | None:
        """Return the current condition."""
        if not self.coordinator.data or "current" not in self.coordinator.data:
            return None
        
        current = self.coordinator.data["current"]
        return current.get("condition")

    @property
    def native_temperature(self) -> float | None:
        """Return the current temperature."""
        if not self.coordinator.data or "current" not in self.coordinator.data:
            return None
        
        current = self.coordinator.data["current"]
        return current.get("temperature")

    @property
    def native_apparent_temperature(self) -> float | None:
        """Return the apparent temperature."""
        if not self.coordinator.data or "current" not in self.coordinator.data:
            return None
        
        current = self.coordinator.data["current"]
        realfeel = current.get("realfeel")
        if realfeel:
            # Extract numeric value from RealFeel text
            import re
            match = re.search(r"(-?[\d.,]+)", str(realfeel))
            if match:
                try:
                    return float(match.group(1).replace(",", "."))
                except ValueError:
                    pass
        return None

    @property
    def humidity(self) -> float | None:
        """Return the humidity."""
        if not self.coordinator.data or "current" not in self.coordinator.data:
            return None
        
        current = self.coordinator.data["current"]
        return current.get("humidity")

    @property
    def native_pressure(self) -> float | None:
        """Return the pressure."""
        if not self.coordinator.data or "current" not in self.coordinator.data:
            return None
        
        current = self.coordinator.data["current"]
        return current.get("pressure")

    @property
    def native_wind_speed(self) -> float | None:
        """Return the wind speed."""
        if not self.coordinator.data or "current" not in self.coordinator.data:
            return None
        
        current = self.coordinator.data["current"]
        return current.get("wind_speed")

    @property
    def wind_bearing(self) -> float | str | None:
        """Return the wind bearing in degrees."""
        if not self.coordinator.data or "current" not in self.coordinator.data:
            return None

        # Already converted from Vietnamese initials to degrees while parsing.
        return self.coordinator.data["current"].get("wind_bearing")

    @property
    def native_visibility(self) -> float | None:
        """Return the visibility."""
        if not self.coordinator.data or "current" not in self.coordinator.data:
            return None
        
        current = self.coordinator.data["current"]
        return current.get("visibility")

    @property
    def cloud_coverage(self) -> float | None:
        """Return the cloud coverage."""
        if not self.coordinator.data or "current" not in self.coordinator.data:
            return None
        
        current = self.coordinator.data["current"]
        return current.get("cloud_coverage")

    @property
    def uv_index(self) -> float | None:
        """Return the UV index."""
        if not self.coordinator.data or "current" not in self.coordinator.data:
            return None
        
        current = self.coordinator.data["current"]
        return current.get("uv_index")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return {}
        
        attrs = {
            "location_key": self.coordinator.location_key,
        }
        
        # Add current weather attributes
        if "current" in self.coordinator.data:
            current = self.coordinator.data["current"]
            attrs.update({
                "phrase": current.get("phrase"),
                "realfeel": current.get("realfeel"),
                "realfeel_shade": current.get("realfeel_shade"),
                "last_update": current.get("time"),
            })
        
        # Add air quality attributes
        if "air_quality" in self.coordinator.data:
            air_data = self.coordinator.data["air_quality"]
            attrs.update({
                "air_quality_category": air_data.get("category"),
                "air_quality_description": air_data.get("description"),
            })
            
            # Add main pollutant values
            pollutants = air_data.get("pollutants", {})
            if pollutants:
                for name, data in pollutants.items():
                    if data.get("value") is not None:
                        attrs[f"air_{name.lower()}"] = data.get("value")
                        attrs[f"air_{name.lower()}_unit"] = data.get("unit")
                        if data.get("aqi") is not None:
                            attrs[f"air_{name.lower()}_aqi"] = data.get("aqi")
        
        # Add forecast counts
        if "daily_forecast" in self.coordinator.data:
            attrs["daily_forecasts_available"] = len(self.coordinator.data["daily_forecast"])
        
        if "hourly_forecast" in self.coordinator.data:
            attrs["hourly_forecasts_available"] = len(self.coordinator.data["hourly_forecast"])
        
        # Add health activities summary
        if "health_activities" in self.coordinator.data:
            health_data = self.coordinator.data["health_activities"]
            health_summary = {}
            
            for group_name, activities in health_data.items():
                if activities:
                    # Get average risk/condition for each group
                    values = [activity.get('value', 0) for activity in activities if activity.get('value') is not None]
                    if values:
                        health_summary[f"{group_name}_avg"] = sum(values) / len(values)
                        health_summary[f"{group_name}_count"] = len(activities)
            
            attrs["health_activities"] = health_summary
        
        return attrs

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Return the daily forecast."""
        if not self.coordinator.data or "daily_forecast" not in self.coordinator.data:
            return None
        
        daily_data = self.coordinator.data["daily_forecast"]
        if not daily_data:
            return None
        
        forecasts = []
        base_date = dt_util.now()

        for i, day in enumerate(daily_data):
            forecast_date = self._daily_forecast_date(day, base_date, i)

            forecast = Forecast(
                datetime=forecast_date.isoformat(),
                condition=day.get("condition"),
                native_temperature=day.get("native_temperature"),
                native_templow=day.get("native_templow"),
                native_apparent_temperature=day.get("realfeel"),
                precipitation_probability=day.get("precipitation_probability"),
                native_precipitation=day.get("precipitation"),
                humidity=day.get("humidity"),
                native_wind_speed=day.get("wind_speed"),
                native_wind_gust_speed=day.get("wind_gust_speed"),
                wind_bearing=day.get("wind_bearing"),
                cloud_coverage=day.get("cloud_coverage"),
                uv_index=day.get("uv_index"),
            )
            forecasts.append(forecast)

        return forecasts

    @staticmethod
    def _daily_forecast_date(
        day: dict[str, Any], base_date: datetime, index: int
    ) -> datetime:
        """Build a timezone-aware noon timestamp for one forecast day.

        Home Assistant rejects naive datetimes in forecasts, so the local time
        zone is attached explicitly rather than relying on the default.
        """
        day_num = day.get("date_day")
        month_num = day.get("date_month")

        if day_num and month_num:
            year = base_date.year
            # The list runs forward from today, so a month before the current one
            # means the list has crossed into January.
            if month_num < base_date.month:
                year += 1
            try:
                return datetime(
                    year, month_num, day_num, 12, 0, 0,
                    tzinfo=base_date.tzinfo,
                )
            except ValueError:
                _LOGGER.debug(
                    "Invalid forecast date %s/%s, falling back to today+%d",
                    day_num, month_num, index,
                )

        fallback = base_date + timedelta(days=index)
        return fallback.replace(hour=12, minute=0, second=0, microsecond=0)

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Return the hourly forecast."""
        if not self.coordinator.data or "hourly_forecast" not in self.coordinator.data:
            return None
        
        hourly_data = self.coordinator.data["hourly_forecast"]
        if not hourly_data:
            return None
        
        forecasts = []
        base_date = dt_util.now().replace(minute=0, second=0, microsecond=0)

        for i, hour in enumerate(hourly_data):
            forecast_date = self._hourly_forecast_date(hour, base_date, i)

            forecast = Forecast(
                datetime=forecast_date.isoformat(),
                condition=hour.get("condition"),
                native_temperature=hour.get("native_temperature"),
                native_apparent_temperature=hour.get("native_apparent_temperature"),
                precipitation_probability=hour.get("precipitation_probability"),
                native_precipitation=hour.get("precipitation"),
                humidity=hour.get("humidity"),
                native_wind_speed=hour.get("wind_speed"),
                native_wind_gust_speed=hour.get("wind_gust_speed"),
                wind_bearing=hour.get("wind_bearing"),
                cloud_coverage=hour.get("cloud_coverage"),
                uv_index=hour.get("uv_index"),
                native_dew_point=hour.get("dew_point"),
            )
            forecasts.append(forecast)

        return forecasts

    @staticmethod
    def _hourly_forecast_date(
        hour: dict[str, Any], base_date: datetime, index: int
    ) -> datetime:
        """Build a timezone-aware timestamp for one forecast hour.

        Each row carries its own epoch timestamp, which is exact. The hour label
        plus the page's forecast day is the fallback when that attribute is gone.
        """
        if timestamp := hour.get("timestamp"):
            return datetime.fromtimestamp(timestamp, tz=base_date.tzinfo)

        hour_of_day = hour.get("hour")
        if hour_of_day is None:
            return base_date + timedelta(hours=index)

        day_offset = hour.get("day_offset") or 0
        stamp = (base_date + timedelta(days=day_offset)).replace(hour=hour_of_day)
        # Rows on the "today" page that sit before the current hour belong to
        # tomorrow (the page rolls over at midnight).
        if day_offset == 0 and hour_of_day < base_date.hour:
            stamp += timedelta(days=1)
        return stamp
