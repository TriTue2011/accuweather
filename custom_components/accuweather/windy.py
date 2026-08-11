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

from .const import (
    CARDINAL_VI,
    LANDFALL_MODEL_PRIORITY,
    LANDFALL_OBSERVED_KM,
    LANDFALL_THRESHOLD_KM,
    STORM_NEARBY_RADIUS_KM,
    STORM_SLOTS,
    VIETNAM_COAST,
    WINDY_ALERTS_URL,
    WINDY_STORMS_URL,
    WIND_DIRECTION_EN,
)

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


def classify_storm_vi(wind_ms: float | None) -> str | None:
    """Describe a cyclone's intensity the way Vietnamese forecasts do."""
    force = beaufort_force(wind_ms)
    if force is None:
        return None
    if force >= 16:
        return "Siêu bão"
    if force >= 12:
        return "Bão rất mạnh"
    if force >= 10:
        return "Bão mạnh"
    if force >= 8:
        return "Bão"
    if force >= 6:
        return "Áp thấp nhiệt đới"
    return "Vùng áp thấp"


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


def _movement_from_history(history: list[dict[str, Any]]) -> dict[str, Any]:
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
    direction_vi = CARDINAL_VI.get(cardinal, cardinal)

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
        "movement_direction": direction_vi,
        "movement_direction_en": cardinal,
        "movement_bearing": degrees,
        "movement_speed_kmh": speed_kmh,
    }
    movement["movement_text"] = (
        f"Di chuyển hướng {direction_vi}"
        + (f", {speed_kmh} km/h" if speed_kmh is not None else "")
    )
    return movement


def nearest_coast(latitude: float, longitude: float) -> tuple[str, float]:
    """Return the closest Vietnamese coastal province and its distance in km."""
    name, best = min(
        (
            (province, distance_km(latitude, longitude, lat, lon))
            for province, lat, lon in VIETNAM_COAST
        ),
        key=lambda item: item[1],
    )
    return name, best


def _coast_crossing(
    track: list[dict[str, Any]], threshold_km: float
) -> dict[str, Any] | None:
    """First point of a track that comes within `threshold_km` of the coast."""
    for point in track:
        lat, lon = point.get("latitude"), point.get("longitude")
        if lat is None or lon is None:
            continue
        province, distance = nearest_coast(lat, lon)
        if distance <= threshold_km:
            return {
                "province": province,
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
) -> dict[str, Any] | None:
    """Work out where a storm's track meets the Vietnamese coast, past or future.

    The observed track is checked first, oldest point first: a storm that has
    already come ashore must be reported as having done so, not as still
    approaching — its remaining forecast points sit inland, close to the coastal
    reference points, and would otherwise read as a landfall still to come.
    Failing that, forecast tracks are checked in agency-trust order and the
    first point reaching the coast is reported.

    Either way this is an approximation from track points and coastal reference
    points: it names the stretch of coast involved, not an official bulletin.
    """
    if history:
        # Sorted forward — the feed sends history newest first, and the crossing
        # that matters is the first one, not the most recent point near shore.
        observed = sorted(history, key=lambda p: p.get("time") or "")
        if hit := _coast_crossing(observed, LANDFALL_OBSERVED_KM):
            hit["model"] = "observed"
            hit["status"] = "past"
            return hit

    ordered = [m for m in LANDFALL_MODEL_PRIORITY if m in forecasts]
    ordered += [m for m in sorted(forecasts) if m not in ordered]

    for model in ordered:
        if hit := _coast_crossing(forecasts[model].get("track") or [], threshold_km):
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
) -> str:
    """One line of plain Vietnamese about where the storm is going.

    Three situations, told apart by the track: the storm has already come
    ashore, it is forecast to, or nothing on its track reaches the coast.

    `from_home` adds how far the landfall point is from the configured
    location — the figure that says whether the storm is coming for you, rather
    than how far it still has to travel. It belongs on the "nearest storm"
    sensor and would only be noise repeated on every individual storm.
    """
    if not landfall:
        if heading_towards and distance_to_coast is not None:
            return (
                f"Chưa có dấu hiệu vào đất liền; gần bờ {heading_towards} nhất "
                f"khoảng {round(distance_to_coast)} km"
            )
        return "Chưa có dấu hiệu vào đất liền Việt Nam"

    when = local_time_text(landfall.get("time"))
    force = landfall.get("beaufort")
    home = landfall.get("distance_from_home_km") if from_home else None

    if landfall.get("status") == "past":
        parts = [f"Đã vào khu vực {landfall['province']}"]
        if when:
            parts[0] += f" lúc {when}"
        if home is not None:
            parts.append(f"cách bạn {round(home)} km")
        if force:
            parts.append(f"cấp {force} khi vào bờ")
        return ", ".join(parts)

    parts = [f"Dự kiến vào khu vực {landfall['province']}"]
    if when:
        parts[0] += f" khoảng {when}"
    remaining = landfall.get("distance_from_storm_km")
    if remaining is not None:
        leg = f"còn khoảng {round(remaining)} km"
        hours = landfall.get("hours_away")
        if hours is not None and hours > 0:
            leg += f" (~{round(hours)} giờ nữa)"
        parts.append(leg)
    if home is not None:
        parts.append(f"cách bạn {round(home)} km")
    if force:
        parts.append(f"cấp {force} khi đổ bộ")
    return ", ".join(parts) + f" (theo {landfall['model'].upper()})"


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
    storm: dict[str, Any], latitude: float | None, longitude: float | None
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
        "classification": classify_storm_vi(wind_ms),
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
        summary["direction_from_home"] = CARDINAL_VI.get(cardinal, cardinal)

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
) -> dict[str, Any]:
    """Fetch active tropical cyclones, closest first.

    Tracks, movement and landfall estimates are added for the storms inside
    `radius_km` (up to `detail_limit`); the rest stay summaries, so a quiet basin
    costs a single request.
    """
    empty = dict(EMPTY_STORMS)

    payload = await _get_json(session, WINDY_STORMS_URL)
    if not payload or not isinstance(payload, dict):
        return empty

    storms = [
        _storm_summary(storm, latitude, longitude)
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
        await _add_storm_detail(session, storm, latitude, longitude)

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


async def _add_storm_detail(
    session: aiohttp.ClientSession,
    storm: dict[str, Any],
    latitude: float | None = None,
    longitude: float | None = None,
) -> None:
    """Attach track, movement and landfall estimate to a storm, in place.

    `latitude`/`longitude` are the configured location, used to work out how far
    the landfall point is from it.
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
    storm.update(_movement_from_history(history))
    if history:
        storm["pressure_hpa"] = history[0].get("pressure_hpa")
        # ISO (UTC, as the feed sends it) for templates, plus a local-time
        # rendering for anyone reading the attribute directly.
        storm["observed_at"] = history[0].get("time")
        storm["observed_at_text"] = local_time_text(history[0].get("time"))

    if storm.get("latitude") is not None and storm.get("longitude") is not None:
        province, distance = nearest_coast(storm["latitude"], storm["longitude"])
        storm["nearest_coast"] = province
        storm["distance_to_coast_km"] = distance

    landfall = predict_landfall(forecasts, history)
    if landfall:
        # How much further the storm still has to travel to get there, and how
        # long that leaves. Both are meaningless once it has already landed.
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
        # A different question from the one above: not how far the storm still
        # has to go, but how close it will come ashore to where you live.
        if (
            latitude is not None
            and longitude is not None
            and landfall.get("latitude") is not None
        ):
            landfall["distance_from_home_km"] = distance_km(
                latitude, longitude, landfall["latitude"], landfall["longitude"]
            )
        landfall["time_text"] = local_time_text(landfall.get("time"))

    storm["landfall"] = landfall
    storm["landfall_text"] = describe_landfall(
        landfall,
        storm.get("nearest_coast"),
        storm.get("distance_to_coast_km"),
    )
    # Same sentence with the distance from the configured location added, for
    # the "nearest storm" sensor. Kept as a second string because the nearest
    # storm and storm slot 1 are the same record.
    storm["landfall_text_from_home"] = describe_landfall(
        landfall,
        storm.get("nearest_coast"),
        storm.get("distance_to_coast_km"),
        from_home=True,
    )


async def get_alerts(
    session: aiohttp.ClientSession, latitude: float, longitude: float
) -> list[dict[str, Any]]:
    """Fetch official CAP weather alerts for a point (empty when none apply)."""
    url = WINDY_ALERTS_URL.format(lat=latitude, lon=longitude)
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
