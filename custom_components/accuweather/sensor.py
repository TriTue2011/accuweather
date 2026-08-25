"""Sensor platform for AccuWeather integration."""
from __future__ import annotations

import logging
import re
from typing import Any, NamedTuple

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_SENSOR_LANGUAGE,
    DOMAIN,
    LANDFALL_MODEL_PRIORITY,
    LANGUAGE_FOR_ENTITY_IDS,
    SENSOR_LANGUAGE_AUTO,
    LANDFALL_HORIZON_HOURS,
    LANDFALL_RANGE_KM,
    STORM_SLOTS,
    STORM_TRACK_POINTS,
)
from .coordinator import AccuWeatherDataUpdateCoordinator
from .device import get_device_info
from .i18n import text
from .nchmf import NCHMF_URL
from .windy import place_name, storm_headline

_LOGGER = logging.getLogger(__name__)

# Home Assistant rejects a state longer than this, taking the entity with it.
MAX_STATE_LENGTH = 255

# Mapping from sensor key to API pollutant key
_POLUTANT_KEY_MAP: dict[str, str] = {
    "pm25": "PM2_5",
    "pm10": "PM10",
    "ozone": "O3",
    "nitrogen_dioxide": "NO2",
    "sulfur_dioxide": "SO2",
    "carbon_monoxide": "CO"
}

# Entity names come from translations/<lang>.json via translation_key, so Home
# Assistant renames every sensor when the user switches language. The key is
# reused as the translation key: unique_id is built from key and must not move.
SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    # Basic weather sensors
    SensorEntityDescription(
        key="realfeel_temperature",
        translation_key="realfeel_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="realfeel_shade_temperature",
        translation_key="realfeel_shade_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    SensorEntityDescription(
        key="pressure",
        translation_key="pressure",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.HPA,
    ),
    SensorEntityDescription(
        key="wind_speed",
        translation_key="wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
    ),
    SensorEntityDescription(
        key="wind_bearing",
        translation_key="wind_bearing",
        icon="mdi:compass",
    ),
    SensorEntityDescription(
        key="wind_gust",
        translation_key="wind_gust",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
    ),
    SensorEntityDescription(
        key="visibility",
        translation_key="visibility",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
    ),
    SensorEntityDescription(
        key="cloud_coverage",
        translation_key="cloud_coverage",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    SensorEntityDescription(
        key="uv_index",
        translation_key="uv_index",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="UV index",
    ),
    SensorEntityDescription(
        key="dew_point",
        translation_key="dew_point",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    # Air quality sensors
    SensorEntityDescription(
        key="pm25",
        translation_key="pm25",
        device_class=SensorDeviceClass.PM25,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="µg/m³",
    ),
    SensorEntityDescription(
        key="pm10",
        translation_key="pm10",
        device_class=SensorDeviceClass.PM10,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="µg/m³",
    ),
    SensorEntityDescription(
        key="ozone",
        translation_key="ozone",
        device_class=SensorDeviceClass.OZONE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="µg/m³",
    ),
    SensorEntityDescription(
        key="nitrogen_dioxide",
        translation_key="nitrogen_dioxide",
        device_class=SensorDeviceClass.NITROGEN_DIOXIDE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="µg/m³",
    ),
    SensorEntityDescription(
        key="sulfur_dioxide",
        translation_key="sulfur_dioxide",
        device_class=SensorDeviceClass.SULPHUR_DIOXIDE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="µg/m³",
    ),
    SensorEntityDescription(
        key="carbon_monoxide",
        translation_key="carbon_monoxide",
        device_class=SensorDeviceClass.CO,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="µg/m³",
    ),
    SensorEntityDescription(
        key="cloud_ceiling",
        translation_key="cloud_ceiling",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.METERS,
    ),
    SensorEntityDescription(
        key="heat_index",
        translation_key="heat_index",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="aqi",
        translation_key="aqi",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:air-filter",
    ),
    SensorEntityDescription(
        key="aqi_category",
        translation_key="aqi_category",
        icon="mdi:air-filter",
    ),
    SensorEntityDescription(
        key="sunrise",
        translation_key="sunrise",
        icon="mdi:weather-sunset-up",
    ),
    SensorEntityDescription(
        key="sunset",
        translation_key="sunset",
        icon="mdi:weather-sunset-down",
    ),
    SensorEntityDescription(
        key="moon_phase",
        translation_key="moon_phase",
        icon="mdi:moon-waning-crescent",
    ),
    # MinuteCast sensor
    SensorEntityDescription(
        key="minutecast",
        translation_key="minutecast",
        icon="mdi:radar",
    ),
)

# Storm tracking sensors, fed by Windy's tropical cyclone feed.
STORM_SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="storm_count",
        translation_key="storm_count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-hurricane",
    ),
    SensorEntityDescription(
        key="storm_nearby_count",
        translation_key="storm_nearby_count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-hurricane",
    ),
    SensorEntityDescription(
        key="storm_nearest_distance",
        translation_key="storm_nearest_distance",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
    ),
    SensorEntityDescription(
        key="storm_nearest_beaufort",
        translation_key="storm_nearest_beaufort",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:windsock",
    ),
    SensorEntityDescription(
        key="storm_movement",
        translation_key="storm_movement",
        icon="mdi:compass-outline",
    ),
    SensorEntityDescription(
        key="storm_landfall",
        translation_key="storm_landfall",
        icon="mdi:map-marker-alert",
    ),
    SensorEntityDescription(
        key="weather_alerts",
        translation_key="weather_alerts",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:alert-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AccuWeather sensor entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    names = await async_name_overrides(
        hass,
        config_entry.data.get(CONF_SENSOR_LANGUAGE, SENSOR_LANGUAGE_AUTO),
    )

    entities = []

    # Add static sensor types
    for description in SENSOR_TYPES:
        entities.append(AccuWeatherSensorEntity(coordinator, description, names))

    # Storm tracking (Windy). One sensor per slot so the entity ids stay stable
    # as storms form and dissipate, plus the summary sensors.
    for description in STORM_SENSOR_TYPES:
        entities.append(
            AccuWeatherStormSummarySensor(coordinator, description, names)
        )

    for slot in range(STORM_SLOTS):
        entities.append(AccuWeatherStormSensor(coordinator, slot, names))

    # Việt Nam's official bulletins, a source of its own next to Windy.
    entities.append(AccuWeatherBulletinSensor(coordinator, names))

    # Add dynamic health activity sensors
    health_count = 0
    if coordinator.data and "health_activities" in coordinator.data:
        health_data = coordinator.data["health_activities"]
        
        for group_name, activities in health_data.items():
            for activity in activities:
                activity_name = activity.get("name")
                activity_slug = activity.get("slug")
                if activity_name and activity_slug:
                    # Create sensor description for this health activity. The
                    # slugs AccuWeather publishes today are translated; anything
                    # new keeps the name the site itself returned.
                    slug_key = activity_slug.replace("-", "_")
                    if activity_slug in HEALTH_TRANSLATED_SLUGS:
                        health_desc = SensorEntityDescription(
                            key=f"health_{slug_key}",
                            translation_key=f"health_{slug_key}",
                            icon=get_health_icon(activity_slug),
                        )
                    else:
                        health_desc = SensorEntityDescription(
                            key=f"health_{slug_key}",
                            name=activity_name,
                            icon=get_health_icon(activity_slug),
                        )
                    entities.append(
                        AccuWeatherHealthSensorEntity(
                            coordinator, health_desc, activity, names
                        )
                    )
                    health_count += 1

    _LOGGER.info("AccuWeather: Created %d health activity sensors", health_count)
    async_add_entities(entities, False)


class SensorNames(NamedTuple):
    """Names to show, and the English names entity ids are built from."""

    display: dict[str, str]
    object_id: dict[str, str]


async def _async_sensor_names(hass: HomeAssistant, language: str) -> dict[str, str]:
    """Read entity names for one language out of translations/<lang>.json."""
    prefix = f"component.{DOMAIN}.entity.sensor."
    suffix = ".name"
    # A language with no file of its own falls back to English in here, so an
    # unexpected value still produces readable names rather than raw keys.
    translations = await async_get_translations(hass, language, "entity", {DOMAIN})
    return {
        key[len(prefix):-len(suffix)]: value
        for key, value in translations.items()
        if key.startswith(prefix) and key.endswith(suffix)
    }


async def async_name_overrides(
    hass: HomeAssistant, language: str
) -> SensorNames | None:
    """Sensor names in `language`, or None to let Home Assistant decide.

    Home Assistant names entities in the language set in Settings, which is also
    the language of the whole interface. Plenty of people run the interface in
    English and still want Vietnamese sensor names, so this option pins the
    names to one language on its own.

    Entity ids are a separate matter. Home Assistant only builds them from the
    local language for languages it can slugify safely, a list Vietnamese is not
    on, so a Vietnamese installation still gets English entity ids. Pinning the
    name alone would drag the entity id along with it and quietly break that
    rule, so the English name is kept for the id.
    """
    if language == SENSOR_LANGUAGE_AUTO:
        return None

    display = await _async_sensor_names(hass, language)
    object_id = (
        display
        if language == LANGUAGE_FOR_ENTITY_IDS
        else await _async_sensor_names(hass, LANGUAGE_FOR_ENTITY_IDS)
    )
    return SensorNames(display=display, object_id=object_id)


def watched_landfalls(storms: dict[str, Any]) -> list[dict[str, Any]]:
    """Every storm whose track reaches the coast being watched, soonest first.

    Which coast that is comes from the landfall country chosen when the entry
    was set up. More than one storm can be heading for the same country, so
    this returns all of them rather than the first one found.

    Crossings still to come are ordered by arrival time and come before ones
    that have already happened, which are ordered most recent first. A storm
    that has just landed is still the weather, but it is not the one to warn
    about while another is inbound.

    Only the storms close enough to have their track fetched — STORM_SLOTS of
    them — carry a landfall estimate at all, which is the practical limit on
    how far ahead this can look.
    """
    forecast: list[dict[str, Any]] = []
    past: list[dict[str, Any]] = []
    for storm in storms.get("storms") or ():
        landfall = storm.get("landfall_watched")
        if not landfall:
            continue
        (past if landfall.get("status") == "past" else forecast).append(storm)

    # ISO timestamps sort correctly as text. A crossing with no time sorts last
    # among the forecasts and first among the past ones, which in both cases
    # keeps it behind every crossing that does carry one.
    forecast.sort(key=lambda s: str(s["landfall_watched"].get("time") or "9999"))
    past.sort(key=lambda s: str(s["landfall_watched"].get("time") or ""), reverse=True)
    return forecast + past


def watched_landfall(storms: dict[str, Any]) -> dict[str, Any] | None:
    """The storm coming ashore soonest on the coast being watched.

    Not the nearest one: a faster storm further out can reach the coast first,
    and that is the one a warning is about.
    """
    inbound = watched_landfalls(storms)
    return inbound[0] if inbound else None


def landfall_summary(storm: dict[str, Any]) -> dict[str, Any]:
    """One storm's crossing of the watched coast, flattened for a card."""
    landfall = storm.get("landfall_watched") or {}
    return {
        "name": storm.get("name"),
        "headline": storm_headline(storm),
        "province": landfall.get("province"),
        "time": landfall.get("time"),
        "time_text": landfall.get("time_text"),
        "hours_away": landfall.get("hours_away"),
        "status": landfall.get("status"),
        "model": landfall.get("model"),
        "beaufort": landfall.get("beaufort"),
        "models_agreeing": landfall.get("models_agreeing"),
        "models_total": landfall.get("models_total"),
        "spread_km": landfall.get("spread_km"),
        "spread_hours": landfall.get("spread_hours"),
        "places": landfall.get("places"),
        "distance_to_landfall_km": landfall.get("distance_from_storm_km"),
        "landfall_distance_from_home_km": landfall.get("distance_from_home_km"),
        "text": storm.get("landfall_watched_text"),
    }


def landfall_attributes(
    landfall: dict[str, Any] | None, language: str
) -> dict[str, Any]:
    """Flatten one landfall estimate into attributes a card can read directly.

    The nested mapping stays as it is for anyone already using it; these are the
    same figures one level up, where a template can reach them without an
    existence check on every step.
    """
    landfall = landfall or {}
    return {
        # "past" once the storm has come ashore, "forecast" while it is still
        # heading in, absent when nothing on its track reaches the coast.
        "landfall_status": landfall.get("status"),
        # Which country the storm comes ashore in, in the sensor language.
        "landfall_country": place_name(landfall.get("country"), language),
        "landfall_province": landfall.get("province"),
        "landfall_time": landfall.get("time"),
        "landfall_time_text": landfall.get("time_text"),
        "landfall_beaufort": landfall.get("beaufort"),
        "landfall_wind_speed_kmh": landfall.get("wind_speed_kmh"),
        "landfall_model": landfall.get("model"),
        # How much the forecast models disagree about this same landfall, which
        # is the honest measure of how much to trust the place and the hour
        # above. Present only on the watched-coast estimate, where every model
        # is checked rather than only the most trusted one that reaches land.
        "landfall_models": landfall.get("models"),
        "landfall_models_agreeing": landfall.get("models_agreeing"),
        "landfall_models_total": landfall.get("models_total"),
        "landfall_spread_km": landfall.get("spread_km"),
        "landfall_spread_hours": landfall.get("spread_hours"),
        # Every stretch of coast the models name, so a card can show the range
        # rather than the single most-trusted answer.
        "landfall_places": landfall.get("places"),
        # How much further the storm has to travel, and how long that leaves.
        "distance_to_landfall_km": landfall.get("distance_from_storm_km"),
        "hours_to_landfall": landfall.get("hours_away"),
        # A different distance: from the configured location to the landfall
        # point. This one says whether the storm is coming for you. Every storm
        # sensor carries the figure; only the nearest-storm sensor says it out
        # loud in its state.
        "landfall_distance_from_home_km": landfall.get("distance_from_home_km"),
    }


class AccuWeatherNameMixin:
    """Applies the name language chosen in the options, if any.

    With no override the entity keeps Home Assistant's own behaviour: the name
    comes from the translation key, in the language from Settings.
    """

    # The displayed name is the device name plus the entity name, which is what
    # makes the entity name translatable at all.
    _attr_has_entity_name = True
    # English name, used for the entity id only. None means "leave it to Home
    # Assistant", which is the case whenever no language is pinned.
    _object_id_name: str | None = None

    def _apply_names(
        self,
        names: SensorNames | None,
        translation_key: str | None,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        """Pin the visible name, keeping the English one for the entity id."""
        if not names or not translation_key:
            return
        if display := names.display.get(translation_key):
            self._attr_name = (
                display.format(**placeholders) if placeholders else display
            )
        if object_id := names.object_id.get(translation_key):
            self._object_id_name = (
                object_id.format(**placeholders) if placeholders else object_id
            )

    @property
    def suggested_object_id(self) -> str | None:
        """Build the entity id from the English name when one is pinned."""
        if self._object_id_name:
            return self._object_id_name
        return super().suggested_object_id  # type: ignore[misc]


# Health activity slugs that have a name in translations/<lang>.json. A slug
# outside this set falls back to the name AccuWeather returned, so a new index
# still gets a sensor instead of a blank label.
HEALTH_TRANSLATED_SLUGS: frozenset[str] = frozenset({
    "asthma", "arthritis", "migraine", "dust-dander", "common-cold", "flu",
    "sinus", "running", "hiking", "biking", "golf", "sun-sand", "astronomy",
    "fishing", "air-travel", "driving", "lawn-mowing", "composting",
    "mosquito-activity", "indoor-pests", "outdoor-pests",
    "outdoor-entertaining",
})


def get_health_icon(slug: str) -> str:
    """Get icon for health activity based on slug."""
    icon_map = {
        "asthma": "mdi:lungs",
        "arthritis": "mdi:bone",
        "migraine": "mdi:head-outline", 
        "dust-dander": "mdi:air-filter",
        "common-cold": "mdi:account-alert",
        "flu": "mdi:account-alert",
        "sinus": "mdi:head-outline",
        "running": "mdi:run",
        "hiking": "mdi:hiking",
        "biking": "mdi:bike",
        "golf": "mdi:golf",
        "sun-sand": "mdi:pool",
        "astronomy": "mdi:telescope",
        "fishing": "mdi:fish",
        "air-travel": "mdi:airplane",
        "driving": "mdi:car",
        "lawn-mowing": "mdi:grass",
        "composting": "mdi:compost",
        "mosquito-activity": "mdi:bug",
        "indoor-pests": "mdi:home-variant",
        "outdoor-pests": "mdi:bug-outline",
        "outdoor-entertaining": "mdi:party-popper",
    }
    return icon_map.get(slug, "mdi:information")


class AccuWeatherSensorEntity(
    AccuWeatherNameMixin,
    CoordinatorEntity[AccuWeatherDataUpdateCoordinator],
    SensorEntity,
):
    """Implementation of AccuWeather sensor entity."""

    def __init__(
        self,
        coordinator: AccuWeatherDataUpdateCoordinator,
        description: SensorEntityDescription,
        names: SensorNames | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._apply_names(names, description.translation_key)
        self._attr_unique_id = f"accuweather_{coordinator.location_key}_{description.key}"
        self._attr_device_info = get_device_info(coordinator.location_key, coordinator.location_name)

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        
        key = self.entity_description.key
        
        # Current weather sensors
        if "current" in self.coordinator.data:
            current = self.coordinator.data["current"]

            if key == "realfeel_temperature":
                realfeel = current.get("realfeel")
                if realfeel:
                    match = re.search(r"(-?\d+)", str(realfeel))
                    if match:
                        return float(match.group(1))
                return current.get("temperature")
                
            elif key == "realfeel_shade_temperature":
                realfeel_shade = current.get("realfeel_shade")
                if realfeel_shade:
                    match = re.search(r"(-?\d+)", str(realfeel_shade))
                    if match:
                        return float(match.group(1))
                return None
                
            elif key == "humidity":
                return current.get("humidity")
            elif key == "pressure":
                return current.get("pressure")
            elif key == "wind_speed":
                return current.get("wind_speed")
            elif key == "wind_bearing":
                # Converted from Vietnamese initials while parsing.
                return current.get("wind_bearing_text")
            elif key == "visibility":
                return current.get("visibility")
            elif key == "cloud_coverage":
                return current.get("cloud_coverage")
            elif key == "uv_index":
                return current.get("uv_index")
            elif key == "heat_index":
                return current.get("heat_index")
            elif key in ("sunrise", "sunset", "moon_phase"):
                return current.get(key)
            elif key == "dew_point":
                # Read out of the details table by the parser, which knows the
                # labels in every language it fetches and converts °F and feet.
                return current.get("dew_point")
            elif key == "wind_gust":
                return current.get("wind_gust_speed")
            elif key == "cloud_ceiling":
                return current.get("cloud_ceiling")
        
        # Air quality sensors
        if "air_quality" in self.coordinator.data:
            air_data = self.coordinator.data["air_quality"]

            if key == "aqi":
                return air_data.get("aqi")
            if key == "aqi_category":
                return air_data.get("category")

            # Individual pollutants
            pollutants = air_data.get("pollutants", {})

            if key in _POLUTANT_KEY_MAP and _POLUTANT_KEY_MAP[key] in pollutants:
                pollutant_data = pollutants[_POLUTANT_KEY_MAP[key]]
                value = pollutant_data.get("value")
                if value:
                    try:
                        float_value = float(value)
                        return float_value
                    except (ValueError, TypeError):
                        return None
        
        # MinuteCast sensor
        if key == "minutecast":
            unavailable = text(
                self.coordinator.language, "minutecast_unavailable"
            )
            minutecast = self.coordinator.data.get("minutecast")
            if minutecast is not None:
                return minutecast.get("summary", unavailable)
            return unavailable
        
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return {}
        
        attrs = {
            "location_key": self.coordinator.location_key,
        }
        
        # Add current weather update time
        if "current" in self.coordinator.data:
            current = self.coordinator.data["current"]
            attrs["last_update"] = current.get("time")
        
        # Add air quality details
        if "air_quality" in self.coordinator.data and \
                self.entity_description.key.startswith(
                    ("pm25", "pm10", "ozone", "nitrogen", "sulfur", "carbon")):
            air_data = self.coordinator.data["air_quality"]
            attrs.update({
                "description": air_data.get("description"),
                "category": air_data.get("category"),
                "aqi": air_data.get("aqi"),
            })
            
            # Add specific pollutant details
            pollutants = air_data.get("pollutants", {})
            key = self.entity_description.key
            if key in _POLUTANT_KEY_MAP and _POLUTANT_KEY_MAP[key] in pollutants:
                pollutant_data = pollutants[_POLUTANT_KEY_MAP[key]]
                attrs.update({
                    "aqi": pollutant_data.get("aqi"),
                    "unit": pollutant_data.get("unit"),
                })
        
        # Add MinuteCast details
        if self.entity_description.key == "minutecast":
            minutecast = self.coordinator.data.get("minutecast")
            if minutecast is not None:
                attrs.update({
                    "current_temperature": minutecast.get("current_temperature"),
                    "current_condition": minutecast.get("current_condition"),
                    "realfeel": minutecast.get("realfeel"),
                    "current_time": minutecast.get("current_time"),
                    "forecast_type": minutecast.get("forecast_type"),
                })
        
        return attrs


class AccuWeatherBulletinSensor(
    AccuWeatherNameMixin,
    CoordinatorEntity[AccuWeatherDataUpdateCoordinator],
    SensorEntity,
):
    """The latest hazardous-weather bulletin from Việt Nam's forecast centre.

    The state is the headline and then the opening paragraph, because neither
    alone is enough. The headline says what kind of warning this is; the
    paragraph says where the storm is, how strong it has become and which way
    it is going, and it usually opens on a section heading like "1. Hiện trạng
    đã qua:" that names nothing.

    Both go in the state rather than one going in an attribute because recent
    Home Assistant versions dropped the attribute list from the more-info
    dialog: clicking the entity shows history and the logbook and nothing else,
    so an attribute is only reachable from Developer Tools or a template. An
    attribute nobody can see is not an answer.

    What will not fit in a state is trimmed here and nowhere else: `title` and
    `summary` keep their own text whole, and `content` carries the entire
    bulletin, for a Markdown card or a template that has room for them.

    Deliberately not a count: the page keeps months of old bulletins below the
    current ones, so the number barely moves and would never trigger anything.
    Either the state or the `issued` attribute changes with every new bulletin,
    so an automation still has something to act on.
    """

    _attr_icon = "mdi:bullhorn-variant"

    def __init__(
        self,
        coordinator: AccuWeatherDataUpdateCoordinator,
        names: SensorNames | None = None,
    ) -> None:
        """Initialize the national bulletin sensor."""
        super().__init__(coordinator)
        self.entity_description = SensorEntityDescription(
            key="nchmf_bulletin",
            translation_key="nchmf_bulletin",
            icon="mdi:bullhorn-variant",
        )
        self._apply_names(names, "nchmf_bulletin")
        self._attr_unique_id = (
            f"accuweather_{coordinator.location_key}_nchmf_bulletin"
        )
        self._attr_device_info = get_device_info(
            coordinator.location_key, coordinator.location_name
        )

    @property
    def _bulletins(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("bulletins") or {}

    @property
    def native_value(self) -> str | None:
        """The headline of the most recent bulletin, and what it says.

        Either half on its own leaves a question: the headline does not say
        where the storm is, and the paragraph does not say what kind of warning
        it belongs to. Whichever half is missing, the other stands alone — the
        list page and the bulletin page are separate requests, and one failing
        does not mean the other did.
        """
        latest = self._bulletins.get("latest") or {}
        parts = [part for part in (latest.get("title"), latest.get("summary")) if part]
        if not parts:
            return text(self.coordinator.language, "bulletin_none")

        value = " — ".join(parts)
        # Home Assistant refuses a state over 255 characters and drops the
        # entity rather than truncating, so the trimming happens here, on a
        # word boundary. The headline comes first so it always survives; the
        # `summary` attribute keeps the paragraph whole either way.
        if len(value) <= MAX_STATE_LENGTH:
            return value
        return value[: MAX_STATE_LENGTH - 1].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The bulletin list, and what the newest one is about."""
        bulletins = self._bulletins
        latest = bulletins.get("latest") or {}
        attrs: dict[str, Any] = {
            # The headline. The state carries the paragraph instead, because
            # that is the half worth reading, but the headline is what names
            # the kind of warning, so it stays reachable for templates.
            "title": latest.get("title"),
            "issued": latest.get("issued"),
            "issued_text": latest.get("issued_text"),
            "url": latest.get("url"),
            # What the bulletin actually says. The headline names the hazard;
            # only the body says where the storm is, how strong it has become
            # and which provinces are in the way. `summary` is the opening
            # paragraph, sized for a dashboard tile; `content` is the whole
            # text with the forecast tables marked but not inlined.
            "summary": latest.get("summary") or "",
            "content": latest.get("content") or "",
            # The official PDF of the bulletin, when the page links one.
            "pdf_url": latest.get("pdf_url"),
            # "bão", "lũ", "biển", "mưa", "nắng nóng", "rét" or "khác", so an
            # automation can act on storms alone.
            "category": latest.get("category"),
            # The official Vietnamese storm number, which the Windy feed never
            # carries: it names storms internationally (Kajiki) while the
            # bulletins number them by basin entry (bão số 4).
            "storm_number": latest.get("storm_number"),
            "count": bulletins.get("count", 0),
            # How many were issued in the last day. The page keeps a long tail
            # of old bulletins, so this is what tells an active spell from a
            # quiet one.
            "recent_count": bulletins.get("recent_count", 0),
            "bulletins": bulletins.get("bulletins") or [],
            "source": bulletins.get("source") or NCHMF_URL,
        }
        if bulletins.get("stale"):
            # The site was unreachable; this is the last list that arrived.
            attrs["stale"] = True
        return attrs


class AccuWeatherStormSummarySensor(
    AccuWeatherNameMixin,
    CoordinatorEntity[AccuWeatherDataUpdateCoordinator],
    SensorEntity,
):
    """Summary of the tropical cyclone situation from Windy."""

    def __init__(
        self,
        coordinator: AccuWeatherDataUpdateCoordinator,
        description: SensorEntityDescription,
        names: SensorNames | None = None,
    ) -> None:
        """Initialize the storm summary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._apply_names(names, description.translation_key)
        self._attr_unique_id = f"accuweather_{coordinator.location_key}_{description.key}"
        self._attr_device_info = get_device_info(
            coordinator.location_key, coordinator.location_name
        )

    @property
    def _data(self) -> dict[str, Any]:
        """Coordinator data, or an empty mapping before the first update."""
        return self.coordinator.data or {}

    @property
    def _storms(self) -> dict[str, Any]:
        return self._data.get("storms") or {}

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        key = self.entity_description.key
        storms = self._storms
        nearest = storms.get("nearest") or {}

        if key == "storm_count":
            return storms.get("count", 0)
        if key == "storm_nearby_count":
            return storms.get("nearby_count", 0)
        if key == "storm_nearest_distance":
            return nearest.get("distance_km")
        if key == "storm_nearest_beaufort":
            return nearest.get("beaufort")
        language = self.coordinator.language
        if key == "storm_movement":
            if not nearest:
                return text(language, "no_storm")
            return nearest.get("movement_text") or text(
                language, "movement_unknown"
            )
        if key == "storm_landfall":
            if not nearest:
                return text(language, "no_storm")
            # Only a landfall on the coast being watched is reported here: a
            # storm heading elsewhere is somebody else's warning, and saying
            # nothing is the useful answer. The line names the storm and
            # carries the distance from the configured location, which is what
            # makes it readable on its own.
            inbound = watched_landfall(storms)
            country = place_name(self.coordinator.landfall_country, language)
            if not inbound:
                return text(language, "landfall_none_country", country=country)
            return inbound.get("landfall_watched_text") or text(
                language, "landfall_unknown"
            )
        if key == "weather_alerts":
            return len(self._data.get("alerts") or [])
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        key = self.entity_description.key
        storms = self._storms
        attrs: dict[str, Any] = {"location_key": self.coordinator.location_key}
        if storms.get("stale"):
            # Windy was unreachable; these are the last figures that arrived.
            attrs["stale"] = True

        if key == "weather_alerts":
            attrs["alerts"] = self._data.get("alerts") or []
            return attrs

        if key in ("storm_count", "storm_nearby_count"):
            # Every active system, closest first, so a card can list them all.
            attrs["storms"] = [
                {
                    "name": storm.get("name"),
                    "distance_km": storm.get("distance_km"),
                    "direction_from_home": storm.get("direction_from_home"),
                    "wind_speed_kmh": storm.get("wind_speed_kmh"),
                    "beaufort": storm.get("beaufort"),
                    "classification": storm.get("classification"),
                    "movement": storm.get("movement_text"),
                    "landfall": storm.get("landfall_text"),
                    "landfall_status": (storm.get("landfall") or {}).get("status"),
                    "landfall_province": (storm.get("landfall") or {}).get("province"),
                    "distance_to_landfall_km": (
                        (storm.get("landfall") or {}).get("distance_from_storm_km")
                    ),
                    "landfall_distance_from_home_km": (
                        (storm.get("landfall") or {}).get("distance_from_home_km")
                    ),
                }
                for storm in storms.get("storms", [])
            ]
            return attrs

        if key == "storm_landfall":
            # The state only speaks about a landfall on the watched coast, so
            # this has to be the storm that state is about — the one ashore
            # soonest, not necessarily the nearest — and that crossing rather
            # than wherever the storm first met land.
            inbound = watched_landfalls(storms)
            storm = inbound[0] if inbound else {}
            landfall = storm.get("landfall_watched")
            # Both always present, so a card can hide the row without reading
            # the sentence, and can name the coast being watched.
            attrs["watched_country"] = place_name(
                self.coordinator.landfall_country, self.coordinator.language
            )
            attrs["landfall_in_country"] = bool(landfall)
            # The state has room for one storm. In a busy season more than one
            # can be heading for the same coast, and a card or an automation
            # reading only the sentence would never learn about the second.
            attrs["landfall_count"] = len(inbound)
            attrs["landfall_storms"] = [landfall_summary(s) for s in inbound]
            # Estimates held back for being both more than LANDFALL_HORIZON_HOURS
            # off and more than LANDFALL_RANGE_KM away. Kept visible so the
            # sensor going quiet is legible rather than mysterious, but out of
            # the sentence, which should not name a province and an hour on the
            # strength of one model's guess about next week.
            distant = [
                s for s in storms.get("storms") or ()
                if s.get("landfall_watched_beyond")
            ]
            attrs["landfall_beyond_horizon"] = [
                {
                    "name": s.get("name"),
                    "province": (s["landfall_watched_beyond"]).get("province"),
                    "time_text": (s["landfall_watched_beyond"]).get("time_text"),
                    "hours_away": (s["landfall_watched_beyond"]).get("hours_away"),
                    "distance_to_landfall_km": (
                        (s["landfall_watched_beyond"]).get("distance_from_storm_km")
                    ),
                    "models_agreeing": (
                        (s["landfall_watched_beyond"]).get("models_agreeing")
                    ),
                    "models_total": (
                        (s["landfall_watched_beyond"]).get("models_total")
                    ),
                }
                for s in distant
            ]
            # Which storms are inside the watched country's waters right now —
            # a 200-nautical-mile stand-in for its exclusive economic zone.
            attrs["storms_in_maritime_zone"] = [
                {
                    "name": s.get("name"),
                    "distance_to_coast_km": s.get("distance_to_watched_coast_km"),
                }
                for s in storms.get("storms") or ()
                if s.get("in_maritime_zone")
            ]
            attrs["landfall_horizon_hours"] = LANDFALL_HORIZON_HOURS
            attrs["landfall_range_km"] = LANDFALL_RANGE_KM
        else:
            storm = storms.get("nearest") or {}
            landfall = storm.get("landfall")

        if storm:
            attrs.update({
                "name": storm.get("name"),
                "latitude": storm.get("latitude"),
                "longitude": storm.get("longitude"),
                "distance_km": storm.get("distance_km"),
                "direction_from_home": storm.get("direction_from_home"),
                "wind_speed_kmh": storm.get("wind_speed_kmh"),
                "beaufort": storm.get("beaufort"),
                "classification": storm.get("classification"),
                "movement_direction": storm.get("movement_direction"),
                "movement_speed_kmh": storm.get("movement_speed_kmh"),
                "nearest_coast": storm.get("nearest_coast"),
                "distance_to_coast_km": storm.get("distance_to_coast_km"),
                "landfall": landfall,
            })
            attrs.update(landfall_attributes(landfall, self.coordinator.language))
        return attrs


class AccuWeatherStormSensor(
    AccuWeatherNameMixin,
    CoordinatorEntity[AccuWeatherDataUpdateCoordinator],
    SensorEntity,
):
    """One active tropical cyclone, ordered by distance from the location."""

    _attr_icon = "mdi:weather-hurricane"

    def __init__(
        self,
        coordinator: AccuWeatherDataUpdateCoordinator,
        slot: int,
        names: SensorNames | None = None,
    ) -> None:
        """Initialize a storm slot sensor."""
        super().__init__(coordinator)
        self._slot = slot
        self.entity_description = SensorEntityDescription(
            key=f"storm_{slot + 1}",
            translation_key="storm_slot",
            icon="mdi:weather-hurricane",
        )
        # One translated name shared by every slot, numbered by placeholder.
        placeholders = {"number": str(slot + 1)}
        self._attr_translation_placeholders = placeholders
        self._apply_names(names, "storm_slot", placeholders)
        self._attr_unique_id = (
            f"accuweather_{coordinator.location_key}_storm_{slot + 1}"
        )
        self._attr_device_info = get_device_info(
            coordinator.location_key, coordinator.location_name
        )

    @property
    def _storm(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        storms = (self.coordinator.data.get("storms") or {}).get("storms") or []
        if self._slot >= len(storms):
            return None
        return storms[self._slot]

    @property
    def native_value(self) -> Any:
        """Read out the storm the way a Vietnamese bulletin would.

        Intensity wording, name, Beaufort force, how far away and which way it
        is going — the figures worth seeing without opening the attributes.
        """
        storm = self._storm
        language = self.coordinator.language
        if not storm:
            return text(language, "no_storm")
        if summary := storm.get("summary_text"):
            return summary

        # Storms outside the detailed set have no track, so only the headline
        # from the storm list is available for them.
        name = storm.get("name") or "?"
        classification = storm.get("classification")
        beaufort = storm.get("beaufort")
        headline = f"{classification} {name}" if classification else name
        if not beaufort:
            return headline
        return text(language, "storm_force", headline=headline, beaufort=beaufort)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return everything known about this storm."""
        storm = self._storm
        if not storm:
            return {"location_key": self.coordinator.location_key}

        attrs: dict[str, Any] = {
            "location_key": self.coordinator.location_key,
            "name": storm.get("name"),
            "latitude": storm.get("latitude"),
            "longitude": storm.get("longitude"),
            "distance_km": storm.get("distance_km"),
            "direction_from_home": storm.get("direction_from_home"),
            "wind_speed_kmh": storm.get("wind_speed_kmh"),
            "beaufort": storm.get("beaufort"),
            "classification": storm.get("classification"),
            "pressure_hpa": storm.get("pressure_hpa"),
            "observed_at": storm.get("observed_at"),
            "observed_at_text": storm.get("observed_at_text"),
            "movement": storm.get("movement_text"),
            "movement_direction": storm.get("movement_direction"),
            "movement_speed_kmh": storm.get("movement_speed_kmh"),
            "landfall": storm.get("landfall_text"),
            "landfall_details": storm.get("landfall"),
            "nearest_coast": storm.get("nearest_coast"),
            "distance_to_coast_km": storm.get("distance_to_coast_km"),
            "forecast_models": storm.get("forecast_models"),
            **landfall_attributes(storm.get("landfall"), self.coordinator.language),
        }

        # Trim the tracks: full history can run to 56 points per storm, and
        # everything here is written to the state machine on every update.
        if history := storm.get("history"):
            attrs["track_history"] = history[:STORM_TRACK_POINTS]
        forecast = storm.get("forecast") or {}
        models = storm.get("forecast_models") or []
        # Same trust order as the landfall estimate, so the track shown and the
        # landfall text describe the same forecast.
        ordered = [m for m in LANDFALL_MODEL_PRIORITY if m in models]
        ordered += [m for m in models if m not in ordered]
        for model in ordered:
            track = (forecast.get(model) or {}).get("track") or []
            if track:
                attrs["track_forecast_model"] = model
                attrs["track_forecast"] = track[:STORM_TRACK_POINTS]
                break
        return attrs


class AccuWeatherHealthSensorEntity(
    AccuWeatherNameMixin,
    CoordinatorEntity[AccuWeatherDataUpdateCoordinator],
    SensorEntity,
):
    """Implementation of AccuWeather health activity sensor entity."""

    def __init__(
        self,
        coordinator: AccuWeatherDataUpdateCoordinator,
        description: SensorEntityDescription,
        activity_data: dict[str, Any],
        names: SensorNames | None = None,
    ) -> None:
        """Initialize the health sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._activity_data = activity_data
        self._apply_names(names, description.translation_key)
        self._attr_unique_id = f"accuweather_{coordinator.location_key}_{description.key}"
        self._attr_device_info = get_device_info(coordinator.location_key, coordinator.location_name)

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data or "health_activities" not in self.coordinator.data:
            return None
        
        health_data = self.coordinator.data["health_activities"]
        activity_slug = self._activity_data.get("slug")
        unknown = text(self.coordinator.language, "health_unknown")

        # Find current activity data
        for group_activities in health_data.values():
            for activity in group_activities:
                if activity.get("slug") == activity_slug:
                    # Return localized category instead of raw value. The page
                    # localises it for us, into the language it was fetched in.
                    return activity.get(
                        "localizedCategory", activity.get("category", unknown)
                    )

        return unknown

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        if not self.coordinator.data or "health_activities" not in self.coordinator.data:
            return {}
        
        health_data = self.coordinator.data["health_activities"]
        activity_slug = self._activity_data.get("slug")
        
        # Find current activity data
        for group_activities in health_data.values():
            for activity in group_activities:
                if activity.get("slug") == activity_slug:
                    return {
                        "location_key": self.coordinator.location_key,
                        "raw_value": activity.get("value"),
                        "category_value": activity.get("categoryValue"),
                        "phrase": activity.get("categoryPhrase"),
                        "status_color": activity.get("statusColor"),
                        "localized_name": activity.get("localizedName"),
                        "index_date": activity.get("indexDate"),
                    }
        
        return {"location_key": self.coordinator.location_key}
