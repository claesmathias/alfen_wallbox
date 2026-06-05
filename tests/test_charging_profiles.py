"""Tests for charging profiles feature (v3.1.0)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.alfen_wallbox.alfen import AlfenDevice
from custom_components.alfen_wallbox.const import DOMAIN, ID, VALUE
from custom_components.alfen_wallbox.sensor import AlfenMainSensor, ALFEN_SENSOR_TYPES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(name="mock_session")
def mock_session_fixture():
    """Mock aiohttp ClientSession."""
    session = MagicMock()
    session.verify = False
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.headers = {}
    mock_response.raise_for_status = MagicMock()
    mock_response.json = AsyncMock(return_value={"success": True})
    mock_post_ctx = MagicMock()
    mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_ctx.__aexit__ = AsyncMock(return_value=None)
    session.post = MagicMock(return_value=mock_post_ctx)
    return session


@pytest.fixture(name="alfen_device")
def alfen_device_fixture(mock_session):
    """Create an AlfenDevice instance."""
    device = AlfenDevice(
        session=mock_session,
        host="192.168.1.100",
        name="Test Wallbox",
        username="admin",
        password="secret",
        category_options=["generic", "states"],
        ssl=MagicMock(),
    )
    device.category_fetch_delay = 0
    device.max_allowed_phases = 3
    return device


@pytest.fixture(name="mock_coordinator")
def mock_coordinator_fixture():
    """Mock coordinator with a device that has max_allowed_phases=3."""
    coordinator = MagicMock()
    coordinator.device = MagicMock()
    coordinator.device.id = "alfen_test"
    coordinator.device.name = "Test Wallbox"
    coordinator.device.max_allowed_phases = 3
    coordinator.device.properties = {
        "205E_0": {ID: "205E_0", VALUE: 1, "cat": "generic"},
    }
    coordinator.device.latest_tag = None
    coordinator.device.get_number_of_sockets = MagicMock(return_value=1)
    coordinator.device.device_info = {
        "identifiers": {(DOMAIN, "test")},
        "name": "Test Wallbox",
    }
    return coordinator


@pytest.fixture(name="main_sensor")
def main_sensor_fixture(mock_coordinator):
    """Create an AlfenMainSensor entity backed by the mock coordinator."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.runtime_data = mock_coordinator
    sensor = AlfenMainSensor(entry, ALFEN_SENSOR_TYPES[0])
    return sensor


# ---------------------------------------------------------------------------
# AlfenDevice – get_charging_profiles
# ---------------------------------------------------------------------------


async def test_get_charging_profiles_returns_list(alfen_device: AlfenDevice):
    """get_charging_profiles returns unwrapped profiles from the id_list flow."""
    profile = {"chargingProfileId": 1}
    id_list = {"ChargingProfileIDs": [1]}
    wrapped = {"version": 2, "profile": {"csChargingProfiles": profile}}
    with patch.object(
        alfen_device, "_get", new=AsyncMock(side_effect=[id_list, wrapped])
    ):
        result = await alfen_device.get_charging_profiles()

    assert result == [profile]


async def test_get_charging_profiles_wraps_dict_in_list(alfen_device: AlfenDevice):
    """get_charging_profiles fetches each profile ID and returns them as a list."""
    profile = {"chargingProfileId": 42}
    id_list = {"ChargingProfileIDs": [42]}
    wrapped = {"version": 2, "profile": {"csChargingProfiles": profile}}
    with patch.object(
        alfen_device, "_get", new=AsyncMock(side_effect=[id_list, wrapped])
    ):
        result = await alfen_device.get_charging_profiles()

    assert result == [profile]


async def test_get_charging_profiles_returns_empty_on_none(alfen_device: AlfenDevice):
    """get_charging_profiles returns [] when the id_list API returns None."""
    with patch.object(alfen_device, "_get", new=AsyncMock(return_value=None)):
        result = await alfen_device.get_charging_profiles()

    assert result == []


async def test_get_charging_profiles_uses_correct_url(alfen_device: AlfenDevice):
    """get_charging_profiles first calls the ?id_list endpoint."""
    with patch.object(
        alfen_device, "_get", new=AsyncMock(return_value={"ChargingProfileIDs": []})
    ) as mock_get:
        await alfen_device.get_charging_profiles()

    called_url = mock_get.call_args_list[0].kwargs["url"]
    assert "chargingprofiles" in called_url
    assert "id_list" in called_url


# ---------------------------------------------------------------------------
# AlfenDevice – add_charging_profile
# ---------------------------------------------------------------------------


async def test_add_charging_profile_posts_schedule(alfen_device: AlfenDevice):
    """add_charging_profile calls _post with the provided schedule payload."""
    schedule = {"chargingProfileId": -19930828, "stackLevel": 0}
    with patch.object(alfen_device, "_post", new=AsyncMock(return_value={"success": True})) as mock_post:
        await alfen_device.add_charging_profile(schedule)

    mock_post.assert_called_once()
    cmd_arg = mock_post.call_args.kwargs.get("cmd") or mock_post.call_args.args[0]
    assert "chargingprofiles" in cmd_arg
    assert "add" in cmd_arg


async def test_add_charging_profile_sends_payload(alfen_device: AlfenDevice):
    """add_charging_profile forwards the schedule dict as POST payload."""
    schedule = {"chargingProfileId": -19930828, "stackLevel": 0, "data": "test"}
    with patch.object(alfen_device, "_post", new=AsyncMock(return_value=None)) as mock_post:
        await alfen_device.add_charging_profile(schedule)

    payload_arg = mock_post.call_args.kwargs.get("payload") or mock_post.call_args.args[1]
    assert payload_arg == schedule


# ---------------------------------------------------------------------------
# AlfenDevice – clear_charging_profiles
# ---------------------------------------------------------------------------


async def test_clear_charging_profiles_posts_clear_all(alfen_device: AlfenDevice):
    """clear_charging_profiles calls _post with ?clear=all."""
    with patch.object(alfen_device, "_post", new=AsyncMock(return_value={"success": True})) as mock_post:
        await alfen_device.clear_charging_profiles()

    mock_post.assert_called_once()
    cmd_arg = mock_post.call_args.kwargs.get("cmd") or mock_post.call_args.args[0]
    assert "chargingprofiles" in cmd_arg
    assert "clear=all" in cmd_arg


# ---------------------------------------------------------------------------
# AlfenMainSensor – async_get_charging_profiles
# ---------------------------------------------------------------------------


async def test_sensor_get_charging_profiles_returns_dict(main_sensor: AlfenMainSensor, mock_coordinator):
    """async_get_charging_profiles wraps the device result in a dict."""
    profiles = [{"chargingProfileId": 1}]
    mock_coordinator.device.get_charging_profiles = AsyncMock(return_value=profiles)

    result = await main_sensor.async_get_charging_profiles()

    assert result == {"charging_profiles": profiles}


async def test_sensor_get_charging_profiles_empty(main_sensor: AlfenMainSensor, mock_coordinator):
    """async_get_charging_profiles returns empty list key when no profiles."""
    mock_coordinator.device.get_charging_profiles = AsyncMock(return_value=[])

    result = await main_sensor.async_get_charging_profiles()

    assert result == {"charging_profiles": []}


# ---------------------------------------------------------------------------
# AlfenMainSensor – async_add_charging_profile
# ---------------------------------------------------------------------------


async def test_sensor_add_daily_profile_builds_correct_schedule(main_sensor: AlfenMainSensor, mock_coordinator):
    """async_add_charging_profile builds a correct OCPP profile for DAILY recurrence."""
    mock_coordinator.device.add_charging_profile = AsyncMock()

    await main_sensor.async_add_charging_profile(
        start_time="08:00",
        stop_time="10:00",
        max_current=16,
        recurrency="DAILY",
        days=[],
    )

    mock_coordinator.device.add_charging_profile.assert_called_once()
    schedule = mock_coordinator.device.add_charging_profile.call_args.args[0]

    assert schedule["chargingProfilePurpose"] == "TxDefaultProfile"
    assert schedule["chargingProfileKind"] == "Recurring"
    assert schedule["recurrencyKind"] == "DAILY"
    assert schedule["stackLevel"] == 0

    periods = schedule["chargingSchedule"]["chargingSchedulePeriod"]
    assert len(periods) == 2
    # 08:00 = 8*3600 = 28800 s
    assert periods[0]["startPeriod"] == 28800
    assert periods[0]["limit"] == 16
    # 10:00 = 10*3600 = 36000 s
    assert periods[1]["startPeriod"] == 36000
    assert periods[1]["limit"] == 0


async def test_sensor_add_profile_duration_is_positive(main_sensor: AlfenMainSensor, mock_coordinator):
    """async_add_charging_profile calculates a positive duration for same-day slots."""
    mock_coordinator.device.add_charging_profile = AsyncMock()

    await main_sensor.async_add_charging_profile(
        start_time="22:00",
        stop_time="23:00",
        max_current=10,
        recurrency="DAILY",
        days=[],
    )

    schedule = mock_coordinator.device.add_charging_profile.call_args.args[0]
    assert schedule["chargingSchedule"]["duration"] == 3600  # 1 hour


async def test_sensor_add_profile_midnight_wrap(main_sensor: AlfenMainSensor, mock_coordinator):
    """async_add_charging_profile wraps duration when stop < start (overnight slot)."""
    mock_coordinator.device.add_charging_profile = AsyncMock()

    await main_sensor.async_add_charging_profile(
        start_time="22:00",
        stop_time="06:00",
        max_current=8,
        recurrency="DAILY",
        days=[],
    )

    schedule = mock_coordinator.device.add_charging_profile.call_args.args[0]
    # 22:00 -> 06:00 = 8 hours = 28800 s
    assert schedule["chargingSchedule"]["duration"] == 8 * 3600


async def test_sensor_add_weekly_profile_includes_days(main_sensor: AlfenMainSensor, mock_coordinator):
    """async_add_charging_profile includes daysOfWeek for WEEKLY recurrence."""
    mock_coordinator.device.add_charging_profile = AsyncMock()

    await main_sensor.async_add_charging_profile(
        start_time="09:00",
        stop_time="11:00",
        max_current=20,
        recurrency="WEEKLY",
        days=["Monday", "Wednesday", "Friday"],
    )

    schedule = mock_coordinator.device.add_charging_profile.call_args.args[0]
    assert schedule["recurrencyKind"] == "WEEKLY"
    assert schedule["daysOfWeek"] == ["Monday", "Wednesday", "Friday"]


async def test_sensor_add_weekly_profile_no_days_omits_key(main_sensor: AlfenMainSensor, mock_coordinator):
    """async_add_charging_profile omits daysOfWeek when days list is empty."""
    mock_coordinator.device.add_charging_profile = AsyncMock()

    await main_sensor.async_add_charging_profile(
        start_time="09:00",
        stop_time="11:00",
        max_current=20,
        recurrency="WEEKLY",
        days=[],
    )

    schedule = mock_coordinator.device.add_charging_profile.call_args.args[0]
    assert "daysOfWeek" not in schedule


async def test_sensor_add_profile_uses_max_allowed_phases(main_sensor: AlfenMainSensor, mock_coordinator):
    """async_add_charging_profile uses device.max_allowed_phases in schedule periods."""
    mock_coordinator.device.max_allowed_phases = 1
    mock_coordinator.device.add_charging_profile = AsyncMock()

    await main_sensor.async_add_charging_profile(
        start_time="08:00",
        stop_time="09:00",
        max_current=16,
        recurrency="DAILY",
        days=[],
    )

    schedule = mock_coordinator.device.add_charging_profile.call_args.args[0]
    for period in schedule["chargingSchedule"]["chargingSchedulePeriod"]:
        assert period["numberPhases"] == 1


async def test_sensor_add_profile_charging_rate_unit_is_amps(main_sensor: AlfenMainSensor, mock_coordinator):
    """async_add_charging_profile uses 'A' (Amperes) as the chargingRateUnit."""
    mock_coordinator.device.add_charging_profile = AsyncMock()

    await main_sensor.async_add_charging_profile(
        start_time="07:30",
        stop_time="08:30",
        max_current=32,
        recurrency="DAILY",
        days=[],
    )

    schedule = mock_coordinator.device.add_charging_profile.call_args.args[0]
    assert schedule["chargingSchedule"]["chargingRateUnit"] == "A"


# ---------------------------------------------------------------------------
# AlfenMainSensor – async_clear_charging_profiles
# ---------------------------------------------------------------------------


async def test_sensor_clear_charging_profiles_calls_device(main_sensor: AlfenMainSensor, mock_coordinator):
    """async_clear_charging_profiles delegates to device.clear_charging_profiles."""
    mock_coordinator.device.clear_charging_profiles = AsyncMock()

    await main_sensor.async_clear_charging_profiles()

    mock_coordinator.device.clear_charging_profiles.assert_called_once()
