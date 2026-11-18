"""Config flow: reuse an existing FRITZ!Box Tools entry or enter credentials."""

from __future__ import annotations

import logging
from typing import Any

from fritzconnection.core.exceptions import (
    FritzActionError,
    FritzAuthorizationError,
    FritzConnectionException,
    FritzServiceError,
)
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
)
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .collectors.fritz import FritzCredentials, FritzSource
from .const import (
    CONF_FRITZ_ENTRY_ID,
    CONF_SOURCE_ENTRY,
    DEFAULT_HOST,
    DOMAIN,
    MANUAL_ENTRY,
)
from .coordinator import credentials_from_data

_LOGGER = logging.getLogger(__name__)

FRITZ_DOMAIN = "fritz"


class NetworkTopologyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    async def _async_test(self, creds: FritzCredentials) -> dict[str, str]:
        try:
            mesh = await self.hass.async_add_executor_job(
                FritzSource(creds).fetch_mesh
            )
        except FritzAuthorizationError:
            return {"base": "invalid_auth"}
        except (FritzActionError, FritzServiceError):
            return {"base": "mesh_unsupported"}
        except (FritzConnectionException, OSError):
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error while testing the FRITZ!Box")
            return {"base": "unknown"}
        if not isinstance(mesh, dict) or not mesh.get("nodes"):
            return {"base": "mesh_unsupported"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a FRITZ!Box Tools entry, or switch to manual input."""
        fritz_entries = self.hass.config_entries.async_entries(FRITZ_DOMAIN)
        if not fritz_entries:
            return await self.async_step_manual()

        errors: dict[str, str] = {}
        if user_input is not None:
            choice = user_input[CONF_SOURCE_ENTRY]
            if choice == MANUAL_ENTRY:
                return await self.async_step_manual()
            fritz_entry = self.hass.config_entries.async_get_entry(choice)
            if fritz_entry is None:
                errors["base"] = "unknown"
            else:
                errors = await self._async_test(credentials_from_data(dict(fritz_entry.data)))
                if not errors:
                    return self.async_create_entry(
                        title=fritz_entry.title,
                        data={CONF_FRITZ_ENTRY_ID: fritz_entry.entry_id},
                    )

        options = [
            SelectOptionDict(value=e.entry_id, label=e.title) for e in fritz_entries
        ]
        options.append(SelectOptionDict(value=MANUAL_ENTRY, label="Enter manually"))
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SOURCE_ENTRY, default=fritz_entries[0].entry_id
                ): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter FRITZ!Box credentials by hand."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_test(credentials_from_data(user_input))
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_HOST], data=user_input
                )

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, DEFAULT_HOST)): str,
                vol.Optional(CONF_PORT): int,
                vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_SSL, default=defaults.get(CONF_SSL, False)): bool,
            }
        )
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)
