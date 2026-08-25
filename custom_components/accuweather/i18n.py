"""Language of the data, and every sentence this integration writes itself.

Entity *names* come from translations/<lang>.json, which Home Assistant reads on
its own. Everything a sensor actually says does not: part of it is scraped from
AccuWeather, which serves a different page per language, and part of it is
composed here — storm bulletins, landfall estimates, fallback text. Both follow
the language chosen in the options, so a dashboard does not end up half English
and half Vietnamese.

Adding a language means three things: a translations/<lang>.json for the names,
its labels in const.DETAIL_LABELS so the forecast pages still parse, and an
entry in _TEXT below.
"""
from __future__ import annotations

from .const import SENSOR_LANGUAGE_AUTO

# Languages with both a page-label set and a text table here. AccuWeather serves
# many more, but a locale without labels parses to empty sensors.
LANGUAGES: tuple[str, ...] = ("vi", "en")

# Where "auto" lands when Home Assistant runs in a language this integration
# does not cover. English is the one AccuWeather always has.
FALLBACK_LANGUAGE = "en"


def resolve_language(configured: str | None, ha_language: str | None) -> str:
    """Which language to fetch and write in.

    `configured` is the option; "auto" (or missing) follows the language set in
    Home Assistant's own settings, which is what an unconfigured install wants.
    """
    if configured and configured != SENSOR_LANGUAGE_AUTO:
        if configured in LANGUAGES:
            return configured
        return FALLBACK_LANGUAGE

    # "vi-VN" and "en-GB" are the same language as far as these pages go.
    code = (ha_language or "").split("-")[0].lower()
    return code if code in LANGUAGES else FALLBACK_LANGUAGE


# Sentences and fragments, by language. Placeholders are named so that word
# order can differ: Vietnamese puts the distance first, English the direction.
_TEXT: dict[str, dict[str, str]] = {
    "vi": {
        # Storm intensity, on the Beaufort scale Vietnamese bulletins use.
        "storm_class_super": "Siêu bão",
        "storm_class_very_strong": "Bão rất mạnh",
        "storm_class_strong": "Bão mạnh",
        "storm_class_typhoon": "Bão",
        "storm_class_depression": "Áp thấp nhiệt đới",
        "storm_class_low": "Vùng áp thấp",
        # One storm, read out in a single line.
        "storm_force": "{headline} cấp {beaufort}",
        "storm_distance_direction": "cách {km} km về phía {direction}",
        "storm_distance": "cách {km} km",
        "movement": "Di chuyển hướng {direction}",
        "movement_with_speed": "Di chuyển hướng {direction}, {speed} km/h",
        "summary_landfall_past": "{line} — đã vào {place}",
        "summary_landfall_forecast": "{line} — dự kiến vào {place}",
        "summary_landfall_time": "{line} lúc {when}",
        # The landfall sentence, in full.
        "landfall_none_coast": (
            "Chưa có dấu hiệu vào đất liền; gần bờ {place} nhất khoảng {km} km"
        ),
        "landfall_none_offshore": "Đang ở ngoài khơi, chưa có đất liền nào trong tầm",
        "landfall_past": "Đã vào {place}",
        "landfall_past_time": "Đã vào {place} lúc {when}",
        "landfall_forecast": "Dự kiến vào {place}",
        "landfall_forecast_time": "Dự kiến vào {place} khoảng {when}",
        "landfall_remaining": "còn khoảng {km} km",
        "landfall_remaining_hours": "còn khoảng {km} km (~{hours} giờ nữa)",
        "landfall_from_home": "cách bạn {km} km",
        "landfall_force_past": "cấp {beaufort} khi vào bờ",
        "landfall_force_forecast": "cấp {beaufort} khi đổ bộ",
        "landfall_model": " (theo {model})",
        # Bao nhiêu mô hình cùng cho ra một điểm đổ bộ, và chúng lệch nhau
        # bao xa — thước đo trung thực cho việc tin nơi và giờ nói ở trên.
        "landfall_model_spread": (
            " (theo {model}; {agree}/{total} mô hình cùng hướng, lệch {km} km)"
        ),
        "landfall_model_lone": (
            " (theo {model}; chỉ {agree}/{total} mô hình cho vào bờ)"
        ),
        # Cơn bão nào, đứng trước câu dự báo đổ bộ.
        "landfall_named": "{storm}: {line}",
        # Sensor states with nothing to report.
        "no_storm": "Không có bão",
        "movement_unknown": "Chưa xác định hướng di chuyển",
        "landfall_unknown": "Chưa có dấu hiệu vào đất liền",
        "landfall_none_country": "Không có bão đổ bộ {country}",
        "bulletin_none": "Chưa có bản tin",
        "minutecast_unavailable": "Không có dữ liệu MinuteCast",
        "minutecast_error": "Lỗi phân tích dữ liệu MinuteCast",
        "health_unknown": "Không rõ",
        # Why the update failed, and what to do about it.
        "blocked": (
            "AccuWeather từ chối yêu cầu (HTTP {status}) — trang web đang chặn "
            "truy cập tự động từ địa chỉ IP này. {hint}"
        ),
        "blocked_hint_impersonated": (
            "Đã dùng dấu vết trình duyệt mà vẫn bị chặn — địa chỉ IP này có thể "
            "bị đánh dấu. Thử đổi máy chủ VPN, hoặc tắt VPN cho Home Assistant, "
            "hoặc tăng thời gian cập nhật."
        ),
        "blocked_hint_plain": (
            "Thư viện curl_cffi chưa cài được nên yêu cầu không mang dấu vết "
            "trình duyệt; đây là nguyên nhân phổ biến nhất khi chạy qua VPN. "
            "Xem log lúc khởi động để biết vì sao cài thất bại."
        ),
    },
    "en": {
        "storm_class_super": "Super typhoon",
        "storm_class_very_strong": "Very strong typhoon",
        "storm_class_strong": "Strong typhoon",
        "storm_class_typhoon": "Typhoon",
        "storm_class_depression": "Tropical depression",
        "storm_class_low": "Low pressure area",
        "storm_force": "{headline}, force {beaufort}",
        "storm_distance_direction": "{km} km to the {direction}",
        "storm_distance": "{km} km away",
        "movement": "Moving {direction}",
        "movement_with_speed": "Moving {direction} at {speed} km/h",
        "summary_landfall_past": "{line} — came ashore in {place}",
        "summary_landfall_forecast": "{line} — expected to reach {place}",
        "summary_landfall_time": "{line} at {when}",
        "landfall_none_coast": (
            "No sign of landfall yet; nearest coast is {place}, about {km} km away"
        ),
        "landfall_none_offshore": "Out at sea, with no land within range",
        "landfall_past": "Came ashore in {place}",
        "landfall_past_time": "Came ashore in {place} at {when}",
        "landfall_forecast": "Expected to reach {place}",
        "landfall_forecast_time": "Expected to reach {place} around {when}",
        "landfall_remaining": "{km} km still to travel",
        "landfall_remaining_hours": "{km} km still to travel (~{hours} h away)",
        "landfall_from_home": "{km} km from you",
        "landfall_force_past": "force {beaufort} at landfall",
        "landfall_force_forecast": "force {beaufort} at landfall",
        "landfall_model": " (per {model})",
        "landfall_model_spread": (
            " (per {model}; {agree} of {total} models agree, {km} km apart)"
        ),
        "landfall_model_lone": (
            " (per {model}; only {agree} of {total} models bring it ashore)"
        ),
        "landfall_named": "{storm}: {line}",
        "no_storm": "No storms",
        "movement_unknown": "Direction of travel not yet known",
        "landfall_unknown": "No sign of landfall yet",
        "landfall_none_country": "No storm heading for {country}",
        "bulletin_none": "No bulletin",
        "minutecast_unavailable": "No MinuteCast data",
        "minutecast_error": "Could not read the MinuteCast data",
        "health_unknown": "Unknown",
        "blocked": (
            "AccuWeather refused the request (HTTP {status}) — the site is "
            "blocking automated access from this IP address. {hint}"
        ),
        "blocked_hint_impersonated": (
            "The requests already carry a browser TLS fingerprint and are still "
            "blocked, so this IP address is probably flagged. Try another VPN "
            "server, turn the VPN off for Home Assistant, or raise the update "
            "interval."
        ),
        "blocked_hint_plain": (
            "curl_cffi could not be installed, so the requests carry no browser "
            "TLS fingerprint — the most common cause when running through a "
            "VPN. The startup log says why the install failed."
        ),
    },
}


def text(language: str, key: str, **placeholders: object) -> str:
    """One phrase in `language`, falling back to English if it is missing."""
    table = _TEXT.get(language) or _TEXT[FALLBACK_LANGUAGE]
    template = table.get(key) or _TEXT[FALLBACK_LANGUAGE][key]
    return template.format(**placeholders) if placeholders else template
