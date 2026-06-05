"""Live integration tests against a real Alfen wallbox.

These tests require a running wallbox on the local network.
Credentials are loaded from a .env file in the project root:

    ALFEN_HOST=192.168.x.x
    ALFEN_NAME=My Wallbox
    ALFEN_USERNAME=admin
    ALFEN_PASSWORD=secret

Run with:
    pytest tests/live/ -v -s

Skipped automatically when .env is missing or ALFEN_HOST is not set,
or when the wallbox is unreachable.
Never run in CI (no hardware available).
"""

from __future__ import annotations

from pathlib import Path
from ssl import CERT_NONE

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Load .env (no external dependency — manual parser)
# ---------------------------------------------------------------------------

_ENV_PATH = Path(__file__).parent.parent / ".env"


def _load_env(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file, ignoring comments and blank lines."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


_ENV = _load_env(_ENV_PATH)

_SKIP = pytest.mark.skipif(
    not _ENV.get("ALFEN_HOST"),
    reason=".env not found or ALFEN_HOST not set — skipping live tests",
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def live_device():
    """Connect to the real wallbox and yield a logged-in AlfenDevice.

    Logs out and closes the session after each test.
    """
    import ssl

    from aiohttp import ClientSession, TCPConnector

    from custom_components.alfen_wallbox.alfen import AlfenDevice
    from custom_components.alfen_wallbox.const import DEFAULT_REFRESH_CATEGORIES

    host = _ENV["ALFEN_HOST"]
    name = _ENV.get("ALFEN_NAME", "Live Wallbox")
    username = _ENV.get("ALFEN_USERNAME", "admin")
    password = _ENV.get("ALFEN_PASSWORD", "admin")

    context = ssl.create_default_context()
    context.set_ciphers("DEFAULT")
    context.check_hostname = False
    context.verify_mode = CERT_NONE

    session = ClientSession(
        connector=TCPConnector(
            limit=1,
            limit_per_host=1,
            keepalive_timeout=300,
        )
    )

    device = AlfenDevice(
        session=session,
        host=host,
        name=name,
        username=username,
        password=password,
        category_options=list(DEFAULT_REFRESH_CATEGORIES),
        ssl=context,
    )

    try:
        result = await device.init()
    except Exception as exc:
        await session.close()
        pytest.skip(f"Cannot reach wallbox at {host}: {exc}")

    if not result:
        await session.close()
        pytest.skip(f"Cannot reach wallbox at {host} (init returned False)")

    try:
        await device.login()
    except Exception as exc:
        await session.close()
        pytest.skip(f"Login failed for {host}: {exc}")

    yield device

    await device.logout()
    await session.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@_SKIP
async def test_live_device_info(live_device):
    """Device info is populated after init."""
    assert live_device.info is not None
    assert live_device.info.identity != ""
    print(f"\nIdentity  : {live_device.info.identity}")
    print(f"Model     : {live_device.info.model}")
    print(f"Firmware  : {live_device.info.firmware_version}")


@_SKIP
async def test_live_login(live_device):
    """Device is authenticated after fixture setup."""
    assert live_device.logged_in is True


@_SKIP
async def test_live_get_all_raw_profiles(live_device):
    """Probe charging profile endpoints to discover what's stored on the wallbox."""
    import json

    candidates = {
        "no filter":            "",
        "schedule (-19930828)": "?cpid=-19930828",
        "boost (-19930829)":    "?cpid=-19930829",
        "pause (-19930830)":    "?cpid=-19930830",
        "all":                  "?all",
        "cpid=0":               "?cpid=0",
        "cpid=1":               "?cpid=1",
        "cpid=2":               "?cpid=2",
        "cpid=3":               "?cpid=3",
        "cpid=100":             "?cpid=100",
        "cpid=-1":              "?cpid=-1",
        "cpid=-2":              "?cpid=-2",
        "cpid=-19930831":       "?cpid=-19930831",
        "cpid=-19930827":       "?cpid=-19930827",
        "cpid=-19930826":       "?cpid=-19930826",
        "limit=-19930828":      "?limit=-19930828",
        "offset=0":             "?offset=0",
        "stacklevel=0":         "?stacklevel=0",
        "stacklevel=1":         "?stacklevel=1",
    }

    for label, query in candidates.items():
        url = f"https://{live_device.host}/api/chargingprofiles{query}"
        try:
            response = await live_device._get(url=url)
        except Exception as exc:
            print(f"\n--- {label} → ERROR: {exc}")
            continue
        if response:
            print(f"\n--- {label} ---")
            print(json.dumps(response, indent=2, default=str))
        else:
            print(f"\n--- {label} → (empty)")


@_SKIP
async def test_live_get_charging_profiles(live_device):
    """get_charging_profiles returns a list (possibly empty) and prints the schedule."""
    import json

    profiles = await live_device.get_charging_profiles()

    assert isinstance(profiles, list)
    print(f"\nCharging profiles ({len(profiles)} found):")

    for i, profile in enumerate(profiles):
        print(f"\n  Profile {i + 1} (raw):")
        print(f"  {json.dumps(profile, indent=4)}")

        from custom_components.alfen_wallbox.calendar import (
            _normalize_periods,
            _seconds_to_time,
        )

        periods = _normalize_periods(profile)
        recurrency = profile.get("recurrencyKind", "DAILY")
        days = profile.get("daysOfWeek", [])
        start_schedule = profile.get("startSchedule", "")

        if periods:
            print(f"\n  Profile {i + 1} (parsed):")
            print(f"    ID          : {profile.get('chargingProfileId')}")
            print(f"    Recurrency  : {recurrency}")
            if start_schedule:
                import datetime
                anchor = datetime.datetime.fromisoformat(start_schedule.replace("Z", "+00:00"))
                print(f"    Weekday     : {anchor.strftime('%A')}")
            if days:
                print(f"    Days        : {', '.join(days)}")

            for sp, limit, num_phases in periods:
                t = _seconds_to_time(sp).strftime("%H:%M")
                if limit > 0:
                    kw = round(limit * num_phases * 230 / 1000, 1)
                    action = f"{limit}A × {num_phases} phase(s) = {kw} kW"
                else:
                    action = "off"
                print(f"    {t}  →  {action}")


@_SKIP
async def test_live_get_insights(live_device):
    """Fetch all transaction (Insights) data from the wallbox and display it."""
    from urllib.parse import urlencode

    # --- 1. Print raw pages (follow dto jump like _get_transaction does) -----
    print("\n--- Raw transaction pages ---")
    offset = 0
    page = 0
    while True:
        query = urlencode({"offset": offset})
        raw = await live_device._get(
            url=f"https://{live_device.host}/api/transactions?{query}",
            json_decode=False,
        )
        if not raw:
            print(f"  page {page} (offset={offset}): (empty — end of data)")
            break
        lines = str(raw).splitlines()
        print(f"\n  page {page} (offset={offset}, {len(lines)} lines):")
        for line in lines:
            print(f"    {line!r}")

        # Follow the dto jump so we land on actual transaction records
        jumped = False
        for line in lines:
            stripped = line
            if "version" in stripped and ":2," in stripped:
                stripped = stripped.split(":2,", 1)[1]
            if "_dto" in stripped:
                try:
                    dto_offset = int(stripped.split("_dto")[0].split(",")[-1].strip())
                    if dto_offset > offset:
                        offset = dto_offset
                        jumped = True
                        break
                except (ValueError, IndexError):
                    pass

        if not jumped:
            # Advance by the last record offset seen on this page
            last_offset = offset
            for line in lines:
                stripped = line
                if "version" in stripped and ":2," in stripped:
                    stripped = stripped.split(":2,", 1)[1]
                parts = stripped.split("_", 1)
                try:
                    last_offset = max(last_offset, int(parts[0].split(",")[-1].strip()))
                except (ValueError, IndexError):
                    pass
            if last_offset == offset:
                break
            offset = last_offset

        page += 1
        if page > 20:
            print("  (stopped after 20 pages)")
            break

    # --- 2. Full history scan (offset=0, no dto jump) -----------------------
    # _get_transaction() now correctly jumps via the dto offset to the latest
    # records.  To collect the full history we scan manually from offset=0.
    print("\n--- Full history scan (all txstart2 / txstop2 records) ---")
    history: dict = {}  # hex_tx_id -> record dict
    scan_offset = 0
    scan_pages = 0
    max_scan_pages = 2000
    while scan_pages < max_scan_pages:
        query = urlencode({"offset": scan_offset})
        raw = await live_device._get(
            url=f"https://{live_device.host}/api/transactions?{query}",
            json_decode=False,
        )
        if not raw:
            break
        lines = str(raw).splitlines()
        last_offset = scan_offset
        found_new = False
        for line in lines:
            if "version" in line and ":2," in line:
                line = line.split(":2,", 1)[1]
            parts = line.split(" ")
            prefix = parts[0].split("_", 1)
            try:
                rec_offset = int(prefix[0].split(",")[-1])
            except (ValueError, IndexError):
                continue
            if rec_offset > last_offset:
                last_offset = rec_offset
            line_type = prefix[1] if len(prefix) > 1 else ""
            if "txstart" in line_type or "txstop" in line_type:
                found_new = True
                if len(parts) < 9:
                    continue
                hex_tx_id = parts[2].rstrip(",")
                socket = parts[3] + " " + parts[4].split(",")[0]
                date = parts[5] + " " + parts[6]
                kwh = parts[7].split("kWh")[0]
                tag = parts[8]
                rec = history.setdefault(hex_tx_id, {"id": hex_tx_id, "socket": socket, "tag": tag})
                if "txstart" in line_type:
                    rec["start_date"] = date
                    rec["start_kwh"] = kwh
                else:
                    rec["stop_date"] = date
                    rec["stop_kwh"] = kwh
                    try:
                        rec["energy_kwh"] = round(float(kwh) - float(rec.get("start_kwh", kwh)), 3)
                    except (ValueError, TypeError):
                        pass
        if last_offset <= scan_offset:
            break
        scan_offset = last_offset
        scan_pages += 1

    sessions = sorted(history.values(), key=lambda r: r.get("start_date", ""), reverse=True)
    print(f"  Sessions found: {len(sessions)}  (scanned {scan_pages} pages)")
    for s in sessions:
        start = s.get("start_date", "?")
        stop = s.get("stop_date", "in progress")
        energy = f"{s.get('energy_kwh', '?')} kWh" if s.get("stop_date") else "ongoing"
        print(f"  {start} → {stop}  {energy}  tag={s.get('tag')}  socket={s.get('socket')}")

    # --- 3. Fast latest-only fetch via _get_transaction() (uses dto jump) ---
    print("\n--- Latest transactions via _get_transaction() (fast, dto jump) ---")
    live_device.transaction_offset = 0
    live_device._transaction_map.clear()
    live_device.transactions = []
    await live_device._get_transaction()

    if not live_device.latest_tag:
        print("  latest_tag is empty")
    else:
        for key, value in sorted(live_device.latest_tag.items(), key=lambda x: str(x[0])):
            print(f"  {key}: {value!r}")

    # --- 4. Structured transaction list (from _get_transaction map) ---------
    print("\n--- Structured transactions list (from _transaction_map) ---")
    transactions = live_device.transactions
    print(f"  Transactions in map: {len(transactions)}")
    for tx in transactions:
        parts = [
            f"id={tx.get('id')}",
            f"socket={tx.get('socket')}",
            f"start={tx.get('start_date')}",
            f"start_kwh={tx.get('start_kwh')} kWh",
        ]
        if tx.get("stop_date"):
            parts += [
                f"stop={tx.get('stop_date')}",
                f"stop_kwh={tx.get('stop_kwh')} kWh",
                f"energy={tx.get('energy_kwh')} kWh",
            ]
        parts.append(f"tag={tx.get('tag')}")
        print(f"  {' | '.join(parts)}")

    assert isinstance(live_device.transactions, list)


@_SKIP
async def test_live_get_logs(live_device):
    """Fetch raw log pages and display all events, then print parsed RFID tag info."""
    await live_device._get_log()

    logs = list(live_device.latest_logs)
    print(f"\nLog lines fetched: {len(logs)}")

    if not logs:
        print("  (no log lines returned)")
    else:
        print("\n--- Raw log lines ---")
        for line in logs:
            print(f"  {line}")

        print("\n--- Parsed events (socket / tag / connect·disconnect) ---")
        for line in logs:
            underscore_pos = line.find("_")
            if underscore_pos == -1 or underscore_pos >= 20:
                continue
            try:
                line_id = int(line[:underscore_pos])
            except ValueError:
                continue
            parts = line[underscore_pos + 1 :].split(":")
            if len(parts) < 7:
                continue
            message = ":".join(parts[6:])

            from custom_components.alfen_wallbox.alfen import SOCKET_PATTERN, TAG_PATTERN

            socket_match = SOCKET_PATTERN.search(message)
            socket = socket_match.group(1) if socket_match else "?"
            tag_match = TAG_PATTERN.search(message)
            tag = tag_match.group(1) if tag_match else None

            is_connect = any(
                e in message
                for e in ("EV_CONNECTED_AUTHORIZED", "CHARGING_POWER_ON", "CABLE_CONNECTED")
            )
            is_disconnect = any(
                e in message for e in ("CHARGING_POWER_OFF", "CHARGING_TERMINATING")
            )

            if is_connect or is_disconnect or tag:
                kind = "CONNECT" if is_connect else ("DISCONNECT" if is_disconnect else "OTHER")
                tag_str = f"  tag={tag}" if tag else ""
                print(f"  [{line_id:>8}] socket={socket}  {kind}{tag_str}")

    if live_device.latest_tag:
        print("\n--- latest_tag dict (RFID state) ---")
        for key, value in live_device.latest_tag.items():
            print(f"  {key}: {value}")

    assert isinstance(logs, list)


@_SKIP
async def test_live_charging_schedule_timeslots(live_device):
    """Profiles that contain a chargingSchedule have valid period structure."""
    profiles = await live_device.get_charging_profiles()

    assert isinstance(profiles, list)

    for profile in profiles:
        schedule = profile.get("chargingSchedule")
        if schedule is None:
            # System/default profiles may not carry a schedule — just skip them
            continue

        assert "chargingSchedulePeriod" in schedule
        periods = schedule["chargingSchedulePeriod"]
        assert isinstance(periods, list)
        assert len(periods) >= 1

        for period in periods:
            assert "startPeriod" in period
            assert "limit" in period
            assert period["startPeriod"] >= 0
            assert period["limit"] >= 0
