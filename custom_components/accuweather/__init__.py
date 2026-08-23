"""AccuWeather custom component for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import (
    CONF_SENSOR_LANGUAGE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    SENSOR_LANGUAGE_AUTO,
)
from .coordinator import AccuWeatherDataUpdateCoordinator
from .i18n import resolve_language
from .utils import accept_language

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.WEATHER, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AccuWeather from a config entry."""
    _LOGGER.debug("Setting up AccuWeather integration")

    location_key = entry.data["location_key"]
    location_name = entry.data["location_name"]
    update_interval = entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    # One language for the whole integration: which AccuWeather locale to read,
    # and which language the storm sensors write their sentences in. Resolved
    # once here, so nothing further down has to know what "auto" means. The
    # options flow reloads the entry, which comes back through here.
    language = resolve_language(
        entry.data.get(CONF_SENSOR_LANGUAGE, SENSOR_LANGUAGE_AUTO),
        hass.config.language,
    )
    _LOGGER.debug("AccuWeather language resolved to %s", language)

    # A dedicated session keeps AccuWeather's cookies (unit, language) out of
    # Home Assistant's shared session. Home Assistant closes it on shutdown.
    session = async_create_clientsession(
        hass,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept-Language": accept_language(language),
        },
    )

    coordinator = AccuWeatherDataUpdateCoordinator(
        hass, session, location_key, location_name, entry, update_interval,
        language,
    )

    if coordinator.fetcher.using_impersonation:
        _LOGGER.debug("Using a browser TLS fingerprint for AccuWeather requests")
    else:
        _LOGGER.warning(
            "curl_cffi is not available, so AccuWeather requests will not carry a "
            "browser TLS fingerprint. Expect HTTP 403 on datacenter or VPN "
            "addresses; installing the curl_cffi requirement fixes it"
        )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # The aiohttp session is detached automatically when the entry unloads;
        # closing it here would only trip Home Assistant's "integration closes
        # the HA session" warning. The impersonated session is ours to close.
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.fetcher.close()

    return unload_ok
