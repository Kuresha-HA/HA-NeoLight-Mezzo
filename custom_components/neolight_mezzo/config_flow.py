"""Config flow placeholder pending verification of NeoLight cloud auth.

The official app embeds a ThingClips/ThingSmart-derived SDK, but the APK
inspection so far has not identified the effective NeoLight API host, app
credentials, request-signing scheme, or login sequence. Collecting a password
before those are known would be unsafe and would not produce a working login.
"""

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class NeoLightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NeoLight MEZZO."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Stop setup until a verified login implementation is available."""
        return self.async_abort(reason="cloud_auth_not_implemented")
