"""Tests for the Eve Connect compatible charging helpers."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.alfen_wallbox import charging
from custom_components.alfen_wallbox.alfen import AlfenDevice, ChargingProfileError, validate_slots
from custom_components.alfen_wallbox.charging import TimeSlot

# ---------------------------------------------------------------------------
# IDs and maths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (4275036468, -19930828),  # max power, unsigned form
        (4275396292, -19571004),  # boost
        (4282845288, -12122008),  # pause
        (-19930828, -19930828),
        ("234202401", 234202401),
        ("nope", None),
        (None, None),
    ],
)
def test_normalize_profile_id(raw, expected):
    """Unsigned 32-bit IDs are converted to the signed IDs the app uses."""
    assert charging.normalize_profile_id(raw) == expected


@pytest.mark.parametrize(
    ("power", "phases", "expected"),
    [
        (11, 3, (15.9, 3)),
        (22.1, 3, (32.0, 3)),
        (7.4, 1, (32.2, 1)),
        (3.7, 3, (16.1, 1)),  # 5.4 A per phase < 6 A -> single phase
        (1.4, 3, (6.1, 1)),
    ],
)
def test_power_to_current(power, phases, expected):
    """kW to amps uses the app's rounding and single-phase fallback."""
    assert charging.power_to_current(power, phases) == expected


def test_current_to_power():
    """Amps x phases x 230 V."""
    assert charging.current_to_power(16, 3) == 11.0
    assert charging.current_to_power(32, 1) == 7.4


def test_active_phases():
    """Phases count when above 80 V; fall back to the installation setting."""
    assert charging.active_phases([230, 231, 229]) == 3
    assert charging.active_phases([230, 0, 0.5]) == 1
    assert charging.active_phases([], fallback=1) == 1
    assert charging.active_phases(["x"]) == 3


# ---------------------------------------------------------------------------
# Request builders
# ---------------------------------------------------------------------------


def test_build_schedule_day_request_matches_app_format():
    """Day profiles mirror the app: ID per weekday, stack 11-day, anchor 2024-04-0N."""
    tz = ZoneInfo("Europe/Amsterdam")
    request = charging.build_schedule_day_request(
        2, [TimeSlot(79200, 86400, 16, 3), TimeSlot(3600, 7200, 10, 1)], tz
    )
    assert request["connectorId"] == 0
    profile = request["csChargingProfiles"]
    assert profile["chargingProfileId"] == 234202403  # Wednesday
    assert profile["stackLevel"] == 8
    assert profile["chargingProfileKind"] == "Recurring"
    assert profile["recurrencyKind"] == "Weekly"
    assert profile["chargingProfilePurpose"] == "ChargingStationExternalConstraints"
    schedule = profile["chargingSchedule"]
    # Local midnight Wednesday 2024-04-03 (CEST) serialised as UTC like JS toISOString
    assert schedule["startSchedule"] == "2024-04-02T22:00:00.000Z"
    assert schedule["duration"] == 86400
    # Leading 0/1 periods mirror the app; OCPP needs the first period at 0
    assert schedule["chargingSchedulePeriod"] == [
        {"startPeriod": 0, "limit": 0, "numberPhases": 1},
        {"startPeriod": 1, "limit": 0, "numberPhases": 1},
        {"startPeriod": 3600, "limit": 10, "numberPhases": 1},
        {"startPeriod": 7200, "limit": 0, "numberPhases": 1},
        {"startPeriod": 79200, "limit": 16, "numberPhases": 3},
        {"startPeriod": 86400, "limit": 0, "numberPhases": 3},
    ]


def test_build_pause_and_apply_schedule_requests():
    """Pause = stack 1000 limit 0; apply schedule = stack 1 limit 0."""
    pause = charging.build_pause_request()["csChargingProfiles"]
    assert (pause["chargingProfileId"], pause["stackLevel"]) == (-12122008, 1000)
    apply = charging.build_apply_schedule_request()["csChargingProfiles"]
    assert (apply["chargingProfileId"], apply["stackLevel"]) == (234202408, 1)


def test_wrap_profile_request_is_idempotent():
    """Already wrapped requests are left alone."""
    wrapped = charging.wrap_profile_request({"chargingProfileId": 1})
    assert charging.wrap_profile_request(wrapped) is wrapped


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

EVE_RESPONSE = {
    "version": 2,
    "profile": {
        "connectorId": 0,
        "csChargingProfiles": {
            "chargingProfileId": 234202405,
            "chargingProfileKind": "Recurring",
            "recurrencyKind": "Weekly",
            "startSchedule": "2024-04-04T22:00:00.000Z",
            "startPeriod": [0, 1, 33300, 64800],
            "limit": [0.0, 0.0, 15.9, 0.0],
            "numberPhases": [1, 1, 3, 3],
        },
    },
}


def test_unwrap_and_slots_flat_format():
    """The wallbox's flat-array response becomes one 09:15-18:00 slot on Friday."""
    profile = charging.unwrap_profile(EVE_RESPONSE)
    assert profile["chargingProfileId"] == 234202405
    assert charging.profile_slots(profile) == [TimeSlot(33300, 64800, 15.9, 3)]
    assert charging.profile_weekday(profile) == 4


def test_profile_weekday_from_anchor_for_unknown_ids():
    """Non-app weekly profiles use the anchor, robust to the UTC serialisation."""
    profile = {"chargingProfileId": 5, "startSchedule": "2024-03-31T22:00:00.000Z"}
    assert charging.profile_weekday(profile) == 0  # Monday local midnight in CEST
    profile = {"chargingProfileId": 5, "startSchedule": "2024-04-01T05:00:00.000Z"}
    assert charging.profile_weekday(profile) == 0  # Monday local midnight in UTC-5


def test_schedule_from_profiles_mixed_formats():
    """Daily, weekly-with-days and Eve day profiles are combined per weekday."""
    daily = {
        "recurrencyKind": "DAILY",
        "chargingSchedule": {
            "chargingSchedulePeriod": [
                {"startPeriod": 0, "limit": 6, "numberPhases": 1},
                {"startPeriod": 3600, "limit": 0, "numberPhases": 1},
            ]
        },
    }
    weekly = {**daily, "recurrencyKind": "WEEKLY", "daysOfWeek": ["Sunday"]}
    eve = charging.unwrap_profile(EVE_RESPONSE)
    schedule = charging.schedule_from_profiles([daily, weekly, eve])
    assert len(schedule[0]) == 1
    assert len(schedule[4]) == 2  # daily + Friday profile
    assert len(schedule[6]) == 2  # daily + weekly Sunday


def test_active_slot():
    """The slot containing 'now' is returned."""
    schedule = {day: [] for day in range(7)}
    schedule[0] = [TimeSlot(3600, 7200, 16, 3)]
    monday = datetime.datetime(2024, 1, 1, 1, 30)
    assert charging.active_slot(schedule, monday) == TimeSlot(3600, 7200, 16, 3)
    assert charging.active_slot(schedule, monday.replace(hour=3)) is None


def test_boost_end_and_max_power():
    """Boost ends 3 h after its start; max power profile maps back to kW."""
    boost = {"startSchedule": "2024-01-01T10:00:00.000Z", "duration": 10800}
    assert charging.boost_end(boost) == datetime.datetime(2024, 1, 1, 13, 0, tzinfo=datetime.UTC)
    max_power = {
        "chargingProfileKind": "Relative",
        "startPeriod": [0],
        "limit": [15.9],
        "numberPhases": [3],
    }
    assert charging.max_power_from_profile(max_power) == 11.0
    assert charging.max_power_from_profile({**max_power, "chargingProfileKind": "Recurring"}) is None


def test_hhmm_conversions():
    """HH:MM parsing and formatting, including 24:00."""
    assert charging.hhmm_to_seconds("06:30") == 23400
    assert charging.hhmm_to_seconds("24:00") == 86400
    assert charging.hhmm_to_seconds(datetime.time(22, 15)) == 80100
    assert charging.seconds_to_hhmm(86400) == "24:00"
    with pytest.raises(ValueError):
        charging.hhmm_to_seconds("25:00")


def test_validate_slots():
    """Overlaps, empty slots and more than 7 slots per day are rejected."""
    validate_slots([TimeSlot(0, 3600, 16, 3), TimeSlot(3600, 7200, 16, 3)])
    with pytest.raises(ChargingProfileError, match="conflicts"):
        validate_slots([TimeSlot(0, 3600, 16, 3), TimeSlot(1800, 7200, 16, 3)])
    with pytest.raises(ChargingProfileError, match="Invalid"):
        validate_slots([TimeSlot(7200, 3600, 16, 3)])
    with pytest.raises(ChargingProfileError, match="at most 7"):
        validate_slots([TimeSlot(i * 3600, i * 3600 + 60, 16, 3) for i in range(8)])


# ---------------------------------------------------------------------------
# Status and limiting factor
# ---------------------------------------------------------------------------


def test_limiting_factor_decoding():
    """Single flags and combined bitmasks are decoded and grouped."""
    assert charging.decode_limiting_factor(8) == [8]
    assert charging.limiting_group([8]) == "vehicle"
    assert charging.limiting_group(charging.decode_limiting_factor(32768)) == "load_balancing"
    assert charging.limiting_group(charging.decode_limiting_factor(128)) == "installation"
    assert charging.limiting_group(charging.decode_limiting_factor(1)) is None
    assert charging.decode_limiting_factor(1 | 64) == [1, 64]
    assert charging.decode_limiting_factor("x") == []


def test_main_state_table_complete():
    """Every socket main state from the app (-1..55) has a message."""
    assert set(charging.SOCKET_MAIN_STATE) == set(range(-1, 56))


# ---------------------------------------------------------------------------
# Session tracking and transaction parsing
# ---------------------------------------------------------------------------


@pytest.fixture(name="device")
def device_fixture():
    """Return an AlfenDevice with a mocked session."""
    return AlfenDevice(
        session=MagicMock(),
        host="192.168.1.100",
        name="Test",
        username="admin",
        password="secret",
        category_options=["generic", "states"],
        ssl=MagicMock(),
    )


def _set(device, **values):
    for prop_id, value in values.items():
        device.properties[prop_id] = {"id": prop_id, "value": value, "cat": "x"}


def test_session_tracking(device):
    """A session starts on connect, accumulates energy and ends on disconnect."""
    _set(device, **{"2501_1": 2, "2221_22": 1_000_000, "2221_16": 0})
    device._update_session()
    assert device.session["active"] is False

    _set(device, **{"2501_1": 14, "2221_22": 1_000_000, "2221_16": 7400})
    device._update_session()
    assert device.session["active"] is True

    _set(device, **{"2501_1": 14, "2221_22": 1_005_500, "2221_16": 11000})
    device._update_session()
    assert device.session["energy_kwh"] == 5.5
    assert device.session["max_power_w"] == 11000

    _set(device, **{"2501_1": 2})
    device._update_session()
    assert device.session["active"] is False
    assert device.session["energy_kwh"] == 5.5  # last session stays visible
    assert device.session_duration is not None


async def test_transactions_survive_status_notifications(device):
    """sn3 records between transactions no longer end the scan early."""
    status_page = (
        "10_sn3: socket 0, 2024-01-01 10:00:00 Faulted, UnderVoltage, Going down, 31,\n"
        "11_sn3: socket 0, 2024-01-01 10:01:00 AVAILABLE, NoError, , 31,\n"
        "12_sn3: socket 0, 2024-01-01 10:02:00 AVAILABLE, NoError, , 31,\n"
    )
    transaction_page = (
        "13_txstart2: id 0x0000000000000001, socket 1, 2024-01-01 11:00:00 100.5kWh AP;foo; ABC123 3 4 N\n"
        "14_txstop2: id 0x0000000000000001, socket 1, 2024-01-01 12:00:00 110.5kWh (null) ABC123 19\n"
    )
    responses = [status_page, transaction_page] + [""] * 10
    with patch.object(device, "_get", new=AsyncMock(side_effect=responses)):
        await device._get_transaction()

    assert len(device.transactions) == 1
    tx = device.transactions[0]
    assert tx["tag"] == "ABC123"
    assert tx["energy_kwh"] == 10.0


def test_schedule_day_request_round_trips_through_wallbox_format():
    """What we send parses back to the same slots as the app's stored profile."""
    request = charging.build_schedule_day_request(0, [TimeSlot(36000, 60300, 10.4, 1)], datetime.UTC)
    periods = request["csChargingProfiles"]["chargingSchedule"]["chargingSchedulePeriod"]
    stored = {
        "startPeriod": [p["startPeriod"] for p in periods],
        "limit": [p["limit"] for p in periods],
        "numberPhases": [p["numberPhases"] for p in periods],
    }
    # Exactly the layout Eve Connect left on a real wallbox
    assert stored == {
        "startPeriod": [0, 1, 36000, 60300],
        "limit": [0, 0, 10.4, 0],
        "numberPhases": [1, 1, 1, 1],
    }
    assert charging.profile_slots(stored) == [TimeSlot(36000, 60300, 10.4, 1)]


def _response(status, body=""):
    response = MagicMock()
    response.status = status
    response.text = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


async def test_profile_post_reports_rejection(device):
    """A 400 (after one retry) raises instead of silently returning None."""
    device.logged_in = True
    device._session.post = MagicMock(side_effect=[_response(400, "bad"), _response(400, "bad")])
    with (
        patch("custom_components.alfen_wallbox.alfen.asyncio.sleep", new=AsyncMock()),
        pytest.raises(ChargingProfileError, match="HTTP 400"),
    ):
        await device._profile_post("chargingprofiles?add", {"a": 1})


async def test_profile_post_relogs_in_after_401(device):
    """The wallbox drops the session after a burst of writes: re-login and retry."""
    device.logged_in = True
    device._session.post = MagicMock(side_effect=[_response(401), _response(200)])

    async def fake_login():
        device.logged_in = True

    with patch.object(device, "login", new=AsyncMock(side_effect=fake_login)) as mock_login:
        await device._profile_post("chargingprofiles?clear=1", None)
    mock_login.assert_called_once()
    assert device._session.post.call_count == 2


async def test_transactions_follow_large_dto_jump(device):
    """A jump past 500,000 (real wallboxes use ~1.5M) is followed, not capped."""
    pages = {
        0: "0_dto: 1480240\n",
        1480240: (
            "1480240_txstart2: id 0x0000000000000002, socket 1, 2026-11-01 10:00:00 200.0kWh ABC 3 4 N\n"
            "1480300_txstop2: id 0x0000000000000002, socket 1, 2026-11-01 12:00:00 207.5kWh ABC 19\n"
        ),
    }
    requested: list[int] = []

    async def fake_get(url, **kwargs):
        offset = int(url.rsplit("=", 1)[1])
        requested.append(offset)
        return pages.get(offset, "")

    with patch.object(device, "_get", new=AsyncMock(side_effect=fake_get)):
        await device._get_transaction()

    assert 1480240 in requested
    assert len(requested) < 10
    assert device.transactions[0]["energy_kwh"] == 7.5


async def test_transactions_stop_when_offset_does_not_advance(device):
    """A wallbox repeating the same jump no longer causes an endless request loop."""
    with patch.object(
        device, "_get", new=AsyncMock(return_value="0_dto: 999999999\n")
    ) as mock_get:
        await device._get_transaction()
    assert mock_get.call_count <= 3


async def test_load_transaction_history_runs_to_end_in_batches(device):
    """'Load history' keeps reading batch after batch and reports progress."""
    # 450 pages of one meter-value line each, then the end of the log
    def page(offset):
        if offset >= 450 * 10:
            return ""
        day = 1 + offset // 1000
        return f"{offset}_mv: socket 1, 2026-08-{day:02d} 10:00:00 1000.000 Y\n{offset + 10}_mv: socket 1, 2026-08-{day:02d} 10:05:00 1000.000 Y\n"

    async def fake_get(url, **kwargs):
        return page(int(url.rsplit("=", 1)[1]))

    states: list[tuple[bool, str | None]] = []
    device._state_changed_callback = lambda: states.append(
        (device.transactions_loading, device.transactions_loaded_until)
    )
    with patch.object(device, "_get", new=AsyncMock(side_effect=fake_get)) as mock_get:
        await device.async_load_transaction_history()

    assert mock_get.call_count > 200  # more than one batch: did not stop at the cap
    assert states[0][0] is True  # loading announced first
    assert states[-1] == (False, "2026-08-05 10:05:00")  # finished, progress date kept
    assert len(states) >= 4  # start + one update per batch + end


async def test_transactions_survive_restart(device):
    """Sessions and the log position are exported and restored (HA .storage)."""
    page = (
        "13_txstart2: id 0x0000000000000001, socket 1, 2024-01-01 11:00:00 100.5kWh ABC123 3 4 N\n"
        "14_txstop2: id 0x0000000000000001, socket 1, 2024-01-01 12:00:00 110.5kWh ABC123 19\n"
    )
    saved: list[dict] = []
    device._transactions_changed_callback = lambda: saved.append(device.export_transactions())
    with patch.object(device, "_get", new=AsyncMock(side_effect=[page, ""] + [""] * 5)):
        await device._get_transaction()
    assert saved, "change callback not called"
    data = saved[-1]
    assert data["sessions"][0]["energy_kwh"] == 10.0

    restarted = AlfenDevice(
        session=MagicMock(), host="h", name="n", username="admin", password="p",
        category_options=[], ssl=MagicMock(),
    )
    restarted.import_transactions(data)
    assert restarted.transactions == device.transactions
    assert restarted.transaction_offset == device.transaction_offset > 0
    restarted.import_transactions(None)  # empty storage is fine


def test_history_summary_periods():
    """This month / last month (incl. year change) / this year / total."""
    from custom_components.alfen_wallbox.sensor import history_summary

    sessions = [
        {"start_date": "2027-01-03 10:00:00", "energy_kwh": 5.0},
        {"start_date": "2026-12-30 22:00:00", "stop_date": "2027-01-01 01:00:00", "energy_kwh": 7.5},
        {"start_date": "2026-12-01 08:00:00", "energy_kwh": 2.5},
        {"start_date": "2026-11-02 07:00:00"},  # open session: counted, no energy yet
        {"start_date": "garbage", "energy_kwh": 99},
    ]
    today = datetime.date(2027, 1, 15)
    assert history_summary(sessions, "this_month", today) == (5.0, 1)
    assert history_summary(sessions, "last_month", today) == (10.0, 2)
    assert history_summary(sessions, "this_year", today) == (5.0, 1)
    assert history_summary(sessions, "total", today) == (15.0, 4)


def test_solar_grid_split_like_eve_connect():
    """Exporting -> all solar; importing -> the import is grid."""
    assert charging.solar_grid_split(7000, -2500) == (7000, 0)
    assert charging.solar_grid_split(7000, 3000) == (4000, 3000)
    assert charging.solar_grid_split(7000, 9000) == (0, 7000)
    assert charging.solar_grid_split(0, -2500) == (0, 0)
    assert charging.solar_grid_split(7000, None) == (0, 0)


def test_session_green_share_integrates_over_time(device):
    """Session green share = solar energy / total energy over the session."""
    _set(device, **{"2501_1": 14, "2221_22": 0, "2221_16": 4000, "5221_16": -1000})
    device._update_session()  # session starts
    t0 = device.session["last_ts"]
    # 30 min all-solar, then 30 min half grid
    device.session["last_ts"] = t0 - datetime.timedelta(seconds=100)
    device._update_session()  # 100 s @ 4000 W solar
    _set(device, **{"5221_16": 2000})
    device.session["last_ts"] -= datetime.timedelta(seconds=100)
    device._update_session()  # 100 s @ 2000 solar + 2000 grid
    assert round(device.session["solar_wh"]) == round((4000 + 2000) * 100 / 3600)
    assert round(device.session["grid_wh"]) == round(2000 * 100 / 3600)
    assert device.session_green_share == 75.0
    assert device.has_smart_meter_power



async def test_entity_unique_ids_are_unique():
    """No two entities of a platform may share a unique ID (HA drops the second)."""
    import importlib

    import homeassistant.helpers.entity_platform as ep

    device = MagicMock()
    device.id = "alfen_X"
    device.name = "X"
    device.properties = {}
    device.latest_tag = None
    device.charging_profiles = []
    device.get_number_of_sockets = MagicMock(return_value=2)
    device.get_licenses = MagicMock(return_value=[])
    entry = MagicMock()
    entry.runtime_data.device = device
    ep.current_platform.set(None)
    for name in ("binary_sensor", "button", "calendar", "number", "select", "sensor", "switch", "text", "time"):
        module = importlib.import_module(f"custom_components.alfen_wallbox.{name}")
        created: list = []
        await module.async_setup_entry(MagicMock(), entry, lambda ents, *_, sink=created: sink.extend(ents))
        ids = [entity.unique_id for entity in created]
        duplicates = sorted({uid for uid in ids if ids.count(uid) > 1})
        assert not duplicates, f"{name}: duplicate unique IDs {duplicates}"


async def test_history_fetch_has_its_own_budget(device):
    """A slow history fetch is cut off without failing the update, and retried next cycle."""
    import asyncio

    from custom_components.alfen_wallbox import alfen as alfen_module

    device.category_options = ["transactions"]

    async def slow_fetch(*args, **kwargs):
        await asyncio.sleep(10)
        return False

    with (
        patch.object(alfen_module, "HISTORY_FETCH_TIMEOUT", 0.05),
        patch.object(device, "_get_transaction", new=AsyncMock(side_effect=slow_fetch)),
        patch.object(device, "async_update_charging_profiles", new=AsyncMock()),
    ):
        await device._fetch_logs_and_transactions()  # first cycle fetches immediately
    assert device.history_fetch_retries == 1
    assert device.transaction_counter == -1  # retried on the next cycle
