"""Windy.com data sources: tropical cyclone tracking, alerts and map images.

Windy's public storm feed (node.windy.com/tc/v2/storms) merges the official
regional agencies — JMA for the northwest Pacific, NOAA NHC for the Atlantic and
eastern Pacific, BoM, UKMO, IMD — with Windy's own automatic detection on the
ECMWF, GFS and ICON models, so depressions show up before they are named. It
needs no API key.

Windy's paid Point Forecast API is deliberately not used: its free tier serves
"randomly shuffled and slightly modified data" and is documented as development
only, which is worse than no data at all.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from time import monotonic
from typing import Any

import aiohttp
from homeassistant.util import dt as dt_util

from .coastline import COASTAL_POINTS
from .const import (
    CARDINAL_NAMES,
    COAST_LOOKUP_MAX_KM,
    COUNTRY_NAME_EN,
    DEFAULT_LANDFALL_COUNTRY,
    LANDFALL_MODEL_PRIORITY,
    LANDFALL_OBSERVED_KM,
    LANDFALL_RECENT_HOURS,
    LANDFALL_THRESHOLD_KM,
    STORM_NEARBY_RADIUS_KM,
    STORM_SLOTS,
    VIETNAM,
    VIETNAM_COAST,
    WINDY_ALERTS_URL,
    WINDY_STORMS_URL,
    WIND_DIRECTION_EN,
)
from .i18n import FALLBACK_LANGUAGE, text

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=25)

# Shared response cache: {url: (fetched_at, payload)}. Storm data is identical
# for every configured location, and storms move on a scale of hours.
_CACHE: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 240.0  # seconds

# Shape returned when Windy has nothing to say, or is unreachable. "available"
# separates the two: a quiet basin is a real answer, an unreachable endpoint is
# not, and reporting "no storms" for the latter would be a dangerous kind of
# wrong.
EMPTY_STORMS: dict[str, Any] = {
    "count": 0,
    "nearby_count": 0,
    "storms": [],
    "nearest": None,
    "available": False,
}

# Beaufort force -> lower bound in m/s. Vietnam reports cyclones on this scale,
# so it is more useful locally than the Saffir-Simpson categories.
_BEAUFORT_MIN_MS: tuple[tuple[int, float], ...] = (
    (17, 56.1), (16, 51.0), (15, 46.2), (14, 41.5), (13, 37.0), (12, 32.7),
    (11, 28.5), (10, 24.5), (9, 20.8), (8, 17.2), (7, 13.9), (6, 10.8),
    (5, 8.0), (4, 5.5), (3, 3.4), (2, 1.6), (1, 0.3),
)


def beaufort_force(wind_ms: float | None) -> int | None:
    """Return the Beaufort force for a wind speed in m/s."""
    if wind_ms is None:
        return None
    for force, lower in _BEAUFORT_MIN_MS:
        if wind_ms >= lower:
            return force
    return 0


def classify_storm(
    wind_ms: float | None, language: str = FALLBACK_LANGUAGE
) -> str | None:
    """Describe a cyclone's intensity the way Vietnamese forecasts do.

    The bands are the Beaufort ones Vietnamese bulletins use; the English
    wording names the same bands rather than switching to Saffir-Simpson, so
    that a sensor says the same thing in either language.
    """
    force = beaufort_force(wind_ms)
    if force is None:
        return None
    if force >= 16:
        key = "storm_class_super"
    elif force >= 12:
        key = "storm_class_very_strong"
    elif force >= 10:
        key = "storm_class_strong"
    elif force >= 8:
        key = "storm_class_typhoon"
    elif force >= 6:
        key = "storm_class_depression"
    else:
        key = "storm_class_low"
    return text(language, key)


def place_name(name: str | None, language: str) -> str | None:
    """A coastal name in `language`.

    coastline.py names countries in Vietnamese, because that is what the
    generator writes. Vietnamese provinces are proper nouns and read the same
    either way, so they fall through untouched.
    """
    if not name or language == "vi":
        return name
    return COUNTRY_NAME_EN.get(name, name)


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return round(2 * radius * math.asin(math.sqrt(a)), 1)


def bearing_to(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, str]:
    """Initial bearing from point 1 to point 2, as degrees and a cardinal."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    degrees = (math.degrees(math.atan2(y, x)) + 360) % 360

    cardinal = min(
        WIND_DIRECTION_EN.items(),
        key=lambda item: min(abs(degrees - item[1]), 360 - abs(degrees - item[1])),
    )[0]
    return round(degrees, 1), cardinal


def _movement_from_history(
    history: list[dict[str, Any]], language: str = FALLBACK_LANGUAGE
) -> dict[str, Any]:
    """Work out which way the storm is travelling, and how fast.

    The feed has no heading field, so it is derived from the two most recent
    track points (newest first). The bearing is where the storm is going — the
    opposite convention from wind direction, which names where wind comes from.
    """
    points = [
        p for p in history
        if p.get("latitude") is not None and p.get("longitude") is not None
    ]
    if len(points) < 2:
        return {}

    newest, previous = points[0], points[1]
    degrees, cardinal = bearing_to(
        previous["latitude"], previous["longitude"],
        newest["latitude"], newest["longitude"],
    )
    direction = CARDINAL_NAMES[language].get(cardinal, cardinal)

    travelled = distance_km(
        previous["latitude"], previous["longitude"],
        newest["latitude"], newest["longitude"],
    )

    speed_kmh = None
    try:
        t_new = datetime.fromisoformat(str(newest.get("time")))
        t_old = datetime.fromisoformat(str(previous.get("time")))
        hours = (t_new - t_old).total_seconds() / 3600
        if hours > 0:
            speed_kmh = round(travelled / hours, 1)
    except (TypeError, ValueError):
        _LOGGER.debug("Windy storm history has unparsable timestamps")

    movement = {
        "movement_direction": direction,
        "movement_direction_en": cardinal,
        "movement_bearing": degrees,
        "movement_speed_kmh": speed_kmh,
    }
    movement["movement_text"] = (
        text(language, "movement_with_speed", direction=direction, speed=speed_kmh)
        if speed_kmh is not None
        else text(language, "movement", direction=direction)
    )
    return movement


# Coastal points bucketed into whole cells of this many degrees. Scanning all
# 2716 of them for every track point — around 90 points per storm — took long
# enough to be felt inside the event loop; this cuts each lookup to a few dozen.
_GRID_DEGREES = 5
_COAST_GRID: dict[tuple[int, int], list[tuple[str, float, float]]] = {}


def _coast_grid() -> dict[tuple[int, int], list[tuple[str, float, float]]]:
    """Coastal points indexed by grid cell, built once on first use."""
    if not _COAST_GRID:
        for name, lat, lon in (*VIETNAM_COAST, *COASTAL_POINTS):
            cell = (int(lat // _GRID_DEGREES), int(lon // _GRID_DEGREES))
            _COAST_GRID.setdefault(cell, []).append((name, lat, lon))
    return _COAST_GRID


def nearest_coast(
    latitude: float, longitude: float
) -> tuple[str | None, float | None]:
    """Nearest named piece of land and its distance in km.

    Vietnamese landfalls are named by province, everywhere else by country. Land
    further than COAST_LOOKUP_MAX_KM away is reported as no land at all: the
    honest answer for a storm sitting in the middle of an ocean.
    """
    grid = _coast_grid()
    home_lat = int(latitude // _GRID_DEGREES)
    home_lon = int(longitude // _GRID_DEGREES)

    for radius in (1, 2, 4):
        window = [
            point
            for d_lat in range(-radius, radius + 1)
            for d_lon in range(-radius, radius + 1)
            for point in grid.get((home_lat + d_lat, home_lon + d_lon), ())
        ]
        if not window:
            continue
        # One pass, keeping the running best: min() with a key would measure
        # every point twice over, and this runs for every track point of every
        # storm on every update.
        name, best = None, None
        for candidate, lat, lon in window:
            measured = distance_km(latitude, longitude, lat, lon)
            if best is None or measured < best:
                name, best = candidate, measured
        # The window reaches at least `radius` whole cells in every direction,
        # so anything nearer than that span would have been inside it. Below
        # that bound the answer is certainly the nearest; above it, widen.
        certain_km = radius * _GRID_DEGREES * 111.0 * math.cos(math.radians(latitude))
        if best <= certain_km or radius == 4:
            if best > COAST_LOOKUP_MAX_KM:
                return None, None
            return name, best

    return None, None


# The Vietnamese names out of VIETNAM_COAST. Every other coastal point is
# already named after its country; these are the ones that are not.
_VIETNAM_PLACES = frozenset(name for name, _, _ in VIETNAM_COAST)


def _country_of(place: str | None) -> str | None:
    """Which country a coastal reference point belongs to."""
    if place is None:
        return None
    return VIETNAM if place in _VIETNAM_PLACES else place


# Margin added to each country's own bounding box. A track point further
# outside than this cannot be within the landfall threshold of that coast, and
# 2 degrees is about 220 km at these latitudes.
_BOX_MARGIN_DEGREES = 2.0

_COUNTRY_COAST: dict[str, list[tuple[str, float, float]]] = {}
_COUNTRY_BOX: dict[str, tuple[float, float, float, float]] = {}


def _by_country() -> dict[str, list[tuple[str, float, float]]]:
    """Coastal points grouped by country, with their boxes, built on first use."""
    if not _COUNTRY_COAST:
        for name, lat, lon in (*VIETNAM_COAST, *COASTAL_POINTS):
            _COUNTRY_COAST.setdefault(_country_of(name), []).append((name, lat, lon))
        for country, points in _COUNTRY_COAST.items():
            lats = [lat for _, lat, _ in points]
            lons = [lon for _, _, lon in points]
            _COUNTRY_BOX[country] = (
                min(lats) - _BOX_MARGIN_DEGREES,
                max(lats) + _BOX_MARGIN_DEGREES,
                min(lons) - _BOX_MARGIN_DEGREES,
                max(lons) + _BOX_MARGIN_DEGREES,
            )
    return _COUNTRY_COAST


def landfall_countries() -> tuple[str, ...]:
    """Every country whose coast a landfall can be reported for, sorted."""
    return tuple(sorted(_by_country()))


def nearest_coast_in(
    country: str, latitude: float, longitude: float
) -> tuple[str | None, float | None]:
    """Nearest point on one country's coast, and its distance in km.

    `nearest_coast` answers with whichever land is closest, which is China or
    the Philippines for plenty of points that are also within reach of Vietnam.
    This one only ever answers with the country asked for, so a typhoon
    crossing Luzon on its way to Quảng Trị still has a Vietnamese landfall to
    report. Vietnam comes back named by province, everywhere else by country.
    """
    points = _by_country().get(country)
    if not points:
        return None, None

    low_lat, high_lat, low_lon, high_lon = _COUNTRY_BOX[country]
    if not (low_lat <= latitude <= high_lat and low_lon <= longitude <= high_lon):
        return None, None

    name, best = None, None
    for candidate, lat, lon in points:
        measured = distance_km(latitude, longitude, lat, lon)
        if best is None or measured < best:
            name, best = candidate, measured
    return name, best


def _coast_crossing(
    track: list[dict[str, Any]],
    threshold_km: float,
    language: str = FALLBACK_LANGUAGE,
    country: str | None = None,
) -> dict[str, Any] | None:
    """First point of a track that comes within `threshold_km` of the coast.

    `country` narrows the search to one country's coast; without it the nearest
    land wins, whichever country that turns out to be.
    """
    for point in track:
        lat, lon = point.get("latitude"), point.get("longitude")
        if lat is None or lon is None:
            continue
        province, distance = (
            nearest_coast_in(country, lat, lon) if country
            else nearest_coast(lat, lon)
        )
        if distance is not None and distance <= threshold_km:
            return {
                "province": place_name(province, language),
                # Kept untranslated: this is the value the landfall country
                # option is set to, and it is compared against it.
                "country": _country_of(province),
                "distance_km": distance,
                "time": point.get("time"),
                "latitude": lat,
                "longitude": lon,
                "pressure_hpa": point.get("pressure_hpa"),
                "wind_speed_kmh": point.get("wind_speed_kmh"),
                "beaufort": beaufort_force(
                    point["wind_speed_kmh"] / 3.6
                    if point.get("wind_speed_kmh") is not None
                    else None
                ),
            }
    return None


def predict_landfall(
    forecasts: dict[str, dict[str, Any]],
    history: list[dict[str, Any]] | None = None,
    threshold_km: float = LANDFALL_THRESHOLD_KM,
    language: str = FALLBACK_LANGUAGE,
    country: str | None = None,
) -> dict[str, Any] | None:
    """Work out where a storm's track meets the coast, past or future.

    The observed track is checked first, oldest point first: a storm that has
    already come ashore must be reported as having done so, not as still
    approaching — its remaining forecast points sit inland, close to the coastal
    reference points, and would otherwise read as a landfall still to come.
    Failing that, forecast tracks are checked in agency-trust order and the
    first point reaching the coast is reported.

    The coast in question is whichever land is nearest — Vietnam by province,
    everywhere else in the basin by country. `country` narrows it to one
    country's coast: the same track then answers "where does this storm meet
    Thailand", which is a different question from "where does it first meet
    land" for every storm that crosses somewhere else on the way in.

    Either way this is an approximation from track points and coastal reference
    points: it names the stretch of coast involved, not an official bulletin.
    """
    if history:
        # Newest point first, so this finds the LAST time the storm was against
        # a coast rather than the first. A long-lived storm crosses more than
        # one country, and only the most recent crossing describes where it is.
        observed = sorted(
            history, key=lambda p: p.get("time") or "", reverse=True
        )
        hit = _coast_crossing(observed, LANDFALL_OBSERVED_KM, language, country)
        # An old crossing is history, not weather. Past that age the storm has
        # moved on and its forecast track is the thing worth reporting.
        if hit and (hours := hours_until(hit.get("time"))) is not None:
            if hours < -LANDFALL_RECENT_HOURS:
                hit = None
        if hit:
            hit["model"] = "observed"
            hit["status"] = "past"
            return hit

    ordered = [m for m in LANDFALL_MODEL_PRIORITY if m in forecasts]
    ordered += [m for m in sorted(forecasts) if m not in ordered]

    for model in ordered:
        # A forecast run starts at its reference time, which is already hours
        # old by the time it is published. Its opening points would otherwise
        # produce "dự kiến đổ bộ" at a moment that has been and gone.
        track = [
            point
            for point in (forecasts[model].get("track") or [])
            if (hours := hours_until(point.get("time"))) is None or hours > 0
        ]
        if hit := _coast_crossing(track, threshold_km, language, country):
            hit["model"] = model
            hit["status"] = "forecast"
            return hit
    return None


def local_time_text(raw: str | None) -> str | None:
    """Format a Windy timestamp as local time.

    Windy stamps everything in UTC; printing it unchanged reads as seven hours
    early in Vietnam, often on the wrong day.
    """
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return str(raw)
    return dt_util.as_local(stamp).strftime("%H:%M %d/%m")


def storm_headline(storm: dict[str, Any]) -> str:
    """What the storm is, plus its name: Bão Kajiki."""
    name = storm.get("name") or "?"
    classification = storm.get("classification")
    return f"{classification} {name}" if classification else name


def describe_storm(storm: dict[str, Any], language: str = FALLBACK_LANGUAGE) -> str:
    """One bulletin line for a single storm: what, where, which way, going in.

    The state of a storm sensor used to be the name alone, which left the
    interesting figures buried in attributes the dashboard does not show. The
    landfall clause here is deliberately the short form — the full sentence,
    with distances and forecast model, stays in the `landfall` attribute, and
    the state has a 255 character ceiling to respect.
    """
    headline = storm_headline(storm)
    if beaufort := storm.get("beaufort"):
        headline = text(
            language, "storm_force", headline=headline, beaufort=beaufort
        )
    parts = [headline]

    distance = storm.get("distance_km")
    direction = storm.get("direction_from_home")
    if distance is not None and direction:
        parts.append(
            text(
                language,
                "storm_distance_direction",
                km=round(distance),
                direction=direction,
            )
        )
    elif distance is not None:
        parts.append(text(language, "storm_distance", km=round(distance)))

    if movement := storm.get("movement_text"):
        # Mid-sentence now, so it loses the capital it was written with.
        parts.append(movement[0].lower() + movement[1:])

    line = ", ".join(parts)

    landfall = storm.get("landfall") or {}
    if province := landfall.get("province"):
        key = (
            "summary_landfall_past"
            if landfall.get("status") == "past"
            else "summary_landfall_forecast"
        )
        line = text(language, key, line=line, place=province)
        when = landfall.get("time_text") or local_time_text(landfall.get("time"))
        if when:
            line = text(language, "summary_landfall_time", line=line, when=when)

    # Home Assistant rejects a state longer than 255 characters, which would
    # take the whole sensor down rather than just truncate the text.
    return line[:255]


def hours_until(raw: str | None) -> float | None:
    """Hours from now until a Windy timestamp; negative once it has passed."""
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        # The feed stamps everything in UTC without saying so.
        stamp = stamp.replace(tzinfo=timezone.utc)
    return round((stamp - dt_util.utcnow()).total_seconds() / 3600, 1)


def describe_landfall(
    landfall: dict[str, Any] | None,
    heading_towards: str | None = None,
    distance_to_coast: float | None = None,
    from_home: bool = False,
    language: str = FALLBACK_LANGUAGE,
    storm_name: str | None = None,
) -> str:
    """One plain line about where the storm is going.

    Three situations, told apart by the track: the storm has already come
    ashore, it is forecast to, or nothing on its track reaches the coast.

    `from_home` adds how far the landfall point is from the configured
    location — the figure that says whether the storm is coming for you, rather
    than how far it still has to travel. It belongs on the "nearest storm"
    sensor and would only be noise repeated on every individual storm.

    `storm_name` opens the line with which storm this is. The per-storm sensors
    already say that in their own state, but the landfall sensor is read on its
    own, where an unnamed forecast leaves you guessing.
    """
    if not landfall:
        if heading_towards and distance_to_coast is not None:
            return text(
                language,
                "landfall_none_coast",
                place=heading_towards,
                km=round(distance_to_coast),
            )
        # No land within COAST_LOOKUP_MAX_KM: the storm is out in open ocean.
        return text(language, "landfall_none_offshore")

    when = local_time_text(landfall.get("time"))
    force = landfall.get("beaufort")
    home = landfall.get("distance_from_home_km") if from_home else None
    place = landfall["province"]
    past = landfall.get("status") == "past"

    if past:
        # "khu vực" is dropped: the name can now be a country as easily as a
        # Vietnamese province, and "đã vào khu vực Nhật Bản" reads oddly.
        opening = (
            text(language, "landfall_past_time", place=place, when=when)
            if when
            else text(language, "landfall_past", place=place)
        )
    else:
        opening = (
            text(language, "landfall_forecast_time", place=place, when=when)
            if when
            else text(language, "landfall_forecast", place=place)
        )
    parts = [opening]

    if not past and (remaining := landfall.get("distance_from_storm_km")) is not None:
        hours = landfall.get("hours_away")
        parts.append(
            text(
                language,
                "landfall_remaining_hours",
                km=round(remaining),
                hours=round(hours),
            )
            if hours is not None and hours > 0
            else text(language, "landfall_remaining", km=round(remaining))
        )
    if home is not None:
        parts.append(text(language, "landfall_from_home", km=round(home)))
    if force:
        parts.append(
            text(
                language,
                "landfall_force_past" if past else "landfall_force_forecast",
                beaufort=force,
            )
        )

    line = ", ".join(parts)
    if not past:
        line += text(language, "landfall_model", model=landfall["model"].upper())
    if storm_name:
        line = text(language, "landfall_named", storm=storm_name, line=line)
    return line


async def _get_json(
    session: aiohttp.ClientSession, url: str
) -> Any | None:
    """GET a Windy JSON endpoint, with a short shared cache.

    Every configured location tracks the same storms, so the responses are
    cached process-wide: adding a second or tenth location costs no extra
    requests. Windy itself caches these for 60 seconds.
    """
    cached = _CACHE.get(url)
    if cached and (monotonic() - cached[0]) < CACHE_TTL:
        return cached[1]

    payload = await _fetch_json(session, url)
    # Cache failures too, briefly, so a broken endpoint is not retried once per
    # location on every cycle.
    _CACHE[url] = (monotonic(), payload)
    return payload


async def _fetch_json(
    session: aiohttp.ClientSession, url: str
) -> Any | None:
    """GET a Windy JSON endpoint. Returns None on 204 or any failure."""
    try:
        async with session.get(
            url,
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        ) as response:
            if response.status == 204:
                # Windy answers 204 with an empty body when there is nothing to
                # report — no alerts in force, for instance.
                return None
            if response.status != 200:
                _LOGGER.debug("Windy %s returned HTTP %d", url, response.status)
                return None
            return await response.json(content_type=None)
    except asyncio.TimeoutError:
        _LOGGER.debug("Windy %s timed out", url)
    except Exception as err:  # noqa: BLE001 - never break the update for Windy
        _LOGGER.debug("Windy %s failed: %s: %s", url, type(err).__name__, err)
    return None


def _as_float(value: Any) -> float | None:
    """Coerce a feed value to float, or None if it is missing or not numeric.

    The feed is undocumented, and a single null coordinate used to raise a
    TypeError deep inside the distance maths — which surfaced as every
    AccuWeather sensor going unavailable.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _storm_summary(
    storm: dict[str, Any],
    latitude: float | None,
    longitude: float | None,
    language: str = FALLBACK_LANGUAGE,
) -> dict[str, Any]:
    """Normalise one storm: m/s -> km/h, Pascal -> hPa, plus distance."""
    wind_ms = _as_float(storm.get("windSpeed"))
    latitude_s = _as_float(storm.get("lat"))
    longitude_s = _as_float(storm.get("lon"))
    summary: dict[str, Any] = {
        "id": storm.get("id"),
        "name": storm.get("name"),
        "latitude": latitude_s,
        "longitude": longitude_s,
        "strength": storm.get("strength"),
        "wind_speed_ms": wind_ms,
        "wind_speed_kmh": round(wind_ms * 3.6, 1) if wind_ms is not None else None,
        "beaufort": beaufort_force(wind_ms),
        "classification": classify_storm(wind_ms, language),
    }

    if (
        latitude is not None
        and longitude is not None
        and latitude_s is not None
        and longitude_s is not None
    ):
        summary["distance_km"] = distance_km(
            latitude, longitude, latitude_s, longitude_s
        )
        # Where the storm sits relative to home — not the same thing as the
        # direction it is travelling in (see _movement_from_history).
        degrees, cardinal = bearing_to(
            latitude, longitude, latitude_s, longitude_s
        )
        summary["direction_from_home_degrees"] = degrees
        summary["direction_from_home_en"] = cardinal
        summary["direction_from_home"] = CARDINAL_NAMES[language].get(
            cardinal, cardinal
        )

    return summary


def _track_point(point: dict[str, Any]) -> dict[str, Any]:
    """Normalise one track point (wind m/s, pressure Pascal in the feed)."""
    wind_ms = _as_float(point.get("windSpeed"))
    pressure = _as_float(point.get("pressure"))
    return {
        "time": point.get("time"),
        "latitude": _as_float(point.get("lat")),
        "longitude": _as_float(point.get("lon")),
        "wind_speed_kmh": round(wind_ms * 3.6, 1) if wind_ms is not None else None,
        "pressure_hpa": round(pressure / 100, 1) if pressure is not None else None,
    }


async def get_storms(
    session: aiohttp.ClientSession,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = STORM_NEARBY_RADIUS_KM,
    detail_limit: int = STORM_SLOTS,
    language: str = FALLBACK_LANGUAGE,
    country: str = DEFAULT_LANDFALL_COUNTRY,
) -> dict[str, Any]:
    """Fetch active tropical cyclones, closest first.

    Tracks, movement and landfall estimates are added for the storms inside
    `radius_km` (up to `detail_limit`); the rest stay summaries, so a quiet basin
    costs a single request.

    `country` is the coast the landfall sensor watches, so every detailed storm
    also gets an estimate of where it meets that country in particular.
    """
    empty = dict(EMPTY_STORMS)

    payload = await _get_json(session, WINDY_STORMS_URL)
    if not payload or not isinstance(payload, dict):
        return empty

    storms = [
        _storm_summary(storm, latitude, longitude, language)
        for storm in payload.get("storms", [])
        if isinstance(storm, dict)
    ]
    if not storms:
        # A real answer: the basin is quiet.
        empty["available"] = True
        return empty

    if latitude is not None and longitude is not None:
        storms.sort(key=lambda s: s.get("distance_km") or math.inf)

    nearby = [
        s for s in storms
        if s.get("distance_km") is not None and s["distance_km"] <= radius_km
    ]

    # Track detail costs one request per storm, so it is fetched for the storms
    # that actually get their own sensor — the closest `detail_limit` ones — and
    # the rest stay summaries in the list.
    detailed_ids = [s["id"] for s in storms[:detail_limit] if s.get("id")]
    for storm in storms:
        if storm.get("id") not in detailed_ids:
            continue
        await _add_storm_detail(
            session, storm, latitude, longitude, language, country
        )

    nearest = storms[0] if storms else None

    _LOGGER.debug(
        "Windy storms: %d active, %d within %d km, detailed=%d, nearest=%s",
        len(storms), len(nearby), radius_km, len(detailed_ids),
        nearest.get("name") if nearest else None,
    )

    return {
        "count": len(storms),
        "nearby_count": len(nearby),
        "storms": storms,
        "nearest": nearest,
        "uncertainty_circles_m": payload.get("defaultCircles"),
        "available": True,
    }


def _central_pressure(
    history: list[dict[str, Any]], forecasts: dict[str, dict[str, Any]]
) -> float | None:
    """Central pressure of the storm, in hPa.

    Windy's observed track usually carries no pressure at all — Chan Hom had it
    on none of its 19 points — while the forecast records almost always do. So
    the current observation is used when it has one, and otherwise the earliest
    point of the most trusted forecast, which is the model's analysis of roughly
    now. Older history points are deliberately not searched: the one pressure
    reading Dolphin had was two weeks stale and would have been worse than
    nothing.
    """
    if history and history[0].get("pressure_hpa") is not None:
        return history[0]["pressure_hpa"]

    ordered = [m for m in LANDFALL_MODEL_PRIORITY if m in forecasts]
    ordered += [m for m in sorted(forecasts) if m not in ordered]
    for model in ordered:
        for record in forecasts[model].get("track") or []:
            if record.get("pressure_hpa") is not None:
                return record["pressure_hpa"]
    return None


def _measure_landfall(
    landfall: dict[str, Any] | None,
    storm: dict[str, Any],
    latitude: float | None,
    longitude: float | None,
) -> None:
    """Add the distances and times around a landfall estimate, in place."""
    if not landfall:
        return

    # How much further the storm still has to travel to get there, and how long
    # that leaves. Both are meaningless once it has already landed.
    landfall["hours_away"] = hours_until(landfall.get("time"))
    if (
        landfall.get("status") == "forecast"
        and storm.get("latitude") is not None
        and storm.get("longitude") is not None
        and landfall.get("latitude") is not None
    ):
        landfall["distance_from_storm_km"] = distance_km(
            storm["latitude"],
            storm["longitude"],
            landfall["latitude"],
            landfall["longitude"],
        )
    # A different question from the one above: not how far the storm still has
    # to go, but how close it will come ashore to where you live.
    if (
        latitude is not None
        and longitude is not None
        and landfall.get("latitude") is not None
    ):
        landfall["distance_from_home_km"] = distance_km(
            latitude, longitude, landfall["latitude"], landfall["longitude"]
        )
    landfall["time_text"] = local_time_text(landfall.get("time"))


async def _add_storm_detail(
    session: aiohttp.ClientSession,
    storm: dict[str, Any],
    latitude: float | None = None,
    longitude: float | None = None,
    language: str = FALLBACK_LANGUAGE,
    country: str = DEFAULT_LANDFALL_COUNTRY,
) -> None:
    """Attach track, movement and landfall estimates to a storm, in place.

    `latitude`/`longitude` are the configured location, used to work out how far
    the landfall point is from it. `country` is the coast being watched, which
    gets an estimate of its own.
    """
    detail = await _get_json(session, f"{WINDY_STORMS_URL}/{storm['id']}")
    if not isinstance(detail, dict):
        return

    # History runs newest first, which is what _movement_from_history expects.
    history = [
        _track_point(p) for p in detail.get("history", []) if isinstance(p, dict)
    ]
    forecasts: dict[str, dict[str, Any]] = {}
    for entry in detail.get("forecast", []):
        if not isinstance(entry, dict):
            continue
        model = entry.get("modelIdentifier")
        if not model:
            continue
        forecasts[model] = {
            "reference_time": entry.get("reftime"),
            # Windy sends forecast records furthest-future first. Sorting them
            # forward matters: predict_landfall reports the first point that
            # reaches the coast, which would otherwise be the last approach
            # rather than the first — wrong province and a day late.
            "track": sorted(
                (
                    _track_point(p) for p in entry.get("records", [])
                    if isinstance(p, dict)
                ),
                key=lambda p: p.get("time") or "",
            ),
        }

    storm["history"] = history
    storm["forecast_models"] = sorted(forecasts)
    storm["forecast"] = forecasts
    storm.update(_movement_from_history(history, language))
    if history:
        storm["pressure_hpa"] = _central_pressure(history, forecasts)
        # ISO (UTC, as the feed sends it) for templates, plus a local-time
        # rendering for anyone reading the attribute directly.
        storm["observed_at"] = history[0].get("time")
        storm["observed_at_text"] = local_time_text(history[0].get("time"))

    if storm.get("latitude") is not None and storm.get("longitude") is not None:
        province, distance = nearest_coast(storm["latitude"], storm["longitude"])
        storm["nearest_coast"] = place_name(province, language)
        storm["distance_to_coast_km"] = distance

    landfall = predict_landfall(forecasts, history, language=language)
    _measure_landfall(landfall, storm, latitude, longitude)

    # Where the storm meets the country being watched, which is not the same
    # question as where it first meets land: a typhoon that crosses Luzon has
    # made landfall long before it reaches Quảng Trị, and the Philippine
    # crossing is the one the estimate above reports.
    if landfall and landfall.get("country") == country:
        # The nearest land already is that country, so it is the same crossing.
        watched = landfall
    else:
        watched = predict_landfall(
            forecasts, history, language=language, country=country
        )
        _measure_landfall(watched, storm, latitude, longitude)

    storm["landfall"] = landfall
    storm["landfall_text"] = describe_landfall(
        landfall,
        storm.get("nearest_coast"),
        storm.get("distance_to_coast_km"),
        language=language,
    )

    storm["landfall_watched"] = watched
    # The landfall sensor is read on its own, so this line carries the name of
    # the storm and how far from you it comes ashore. Written only when there
    # is a landfall on the watched coast: with none, that sensor says so in its
    # own words rather than describing an absent one.
    storm["landfall_watched_text"] = (
        describe_landfall(
            watched,
            from_home=True,
            language=language,
            storm_name=storm_headline(storm),
        )
        if watched
        else None
    )
    # Built last: it quotes the landfall estimate worked out just above.
    storm["summary_text"] = describe_storm(storm, language)


async def get_alerts(
    session: aiohttp.ClientSession,
    latitude: float,
    longitude: float,
    language: str = FALLBACK_LANGUAGE,
) -> list[dict[str, Any]]:
    """Fetch official CAP weather alerts for a point (empty when none apply).

    Windy translates the headline and event name itself, given `lang`.
    """
    url = WINDY_ALERTS_URL.format(lat=latitude, lon=longitude, lang=language)
    payload = await _get_json(session, url)
    if not isinstance(payload, list):
        return []

    alerts = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        alerts.append({
            "id": item.get("id"),
            "headline": item.get("headline"),
            "event": item.get("event"),
            "severity": item.get("severity"),
            "type": item.get("type"),
            "start": item.get("start"),
            "end": item.get("end"),
        })
    return alerts
