"""Utility functions for AccuWeather integration."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from typing import Any

from bs4 import BeautifulSoup

from .fetcher import HtmlFetcher
from .const import (
    AUTOCOMPLETE_URL,
    BASE_URL,
    CONDITION_MAP,
    CONDITION_MAP_VI,
    HOURLY_DAYS,
    WIND_DIRECTION_EN,
    WIND_DIRECTION_VI,
)

_LOGGER = logging.getLogger(__name__)

# Transient errors worth retrying with exponential backoff.
RETRY_HTTP_ERRORS = {429, 500, 502, 503, 504}
# 403 is what AccuWeather's CDN (Akamai) returns when it classifies the client as
# a bot. That verdict holds for the whole request wave, so walking the full retry
# ladder only stretches each update cycle out without ever succeeding.
BLOCKED_HTTP_ERRORS = {401, 403}
BLOCKED_RETRY_COUNT = 2
RETRY_COUNT = 4
INITIAL_RETRY_DELAY = 1.0   # seconds (starting delay for exponential backoff)
MAX_RETRY_DELAY = 30.0     # seconds (cap for exponential backoff)

# Timeout settings (seconds)
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 20


def slugify(text: str) -> str:
    """Convert Vietnamese location name to URL slug.

    e.g. "Hải Dương" -> "hai-duong", "Thành phố Hồ Chí Minh" -> "thanh-pho-ho-chi-minh"
    """
    # NFD decomposition then strip combining characters (accents)
    nfkd = unicodedata.normalize('NFD', text)
    stripped = ''.join(c for c in nfkd if not unicodedata.combining(c))
    # Lowercase, replace spaces with hyphens, remove anything that's not a-z/0-9/-
    slug = stripped.lower()
    slug = slug.replace(' ', '-')
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug


def get_headers(referer: str | None = None) -> dict[str, str]:
    """Get default headers for requests."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "DNT": "1",
        # AccuWeather picks units from this cookie. Without it the unit follows
        # the server's geo guess, and a page served in °F would be read as °C
        # (90°F silently becoming "90 degrees"). Requesting metric explicitly is
        # the first line of defence; parse_temperature_unit() is the second.
        "Cookie": "awx_user=tp:C|lang:vi",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def parse_temperature_unit(html: str) -> str:
    """Return the temperature unit the page was rendered in ("C" or "F")."""
    soup = BeautifulSoup(html, "html.parser")
    temp = soup.select_one(".display-temp")
    text = temp.get_text(strip=True) if temp else ""
    if "F" in text.upper():
        return "F"
    if "C" in text.upper():
        return "C"
    unit = soup.select_one(".unit")
    unit_text = unit.get_text(strip=True).upper() if unit else ""
    return "F" if unit_text == "F" else "C"


def to_celsius(value: float | None, unit: str) -> float | None:
    """Convert a temperature to Celsius when the page was served in °F."""
    if value is None or unit != "F":
        return value
    return round((value - 32.0) * 5.0 / 9.0, 1)


def parse_distance_km(text: str | None) -> float | None:
    """Parse a distance into kilometres ("24 km", "6 dặm", "6 mi")."""
    value = extract_numeric_value(text)
    if value is None:
        return None
    lowered = (text or "").lower()
    if "dặm" in lowered or re.search(r"\bmi\b", lowered):
        return round(value * 1.609344, 1)
    return value


def parse_length_m(text: str | None) -> float | None:
    """Parse a height into metres ("12200 m", "30000 ft")."""
    value = extract_numeric_value(text)
    if value is None:
        return None
    if "ft" in (text or "").lower():
        return round(value * 0.3048)
    return value


def parse_precipitation_mm(text: str | None) -> float | None:
    """Parse a precipitation amount into millimetres ("0.0 mm", "0.10 inch")."""
    value = extract_numeric_value(text)
    if value is None:
        return None
    lowered = (text or "").lower()
    if "inch" in lowered or '"' in lowered:
        return round(value * 25.4, 1)
    if "cm" in lowered:
        return round(value * 10, 1)
    return value


def parse_wind(wind_text: str | None) -> tuple[float | None, str | None, float | None]:
    """Parse a wind string into (speed km/h, English cardinal, degrees).

    AccuWeather's Vietnamese pages write directions with Vietnamese initials
    ("ĐN" = Đông Nam = southeast), which overlap English letters but mean
    something different: "N" is Nam (south), not north.
    """
    if not wind_text:
        return None, None, None

    speed = None
    speed_match = re.search(r"([\d.,]+)\s*(km/h|mi/h|mph|m/s|kt)", wind_text)
    if speed_match:
        try:
            speed = float(speed_match.group(1).replace(",", "."))
            unit = speed_match.group(2)
            if unit == "m/s":
                speed = round(speed * 3.6, 1)
            elif unit in ("mi/h", "mph"):
                speed = round(speed * 1.609344, 1)
            elif unit == "kt":
                speed = round(speed * 1.852, 1)
        except ValueError:
            speed = None

    # Longest match wins so "NĐN" is not truncated to "N". Vietnamese initials
    # are tried first because they are the ones these pages actually use.
    cardinal = degrees = None
    vi_match = re.search(r"(?<![A-ZĐ])([BĐNT]{1,3})(?![A-ZĐ])", wind_text)
    if vi_match and vi_match.group(1) in WIND_DIRECTION_VI:
        cardinal, degrees = WIND_DIRECTION_VI[vi_match.group(1)]
    else:
        en_match = re.search(r"(?<![A-Z])([NSEW]{1,3})(?![A-Z])", wind_text)
        if en_match and en_match.group(1) in WIND_DIRECTION_EN:
            cardinal = en_match.group(1)
            degrees = WIND_DIRECTION_EN[cardinal]

    return speed, cardinal, degrees


class BlockedError(Exception):
    """AccuWeather's CDN refused the request (bot protection)."""

    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.url = url


async def _fetch_with_retry(
    fetcher: HtmlFetcher,
    url: str,
    headers: dict[str, str],
) -> str | None:
    """Fetch a URL with retry on transient HTTP errors and connection errors.

    Body is read inside the async-with block to ensure the connection stays alive
    while reading. Returns the HTML text on success, None on failure.
    Raises BlockedError when the CDN answers with a bot-protection status, so the
    coordinator can tell "blocked" apart from "page layout changed".
    """
    blocked_attempts = 0
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            status, body = await fetcher.get_text(url, headers)
            if status == 200 and body is not None:
                return body
            if status in BLOCKED_HTTP_ERRORS:
                blocked_attempts += 1
                if blocked_attempts >= BLOCKED_RETRY_COUNT:
                    raise BlockedError(status, url)
                # Drop the cookies before retrying. A stale Akamai clearance
                # cookie is one of the ways a working setup starts returning
                # 403 out of nowhere; starting a fresh handshake recovers it
                # without waiting for Home Assistant to be restarted.
                fetcher.clear_cookies()
                delay = INITIAL_RETRY_DELAY * (2 ** (blocked_attempts - 1))
                _LOGGER.debug(
                    "HTTP %d (bot protection) for %s (attempt %d/%d), cleared "
                    "cookies, retrying in %.1fs...",
                    status, url, blocked_attempts, BLOCKED_RETRY_COUNT, delay,
                )
                await asyncio.sleep(delay)
                continue
            if status in RETRY_HTTP_ERRORS:
                delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
                _LOGGER.debug(
                    "HTTP %d for %s (attempt %d/%d), retrying in %.1fs...",
                    status, url, attempt, RETRY_COUNT, delay,
                )
                if attempt < RETRY_COUNT:
                    await asyncio.sleep(delay)
                continue
            _LOGGER.debug(
                "HTTP %d for %s (attempt %d/%d), not retrying",
                status, url, attempt, RETRY_COUNT,
            )
            return None
        except BlockedError:
            raise
        except asyncio.TimeoutError:
            delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
            _LOGGER.debug(
                "Timeout for %s (attempt %d/%d), retrying in %.1fs...",
                url, attempt, RETRY_COUNT, delay,
            )
            if attempt < RETRY_COUNT:
                await asyncio.sleep(delay)
        except Exception as e:
            delay = min(INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
            _LOGGER.debug(
                "Exception for %s (attempt %d/%d): %s: %s, retrying in %.1fs...",
                url, attempt, RETRY_COUNT, type(e).__name__, e, delay,
            )
            if attempt < RETRY_COUNT:
                await asyncio.sleep(delay)
    _LOGGER.debug("All %d attempts failed for %s", RETRY_COUNT, url)
    return None


async def get_location_keys(fetcher: HtmlFetcher, query: str) -> list[tuple[str, str, str]]:
    """Get location keys from AccuWeather."""
    params = {
        "query": query,
        "language": "vi"
    }
    headers = get_headers()
    headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
    
    try:
        data = await fetcher.get_json(AUTOCOMPLETE_URL, headers, params=params)
        if data and isinstance(data, list):
            results = []
            for item in data:
                key = item.get("key")
                name = item.get("localizedName")
                long_name = item.get("longName")
                if key and name:
                    results.append((key, name, long_name))
            return results
    except Exception as e:
        _LOGGER.debug("get_location_keys: %s: %s", type(e).__name__, e)
    
    return []


def extract_numeric_value(text: str | None) -> float | None:
    """Extract numeric value from text."""
    if not text:
        return None
    
    # Remove special characters and get numbers
    match = re.search(r"([\d.,]+)", str(text).replace("°", "").replace("%", ""))
    if match:
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            pass
    return None


def convert_temp_to_numeric(temp_text: str) -> float | None:
    """Convert temperature text to numeric value."""
    if not temp_text:
        return None
    
    # Extract number from temperature string  
    match = re.search(r"(-?[\d.,]+)", str(temp_text))
    if match:
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            pass
    return None


def map_condition_to_ha(condition: str | None) -> str:
    """Map AccuWeather condition to Home Assistant condition."""
    if not condition:
        return "unknown"
    
    condition_lower = condition.lower().strip()
    
    # Try Vietnamese mapping first
    for vi_condition, ha_condition in CONDITION_MAP_VI.items():
        if vi_condition in condition_lower:
            return ha_condition
    
    # Try English mapping
    for en_condition, ha_condition in CONDITION_MAP.items():
        if en_condition in condition_lower:
            return ha_condition
    
    # Default fallback
    if "mưa" in condition_lower or "rain" in condition_lower:
        return "rainy"
    elif "mây" in condition_lower or "cloud" in condition_lower:
        return "cloudy"
    elif "nắng" in condition_lower or "sun" in condition_lower:
        return "sunny"
    elif "gió" in condition_lower or "wind" in condition_lower:
        return "windy"
    
    return "unknown"


def parse_location_info(html: str) -> dict[str, Any]:
    """Read the page's own `currentLocation` JavaScript object.

    It carries the coordinates and capability flags (hasAlerts, hasMinuteCast,
    hasPollen), which saves guessing whether a section exists — and gives the
    latitude/longitude the Windy storm tracker needs.
    """
    match = re.search(r'currentLocation\s*=\s*(\{.*?\});', html, re.DOTALL)
    if not match:
        return {}
    try:
        raw = json.loads(match.group(1))
    except json.JSONDecodeError:
        _LOGGER.debug("parse_location_info: currentLocation is not valid JSON")
        return {}

    return {
        'latitude': raw.get('lat'),
        'longitude': raw.get('lon'),
        'english_name': raw.get('englishName'),
        'localized_name': raw.get('localizedName'),
        'time_zone': raw.get('timeZone'),
        'gmt_offset': raw.get('gmtOffset'),
        'has_alerts': raw.get('hasAlerts'),
        'has_minutecast': raw.get('hasMinuteCast'),
        'has_pollen': raw.get('hasPollen'),
    }


def _parse_sun_moon(soup: BeautifulSoup) -> dict[str, Any]:
    """Read the "Mặt trời & mặt trăng" block."""
    items = soup.select('.sunrise-sunset__item')
    result: dict[str, Any] = {}
    keys = ('sun', 'moon')
    for key, item in zip(keys, items):
        times = [
            el.get_text(strip=True)
            for el in item.select('.sunrise-sunset__times-value')
        ]
        phrase = item.select_one('.sunrise-sunset__phrase')
        result[f'{key}rise'] = times[0] if len(times) > 0 else None
        result[f'{key}set'] = times[1] if len(times) > 1 else None
        result[f'{key}_duration'] = phrase.get_text(strip=True) if phrase else None

    # The moon phase is only expressed by the icon file name.
    moon_icon = soup.select_one('.sunrise-sunset__item:nth-of-type(2) img[src]')
    if moon_icon:
        src = str(moon_icon.get('src') or '')
        phase_match = re.search(r'/([A-Za-z]+)\.svg$', src)
        if phase_match:
            result['moon_phase'] = phase_match.group(1)
    return result


def _parse_temp_history(soup: BeautifulSoup, unit: str) -> dict[str, Any]:
    """Read the temperature-history block (forecast vs average vs last year)."""
    history: dict[str, Any] = {}
    for row in soup.select('.temp-history .row'):
        label = row.select_one('.label')
        temps = row.select('.temperature')
        if not label or len(temps) < 2:
            continue
        history[label.get_text(strip=True)] = {
            'high': to_celsius(convert_temp_to_numeric(temps[0].get_text(strip=True)), unit),
            'low': to_celsius(convert_temp_to_numeric(temps[1].get_text(strip=True)), unit),
        }
    return history


def parse_clock_minutes(text: str | None) -> int | None:
    """Turn "05:33" into minutes since midnight."""
    if not text:
        return None
    match = re.search(r'(\d{1,2}):(\d{2})', str(text))
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def night_variant(condition: str | None, is_night: bool) -> str | None:
    """Swap daylight-only conditions for their night equivalent.

    AccuWeather writes "Trời quang" both day and night, which mapped to `sunny`
    and put a sun icon on a 22:00 forecast.
    """
    if not is_night:
        return condition
    if condition == 'sunny':
        return 'clear-night'
    return condition


def is_night_at(
    minutes: int | None, sunrise: int | None, sunset: int | None
) -> bool:
    """Whether a time of day falls outside daylight hours."""
    if minutes is None or sunrise is None or sunset is None:
        return False
    return minutes < sunrise or minutes >= sunset


async def parse_weather_html(html: str) -> dict[str, Any] | None:
    """Parse current weather HTML into normalised values.

    Temperatures come back in Celsius regardless of how the page was rendered,
    and wind direction comes back in degrees plus an English cardinal.
    """
    try:
        soup = BeautifulSoup(html, 'html.parser')
        card = soup.select_one('.current-weather-card')
        if not card:
            _LOGGER.debug(
                "parse_weather_html: .current-weather-card NOT found "
                "(HTML structure may have changed). First 100 chars: %s",
                html[:100]
            )
            return None

        unit = parse_temperature_unit(html)

        # Time
        time_element = card.select_one('.card-header .sub')
        time_val = time_element.text.strip() if time_element else None

        # Temperature
        temp_element = card.select_one('.display-temp')
        temp_val = temp_element.text.strip() if temp_element else None
        temp_numeric = to_celsius(convert_temp_to_numeric(temp_val), unit)

        # Weather phrase/condition
        phrase_element = card.select_one('.phrase')
        phrase_val = phrase_element.text.strip() if phrase_element else None
        condition = map_condition_to_ha(phrase_val)

        # Details table, e.g. {"Độ ẩm": "73%", "Gió": "N 10 km/h", ...}
        details = {}
        for item in card.select('.current-weather-details .detail-item'):
            label = item.select_one('div:nth-child(1)')
            value = item.select_one('div:nth-child(2)')
            if label and value:
                details[label.text.strip()] = value.text.strip()

        # RealFeel: the number lives in the details table, while the block above
        # holds its wording ("Rất nóng"). Reading the block as a whole used to
        # glue the two together into "RealFeel® 40°Rất nóng".
        realfeel_phrase = None
        extra = card.select_one('.current-weather-extra')
        if extra:
            label = extra.select_one('.label-tooltip .label, .label')
            if label:
                realfeel_phrase = label.get_text(strip=True)

        wind_speed, wind_text, wind_deg = parse_wind(details.get('Gió'))
        gust_speed, _, _ = parse_wind(
            details.get('Gió giật mạnh') or details.get('Gió giật')
        )

        pressure_raw = details.get('Khí áp') or ''
        pressure_trend = None
        if '↑' in pressure_raw:
            pressure_trend = 'rising'
        elif '↓' in pressure_raw:
            pressure_trend = 'falling'
        elif pressure_raw:
            pressure_trend = 'steady'

        data = {
            'time': time_val,
            'temperature': temp_numeric,
            'temperature_unit': '°C',
            'source_unit': unit,
            'condition': condition,
            'phrase': phrase_val,
            'realfeel': to_celsius(
                extract_numeric_value(details.get('RealFeel®')), unit
            ),
            'realfeel_phrase': realfeel_phrase,
            'realfeel_shade': to_celsius(
                extract_numeric_value(details.get('RealFeel Shade™')), unit
            ),
            'heat_index': to_celsius(
                extract_numeric_value(details.get('Chỉ số nhiệt')), unit
            ),
            'dew_point': to_celsius(
                extract_numeric_value(details.get('Điểm sương')), unit
            ),
            'humidity': extract_numeric_value(details.get('Độ ẩm')),
            'pressure': extract_numeric_value(pressure_raw),
            'pressure_trend': pressure_trend,
            'wind_speed': wind_speed,
            'wind_bearing': wind_deg,
            'wind_bearing_text': wind_text,
            'wind_gust_speed': gust_speed,
            'visibility': parse_distance_km(details.get('Tầm nhìn')),
            'cloud_coverage': extract_numeric_value(details.get('Mật độ mây')),
            'cloud_ceiling': parse_length_m(details.get('Trần mây')),
            'uv_index': extract_numeric_value(details.get('Chỉ số UV tối đa')),
            'details': details,
        }

        data.update(_parse_sun_moon(soup))
        data['temp_history'] = _parse_temp_history(soup, unit)
        data['location'] = parse_location_info(html)

        # Half-day summary card ("Đêm" / "Ngày") shown under the current card.
        half_day = soup.select_one('.half-day-card')
        if half_day:
            title = half_day.select_one('h2.title')
            hd_phrase = half_day.select_one('.half-day-card-content > .phrase')
            hd_temp = half_day.select_one('.weather .temperature')
            hd_realfeel = half_day.select_one('.real-feel')
            hd_details = {}
            for p in half_day.select('.panels .panel-item'):
                label = str(p.contents[0]).strip() if p.contents else None
                value = p.select_one('.value')
                if label and value:
                    hd_details[label] = value.get_text(strip=True)
            data['half_day'] = {
                'label': title.get_text(strip=True) if title else None,
                'phrase': hd_phrase.get_text(strip=True) if hd_phrase else None,
                'temperature': to_celsius(
                    convert_temp_to_numeric(hd_temp.get_text(strip=True)) if hd_temp else None,
                    unit,
                ),
                'realfeel': to_celsius(
                    convert_temp_to_numeric(hd_realfeel.get_text(strip=True)) if hd_realfeel else None,
                    unit,
                ),
                'precipitation': parse_precipitation_mm(hd_details.get('Lượng mưa')),
                'thunderstorm_probability': extract_numeric_value(
                    hd_details.get('Dự báo Dông')
                ),
                'precipitation_probability': extract_numeric_value(
                    hd_details.get('Khả năng dự báo')
                ),
                'details': hd_details,
            }

        _LOGGER.debug(
            "parse_weather_html: temp=%s%s phrase='%s' condition=%s wind=%s/%s",
            temp_numeric, unit, phrase_val, condition, wind_speed, wind_text,
        )
        return data
    except Exception as e:
        _LOGGER.debug("parse_weather_html: %s: %s", type(e).__name__, e)
        return None


async def get_current_weather(fetcher: HtmlFetcher, location_key: str, location_slug: str) -> dict[str, Any] | None:
    """Get current weather data (converted from get_weather.py)."""
    url = f"{BASE_URL}/vi/vn/{location_slug}/{location_key}/current-weather/{location_key}"
    headers = get_headers()

    html = await _fetch_with_retry(fetcher, url, headers)
    if html is None:
        return None

    try:
        data = await parse_weather_html(html)
        if data is None:
            _LOGGER.debug(
                "get_current_weather: parse returned None (HTML structure changed?). URL: %s",
                url,
            )
        return data
    except Exception as e:
        _LOGGER.debug("get_current_weather: %s: %s - %s", type(e).__name__, e, url)
        return None


async def parse_daily_html(html: str) -> list[dict[str, Any]]:
    """Parse daily forecast HTML (converted from get_daily.py)."""
    try:
        soup = BeautifulSoup(html, 'html.parser')
        unit = parse_temperature_unit(html)
        daily = []
        for wrapper in soup.select('.daily-wrapper'):
            card = wrapper.select_one('.daily-forecast-card')
            content = wrapper.select_one('.half-day-card-content')
            if not card or not content:
                continue
            
            # Extract date from two <span> inside <h2 class="date">
            date = None
            date_h2 = card.select_one('.info h2.date')
            if date_h2:
                spans = date_h2.find_all('span')
                if len(spans) >= 2:
                    date = f"{spans[0].get_text(strip=True)} {spans[1].get_text(strip=True)}"
            
            # Fallback: try .date as before
            if not date:
                date_tag = card.select_one('.date')
                date = date_tag.get_text(strip=True) if date_tag else None
            
            precip = card.select_one('.precip')
            precip_val = None
            if precip:
                # Only get the text node, ignore SVG
                for t in precip.contents:
                    if isinstance(t, str) and t.strip():
                        precip_val = extract_numeric_value(t.strip())
                        break
            
            phrase = content.select_one('.phrase')
            phrase_val = phrase.get_text(strip=True) if phrase else None
            condition = map_condition_to_ha(phrase_val)
            
            # Extract high/low temp
            high = low = None
            temp = card.select_one('.temp')
            if temp:
                high_span = temp.select_one('.high')
                low_span = temp.select_one('.low')
                high = convert_temp_to_numeric(high_span.get_text(strip=True)) if high_span else None
                low = convert_temp_to_numeric(low_span.get_text(strip=True)) if low_span else None
            
            # Collect every panel item in the whole wrapper. Restricting this to
            # .panels inside the half-day card dropped the rows AccuWeather puts
            # elsewhere, which is why UV index and RealFeel Shade were always
            # empty.
            details = {}
            for p in wrapper.select('p.panel-item'):
                label = str(p.contents[0]).strip() if p.contents else None
                value = p.select_one('.value')
                if label and value:
                    details[label] = value.text.strip()

            # Night half of the day, when the page splits it out.
            night = {}
            night_content = wrapper.select_one('.half-day-card.night .half-day-card-content')
            if night_content:
                night_phrase = night_content.select_one('.phrase')
                night['phrase'] = (
                    night_phrase.get_text(strip=True) if night_phrase else None
                )
                night['condition'] = map_condition_to_ha(night.get('phrase'))

            wind_speed, wind_text, wind_deg = parse_wind(details.get('Gió'))
            gust_speed, _, _ = parse_wind(
                details.get('Gió giật mạnh') or details.get('Gió giật')
            )

            day_num = month_num = None
            date_match = re.search(r'(\d{1,2})/(\d{1,2})', date or '')
            if date_match:
                day_num = int(date_match.group(1))
                month_num = int(date_match.group(2))

            daily.append({
                'datetime': date,
                'date_day': day_num,
                'date_month': month_num,
                'condition': condition,
                'phrase': phrase_val,
                'native_temperature': to_celsius(high, unit),
                'native_templow': to_celsius(low, unit),
                'precipitation_probability': precip_val,
                'precipitation': parse_precipitation_mm(
                    details.get('Lượng mưa') or details.get('Mưa')
                ),
                'precipitation_hours': extract_numeric_value(
                    details.get('Tổng số giờ mưa')
                ),
                'humidity': extract_numeric_value(details.get('Độ ẩm')),
                'wind_speed': wind_speed,
                'wind_bearing': wind_deg,
                'wind_bearing_text': wind_text,
                'wind_gust_speed': gust_speed,
                'cloud_coverage': extract_numeric_value(details.get('Mật độ mây')),
                'uv_index': extract_numeric_value(details.get('Chỉ số UV tối đa')),
                'uv_phrase': details.get('Chỉ số UV tối đa'),
                'realfeel': to_celsius(
                    extract_numeric_value(details.get('RealFeel®')), unit
                ),
                'realfeel_shade': to_celsius(
                    extract_numeric_value(details.get('RealFeel Shade™')), unit
                ),
                'night': night or None,
                'details': details
            })
        return daily
    except Exception as e:
        _LOGGER.debug("parse_daily_html: %s: %s", type(e).__name__, e)
        return []


async def get_daily_forecast(fetcher: HtmlFetcher, location_key: str, location_slug: str) -> list[dict[str, Any]]:
    """Get daily forecast data (converted from get_daily.py)."""
    url = f"{BASE_URL}/vi/vn/{location_slug}/{location_key}/daily-weather-forecast/{location_key}"
    headers = get_headers()

    html = await _fetch_with_retry(fetcher, url, headers)
    if html is None:
        return []

    try:
        data = await parse_daily_html(html)
        _LOGGER.debug(
            "get_daily_forecast: parsed %d days from %s", len(data), url
        )
        return data
    except Exception as e:
        _LOGGER.debug("get_daily_forecast: %s: %s - %s", type(e).__name__, e, url)
        return []


async def parse_hourly_html(html: str, day_offset: int = 0) -> list[dict[str, Any]]:
    """Parse hourly forecast HTML.

    Each hour carries its own epoch timestamp in the element id, which is used
    instead of reconstructing the calendar date from the hour label.
    """
    try:
        soup = BeautifulSoup(html, 'html.parser')
        hourly = []
        for item in soup.select('.accordion-item.hour'):
            hour_el = item.select_one('.hourly-card-subcontaint .date div')
            # Only the metric rendering carries the "metric" class; without a
            # units cookie AccuWeather serves °F/mi/ft, and requiring
            # ".temp.metric" made every temperature come back empty.
            temp_el = item.select_one('.hourly-card-top .temp') or item.select_one('.temp')
            unit = 'C' if temp_el and 'metric' in (temp_el.get('class') or []) else 'F'
            realfeel = item.select_one('.real-feel__text')
            realfeel_label = item.select_one('.real-feel .label-tooltip .label')
            phrase = item.select_one('.phrase')
            precip = item.select_one('.precip')

            # Two panels per hour: a collapsed header panel and the expanded
            # body. Which labels land in which one changes hour by hour, so both
            # are merged and everything is looked up by label, never by position.
            details = {}
            for p in item.select('.panel p'):
                label = str(p.contents[0]).strip() if p.contents else None
                value = p.select_one('.value')
                if label and value:
                    details[label] = value.get_text(strip=True)

            phrase_val = phrase.get_text(strip=True) if phrase else None
            condition = map_condition_to_ha(phrase_val)

            timestamp = None
            raw_id = item.get('id') or item.get('data-qa')
            if raw_id and str(raw_id).isdigit():
                timestamp = int(raw_id)

            hour_text = hour_el.get_text(strip=True) if hour_el else None
            hour_num = None
            if hour_text and hour_text.isdigit():
                hour_num = int(hour_text)

            wind_speed, wind_text, wind_deg = parse_wind(details.get('Gió'))
            gust_speed, _, _ = parse_wind(
                details.get('Gió giật') or details.get('Gió giật mạnh')
            )

            hourly.append({
                'timestamp': timestamp,
                'datetime': hour_text,
                'hour': hour_num,
                'day_offset': day_offset,
                'native_temperature': to_celsius(
                    convert_temp_to_numeric(temp_el.get_text(strip=True)) if temp_el else None,
                    unit,
                ),
                'condition': condition,
                'phrase': phrase_val,
                'native_apparent_temperature': to_celsius(
                    convert_temp_to_numeric(realfeel.get_text(strip=True)) if realfeel else None,
                    unit,
                ),
                'realfeel_phrase': (
                    realfeel_label.get_text(strip=True) if realfeel_label else None
                ),
                'realfeel_shade': to_celsius(
                    extract_numeric_value(details.get('RealFeel Shade™')), unit
                ),
                'heat_index': to_celsius(
                    extract_numeric_value(details.get('Chỉ số nhiệt')), unit
                ),
                'dew_point': to_celsius(
                    extract_numeric_value(details.get('Điểm sương')), unit
                ),
                'precipitation_probability': (
                    extract_numeric_value(precip.get_text(strip=True)) if precip else None
                ),
                'precipitation': parse_precipitation_mm(
                    details.get('Mưa') or details.get('Lượng mưa')
                ),
                'humidity': extract_numeric_value(details.get('Độ ẩm')),
                'wind_speed': wind_speed,
                'wind_bearing': wind_deg,
                'wind_bearing_text': wind_text,
                'wind_gust_speed': gust_speed,
                'cloud_coverage': extract_numeric_value(details.get('Mật độ mây')),
                'uv_index': extract_numeric_value(details.get('Chỉ số UV tối đa')),
                'visibility': parse_distance_km(details.get('Tầm nhìn')),
                'cloud_ceiling': parse_length_m(details.get('Trần mây')),
                'air_quality': details.get('Chất lượng không khí'),
                'brightness': details.get('AccuLumen Brightness Index™'),
                'details': details
            })
        return hourly
    except Exception as e:
        _LOGGER.debug("parse_hourly_html: %s: %s", type(e).__name__, e)
        return []


async def get_hourly_forecast(
    fetcher: HtmlFetcher,
    location_key: str,
    location_slug: str,
    days: int = HOURLY_DAYS,
) -> list[dict[str, Any]]:
    """Get hourly forecast data.

    The default page only lists the hours left in the current day — two rows at
    22:00 — so the following days are fetched too. AccuWeather serves day 1..3
    (72 hours) without a subscription.
    """
    base = f"{BASE_URL}/vi/vn/{location_slug}/{location_key}/hourly-weather-forecast/{location_key}"
    headers = get_headers()
    hours: list[dict[str, Any]] = []

    for day in range(1, max(1, days) + 1):
        url = base if day == 1 else f"{base}?day={day}"
        if day > 1:
            # Same pacing as the coordinator uses between pages.
            await asyncio.sleep(0.5)

        html = await _fetch_with_retry(fetcher, url, headers)
        if html is None:
            continue

        try:
            parsed = await parse_hourly_html(html, day_offset=day - 1)
        except Exception as e:
            _LOGGER.debug("get_hourly_forecast: %s: %s - %s", type(e).__name__, e, url)
            continue

        _LOGGER.debug("get_hourly_forecast: parsed %d hours from %s", len(parsed), url)
        hours.extend(parsed)

    # Later pages repeat hours already seen when the day rolls over.
    seen: set[Any] = set()
    unique = []
    for hour in hours:
        marker = hour.get('timestamp') or (hour.get('day_offset'), hour.get('hour'))
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(hour)

    unique.sort(key=lambda h: h.get('timestamp') or 0)
    return unique


EMPTY_AIR_QUALITY: dict[str, Any] = {
    'aqi': None,
    'category': None,
    'description': None,
    'based_on': None,
    'pollutants': {},
    'daily': [],
}


async def parse_air_html(html: str) -> dict[str, Any]:
    """Parse the air quality page.

    Every selector here is scoped to a section id. The bare class names overflow
    badly across the page — ".statement" alone matches 17 elements (current
    reading, six pollutants, six scale steps, four forecast days) — which is why
    the unscoped ".air-quality-card .category" lookup never found the category.
    """
    try:
        soup = BeautifulSoup(html, 'html.parser')

        current = soup.select_one('#current') or soup.select_one('.air-quality-card')
        aqi = category = description = based_on = None
        if current:
            aqi = extract_numeric_value(
                el.get_text(strip=True)
                if (el := current.select_one('.aq-number')) else None
            )
            category = (
                el.get_text(strip=True)
                if (el := current.select_one('.category-text')) else None
            )
            description = (
                el.get_text(strip=True)
                if (el := current.select_one('.statement')) else None
            )
            based_on = (
                el.get_text(strip=True)
                if (el := current.select_one('.based-on')) else None
            )

        pollutant_root = soup.select_one('#pollutants') or soup
        pollutants = {}
        for pol in pollutant_root.select('.air-quality-pollutant'):
            qa = pol.get('data-qa', '')
            name = str(qa).replace('airQualityPollutant', '') if qa else None
            if not name:
                continue

            # Index and concentration are rendered twice (mobile and desktop
            # columns); take the first so the value is not doubled up.
            index_el = pol.select_one('.pollutant-index')
            conc_el = pol.select_one('.pollutant-concentration')
            conc_text = conc_el.get_text(strip=True) if conc_el else ''

            unit_match = re.search(
                r"(µg/m³|μg/m³|mg/m³|µg/m3|mg/m3|ppm|ppb|%)", conc_text
            )
            pollutants[name] = {
                'aqi': extract_numeric_value(
                    index_el.get_text(strip=True) if index_el else None
                ),
                'value': extract_numeric_value(conc_text),
                'unit': unit_match.group(1) if unit_match else None,
                'category': (
                    el.get_text(strip=True)
                    if (el := pol.select_one('.category')) else None
                ),
                'statement': (
                    el.get_text(strip=True)
                    if (el := pol.select_one('.statement')) else None
                ),
            }

        # Day-by-day AQI forecast. Note this differs from the current reading:
        # the current number reflects measured pollutants right now, the first
        # forecast entry is a whole-day outlook.
        daily = []
        for entry in soup.select('#daily .air-quality-content'):
            number = entry.select_one('.aq-number')
            if not number:
                continue
            daily.append({
                'day_of_week': (
                    el.get_text(strip=True)
                    if (el := entry.select_one('.day-of-week')) else None
                ),
                'date': (
                    el.get_text(strip=True)
                    if (el := entry.select_one('.date')) else None
                ),
                'aqi': extract_numeric_value(number.get_text(strip=True)),
                'category': (
                    el.get_text(strip=True)
                    if (el := entry.select_one('.category-text')) else None
                ),
                'statement': (
                    el.get_text(strip=True)
                    if (el := entry.select_one('.statement')) else None
                ),
            })

        _LOGGER.debug(
            "parse_air_html: aqi=%s category=%s pollutants=%d daily=%d",
            aqi, category, len(pollutants), len(daily),
        )
        return {
            'aqi': aqi,
            'category': category,
            'description': description,
            'based_on': based_on,
            'pollutants': pollutants,
            'daily': daily,
        }
    except Exception as e:
        _LOGGER.debug("parse_air_html: %s: %s", type(e).__name__, e)
        return dict(EMPTY_AIR_QUALITY)


async def get_air_quality(fetcher: HtmlFetcher, location_key: str, location_slug: str) -> dict[str, Any]:
    """Get air quality data (converted from get_air.py)."""
    url = f"{BASE_URL}/vi/vn/{location_slug}/{location_key}/air-quality-index/{location_key}"
    headers = get_headers()

    html = await _fetch_with_retry(fetcher, url, headers)
    if html is None:
        return dict(EMPTY_AIR_QUALITY)

    try:
        data = await parse_air_html(html)
        pollutant_count = len(data.get("pollutants", {}))
        _LOGGER.debug(
            "get_air_quality: parsed %d pollutants from %s", pollutant_count, url
        )
        return data
    except Exception as e:
        _LOGGER.debug("get_air_quality: %s: %s - %s", type(e).__name__, e, url)
        return dict(EMPTY_AIR_QUALITY)


async def parse_health_html(html: str, group_slug: str = '') -> list[dict[str, Any]]:
    """Parse health activities HTML.

    The page contains MULTIPLE 'indexListData' JavaScript variables, one per
    section (allergy health, outdoor, travel, home garden, pests, allergy other).
    We extract ALL of them and merge the results.

    The old HTML-link approach was WRONG - link text only shows activity name
    without the status, and the adjacent category text belongs to the PREVIOUS
    activity in the list.
    """
    try:
        result: list[dict[str, Any]] = []

        # Find ALL indexListData instances in the page
        index_list_matches = re.findall(
            r'var indexListData\s*=\s*(\[.*?\]);', html, re.DOTALL
        )

        if not index_list_matches:
            _LOGGER.debug(
                'parse_health_html: no indexListData found, returning empty list'
            )
            return result

        for json_str in index_list_matches:
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                _LOGGER.debug(
                    'parse_health_html: failed to decode indexListData JSON, skipping'
                )
                continue

            for item in data:
                result.append({
                    'name': item.get('name'),
                    'localizedName': item.get('localizedName'),
                    'value': item.get('value'),
                    'category': item.get('category'),
                    'localizedCategory': item.get('localizedCategory'),
                    'categoryPhrase': item.get('categoryPhrase'),
                    'categoryValue': item.get('categoryValue'),
                    'statusColor': item.get('statusColor'),
                    'type': item.get('type'),
                    'slug': item.get('slug'),
                    'indexDate': item.get('indexDate'),
                    'lifestyleCategory': item.get('lifestyleCategory'),
                    'categoryGroup': group_slug,
                })

        _LOGGER.debug(
            'parse_health_html: parsed %d health activities from %d sections',
            len(result), len(index_list_matches)
        )
        return result

    except Exception as e:
        _LOGGER.debug('parse_health_html: %s: %s', type(e).__name__, e)
        return []


async def crawl_all_health_activities(fetcher: HtmlFetcher, location_key: str, location_slug: str) -> dict[str, list[dict[str, Any]]]:
    """Crawl all health activities by category (converted from get_all_health.py).

    AccuWeather redesigned the site - all activities are listed on the main
    health-activities page. We crawl that page directly and do NOT fall back
    to individual category subpages (they return 404).
    """
    headers = get_headers()

    groups: dict[str, list[dict[str, Any]]] = {
        'allergy_health': [],
        'outdoor': [],
        'travel': [],
        'home_garden': [],
        'pests': [],
        'entertainment': [],
        'allergy_other': [],
        'other': []
    }

    slug_to_group = {
        'asthma': 'allergy_health', 'arthritis': 'allergy_health',
        'cold-flu': 'allergy_health', 'common-cold': 'allergy_health',
        'flu': 'allergy_health', 'migraine': 'allergy_health',
        'sinus': 'allergy_health',
        'running': 'outdoor', 'hiking': 'outdoor', 'biking': 'outdoor',
        'golf': 'outdoor', 'sun-sand': 'outdoor', 'fishing': 'outdoor',
        'astronomy': 'outdoor',
        'air-travel': 'travel', 'driving': 'travel',
        'lawn-mowing': 'home_garden', 'composting': 'home_garden',
        'mosquito-activity': 'pests', 'pest': 'pests',
        'indoor-pests': 'pests', 'outdoor-pests': 'pests',
        'outdoor-entertaining': 'entertainment',
        'dust-dander': 'allergy_other', 'pollen': 'allergy_other',
        'tree-pollen': 'allergy_other', 'grass-pollen': 'allergy_other',
        'ragweed-pollen': 'allergy_other',
    }

    # Chỉ crawl trang health-activities chính, KHÔNG crawl subpages (404)
    try:
        main_url = f"{BASE_URL}/vi/vn/{location_slug}/{location_key}/health-activities/{location_key}"
        html = await _fetch_with_retry(fetcher, main_url, headers)
        if html:
            activities = await parse_health_html(html, 'health')

            for activity in activities:
                slug = activity.get('slug', '')
                group = slug_to_group.get(slug, 'other')
                if group in groups:
                    groups[group].append(activity)

            _LOGGER.debug(
                "Health activities from main page: %d total across %d groups",
                len(activities), sum(1 for g in groups.values() if g)
            )
    except Exception as e:
        _LOGGER.debug("crawl_all: main page exception: %s: %s", type(e).__name__, e)

    total = sum(len(g) for g in groups.values())
    _LOGGER.debug("Health activities total: %d", total)
    return groups


async def get_minutecast_data(fetcher: HtmlFetcher, location_key: str, location_slug: str) -> dict[str, Any] | None:
    """Get MinuteCast data (minute-by-minute precipitation forecast)."""
    url = f"{BASE_URL}/vi/vn/{location_slug}/{location_key}/minute-weather-forecast/{location_key}"
    headers = get_headers()

    html = await _fetch_with_retry(fetcher, url, headers)
    if html is None:
        return None

    try:
        data = await parse_minutecast_html(html)
        _LOGGER.debug(
            "get_minutecast_data: summary='%s' from %s",
            data.get("summary", "")[:50], url
        )
        return data
    except Exception as e:
        _LOGGER.debug("get_minutecast_data: %s: %s - %s", type(e).__name__, e, url)
        return None


async def parse_minutecast_html(html: str) -> dict[str, Any]:
    """Parse the MinuteCast page.

    The page renders 240 minutes even though the headline says "at least 120".
    Each minute carries its precipitation intensity only as an inline
    border-left-color, so a minute counts as wet when that colour is set.
    """
    try:
        soup = BeautifulSoup(html, 'html.parser')

        current = soup.select_one('.minute-cast-chart .current-summary')
        summary = current_time = current_condition = None
        current_temp = realfeel = None
        unit = 'C'

        if current:
            if el := current.select_one('.summary'):
                summary = el.get_text(strip=True)
            if el := current.select_one('.conditions .time, .time'):
                current_time = el.get_text(strip=True)
            if el := current.select_one('.icon-phrase'):
                current_condition = el.get_text(strip=True)
            if el := current.select_one('.current-temp-unit'):
                unit = 'F' if el.get_text(strip=True).upper() == 'F' else 'C'
            if el := current.select_one('.current-temp'):
                current_temp = to_celsius(convert_temp_to_numeric(el.get_text(strip=True)), unit)
            if el := current.select_one('.realfeel-temp .value'):
                realfeel = to_celsius(convert_temp_to_numeric(el.get_text(strip=True)), unit)

        if not summary:
            if el := soup.select_one('.minute-cast-chart .summary'):
                summary = el.get_text(strip=True)

        # Minute-by-minute timeline.
        minutes = []
        wet_minutes = 0
        first_precip_time = None
        for minute in soup.select('.minute-by-minute .minute'):
            style = minute.get('style') or ''
            colour_match = re.search(r'border-left-color:\s*([^;]+)', style)
            colour = colour_match.group(1).strip() if colour_match else None
            has_precip = bool(colour) and colour.lower() != 'transparent'

            time_el = minute.select_one('.minute-inner .time')
            phrase_el = minute.select_one('.minute-inner .phrase')
            entry = {
                'time': time_el.get_text(strip=True) if time_el else None,
                'phrase': phrase_el.get_text(strip=True) if phrase_el else None,
                'color': colour,
                'precipitation': has_precip,
            }
            if has_precip:
                wet_minutes += 1
                if first_precip_time is None:
                    first_precip_time = entry['time']
            minutes.append(entry)

        _LOGGER.debug(
            "parse_minutecast_html: summary='%s' minutes=%d wet=%d",
            (summary or '')[:40], len(minutes), wet_minutes,
        )

        return {
            'summary': summary or 'Không có dữ liệu MinuteCast',
            'current_temperature': current_temp,
            'current_condition': current_condition,
            'realfeel': realfeel,
            'current_time': current_time,
            'minutes_total': len(minutes),
            'minutes_with_precipitation': wet_minutes,
            'precipitation_starts_at': first_precip_time,
            'minutes': minutes,
            'forecast_type': 'minutecast'
        }

    except Exception as e:
        _LOGGER.debug("parse_minutecast_html: %s: %s", type(e).__name__, e)
        return {
            'summary': 'Lỗi phân tích dữ liệu MinuteCast',
            'current_temperature': None,
            'current_condition': None,
            'realfeel': None,
            'current_time': None,
            'minutes_total': 0,
            'minutes_with_precipitation': 0,
            'precipitation_starts_at': None,
            'minutes': [],
            'forecast_type': 'minutecast'
        }
