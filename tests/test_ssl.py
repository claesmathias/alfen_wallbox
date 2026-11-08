"""The wallbox SSL context must be private (not Home Assistant's shared one)."""

import ssl

from homeassistant.util.ssl import get_default_context
import pytest

from custom_components.alfen_wallbox.coordinator import _create_ssl_context


@pytest.fixture(name="mock_ssl_context")
def real_ssl_context_fixture():
    """Use the real context factory in this module (overrides the autouse mock)."""
    yield None


def test_ssl_context_is_private() -> None:
    """Disabling verification for the wallbox leaves the shared context untouched."""
    shared = get_default_context()
    before = (shared.check_hostname, shared.verify_mode)
    context = _create_ssl_context()
    assert context is not shared
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False
    assert (shared.check_hostname, shared.verify_mode) == before


async def test_coordinator_setup_keeps_shared_ssl_context_verifying(
    hass, mock_config_entry, mock_aiohttp_session
) -> None:
    """Setting up the coordinator leaves the shared context verifying certificates."""
    from unittest.mock import AsyncMock, patch

    from custom_components.alfen_wallbox.coordinator import AlfenCoordinator

    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.alfen_wallbox.coordinator.AlfenDevice", autospec=True
    ) as mock_device_class:
        mock_device_class.return_value.init = AsyncMock(return_value=True)
        mock_device_class.return_value.import_transactions = lambda data: None
        coordinator = AlfenCoordinator(hass, mock_config_entry)
        await coordinator._async_setup()
        device_context = mock_device_class.call_args.args[6]

    shared = get_default_context()
    assert device_context is not shared
    assert device_context.verify_mode == ssl.CERT_NONE
    assert shared.verify_mode == ssl.CERT_REQUIRED
    assert shared.check_hostname is True
