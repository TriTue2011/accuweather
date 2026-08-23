"""Config flow for AccuWeather integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.config_entries import ConfigEntry

from .const import (
    DOMAIN,
    CONF_LANDFALL_COUNTRY,
    CONF_LOCATION_KEY,
    CONF_LOCATION_NAME,
    CONF_SENSOR_LANGUAGE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_LANDFALL_COUNTRY,
    DEFAULT_UPDATE_INTERVAL,
    LANDFALL_COUNTRY_BY_CODE,
    MIN_UPDATE_INTERVAL,
    MAX_UPDATE_INTERVAL,
    SENSOR_LANGUAGE_AUTO,
    SENSOR_LANGUAGES,
)
from .fetcher import HtmlFetcher
from .i18n import resolve_language
from .utils import get_location_keys
from .windy import landfall_countries, place_name

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("location"): str,
    }
)


def country_selector(hass) -> SelectSelector:
    """Dropdown of every coast a landfall can be watched on.

    The stored value is the country name as the coastline data spells it, which
    is Vietnamese; only the label follows the interface language.
    """
    language = resolve_language(None, hass.config.language)
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=country, label=place_name(country, language))
                for country in sorted(
                    landfall_countries(), key=lambda c: place_name(c, language)
                )
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def country_for_code(code: str | None) -> str:
    """Which coast to watch, from the country code of the location picked.

    The search result states the country as an ISO code — "VN", "TH", "JP" —
    which is the one part of it that does not move with the language of the
    query. A country with no coast in the tracked basin, Laos say, has no code
    here and leaves the default in place for the person setting up to change.
    """
    return LANDFALL_COUNTRY_BY_CODE.get(
        (code or "").upper(), DEFAULT_LANDFALL_COUNTRY
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AccuWeather."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._locations: list[tuple[str, str, str, str | None]] = []
        self._selected_location_key: str = ""
        self._selected_location_name: str = ""
        # Where the landfall country option starts from.
        self._selected_country_code: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            try:
                # Same browser-fingerprint transport the coordinator uses, so
                # searching works on networks where plain requests are blocked.
                fetcher = HtmlFetcher(async_get_clientsession(self.hass))
                location_query = user_input["location"]

                try:
                    self._locations = await get_location_keys(
                        fetcher, location_query
                    )
                finally:
                    await fetcher.close()
                
                if not self._locations:
                    errors["base"] = "no_locations"
                else:
                    # Always show selection step, even with 1 result for confirmation
                    return await self.async_step_select_location()
                    
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_select_location(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle location selection step."""
        if user_input is not None:
            selected_location = user_input["location_choice"]
            
            # Find selected location and store for next step
            for location_key, location_name, long_name, country in self._locations:
                if f"{location_key}|{location_name}" == selected_location:
                    self._selected_location_key = location_key
                    self._selected_location_name = location_name
                    self._selected_country_code = country
                    
                    # Move to update interval configuration
                    return await self.async_step_update_interval()
            
            return self.async_abort(reason="invalid_selection")
        
        # Create options for location selection
        location_options = {}
        for location_key, location_name, long_name, _country in self._locations:
            display_name = f"{location_name} ({long_name})" if long_name else location_name
            location_options[f"{location_key}|{location_name}"] = display_name
        
        data_schema = vol.Schema({
            vol.Required("location_choice"): vol.In(location_options)
        })
        
        return self.async_show_form(
            step_id="select_location",
            data_schema=data_schema,
            description_placeholders={"location_count": str(len(self._locations))}
        )

    async def async_step_update_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle update interval configuration step."""
        if user_input is not None:
            update_interval = user_input.get("update_interval", DEFAULT_UPDATE_INTERVAL)
            
            # Check if already configured
            await self.async_set_unique_id(self._selected_location_key)
            self._abort_if_unique_id_configured()
            
            return self.async_create_entry(
                title=self._selected_location_name,
                data={
                    CONF_LOCATION_KEY: self._selected_location_key,
                    CONF_LOCATION_NAME: self._selected_location_name,
                    CONF_UPDATE_INTERVAL: update_interval,
                    CONF_LANDFALL_COUNTRY: user_input.get(
                        CONF_LANDFALL_COUNTRY, DEFAULT_LANDFALL_COUNTRY
                    ),
                }
            )
        
        # Show update interval configuration form
        data_schema = vol.Schema({
            vol.Optional(
                "update_interval", 
                default=DEFAULT_UPDATE_INTERVAL
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL)),
            vol.Optional(
                CONF_LANDFALL_COUNTRY,
                default=country_for_code(self._selected_country_code),
            ): country_selector(self.hass),
        })
        
        return self.async_show_form(
            step_id="update_interval",
            data_schema=data_schema,
            description_placeholders={
                "location_name": self._selected_location_name,
                "default_interval": str(DEFAULT_UPDATE_INTERVAL // 60),
                "min_interval": str(MIN_UPDATE_INTERVAL // 60),
                "max_interval": str(MAX_UPDATE_INTERVAL // 60),
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Create the options flow."""
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for AccuWeather."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Update the config entry data with new update interval
            new_data = dict(self.config_entry.data)
            new_data[CONF_UPDATE_INTERVAL] = user_input.get("update_interval", DEFAULT_UPDATE_INTERVAL)
            new_data[CONF_SENSOR_LANGUAGE] = user_input.get(
                CONF_SENSOR_LANGUAGE, SENSOR_LANGUAGE_AUTO
            )
            new_data[CONF_LANDFALL_COUNTRY] = user_input.get(
                CONF_LANDFALL_COUNTRY, DEFAULT_LANDFALL_COUNTRY
            )

            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )

            # Reload the entry to apply new update interval
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)

            return self.async_create_entry(title="", data={})

        current_interval = self.config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        current_language = self.config_entry.data.get(
            CONF_SENSOR_LANGUAGE, SENSOR_LANGUAGE_AUTO
        )
        current_country = self.config_entry.data.get(
            CONF_LANDFALL_COUNTRY, DEFAULT_LANDFALL_COUNTRY
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    "update_interval",
                    default=current_interval
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL)),
                vol.Optional(
                    CONF_SENSOR_LANGUAGE,
                    default=current_language,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(SENSOR_LANGUAGES),
                        translation_key=CONF_SENSOR_LANGUAGE,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_LANDFALL_COUNTRY,
                    default=current_country,
                ): country_selector(self.hass),
            }),
            description_placeholders={
                "current_interval": str(current_interval // 60),
                "min_interval": str(MIN_UPDATE_INTERVAL // 60),
                "max_interval": str(MAX_UPDATE_INTERVAL // 60),
            }
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
