"""Tests for the CSV / JSON export of the charging history."""

from __future__ import annotations

import csv
import datetime
import io
import json
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alfen_wallbox.const import DOMAIN
from custom_components.alfen_wallbox.export import (
    AlfenExportView,
    async_create_export_links,
    build_csv,
    build_json,
)

SESSIONS = [
    {
        "id": "0x2", "socket": "socket 1", "start_date": "2026-11-01 01:02:27",
        "start_kwh": "2994.630", "tag": "0441BA124A1390",
        "stop_date": "2026-11-02 07:00:57", "stop_kwh": "2995.189", "energy_kwh": 0.559,
    },
    {
        "id": "0x1", "socket": "socket 1", "start_date": "2026-08-06 07:01:32",
        "start_kwh": "2658.073", "tag": "058C5DC4D97300",
        "stop_date": "2026-08-06 18:36:34", "stop_kwh": "2666.893", "energy_kwh": 8.82,
    },
    {"id": "0x3", "socket": "socket 1", "start_date": "2026-11-07 23:23:59", "start_kwh": "2995.2"},
]


def test_build_csv():
    """CSV has a header and one row per session, oldest first, open session blank."""
    rows = list(csv.DictReader(io.StringIO(build_csv(SESSIONS))))
    assert [r["id"] for r in rows] == ["0x1", "0x2", "0x3"]
    assert rows[0] == {
        "id": "0x1", "socket": "socket 1", "start": "2026-08-06 07:01:32",
        "end": "2026-08-06 18:36:34", "duration_minutes": "695", "energy_kwh": "8.82",
        "start_meter_kwh": "2658.073", "stop_meter_kwh": "2666.893", "tag": "058C5DC4D97300",
    }
    assert rows[2]["end"] == "" and rows[2]["energy_kwh"] == ""


def test_build_json():
    """JSON has totals and the sessions."""
    data = json.loads(build_json(SESSIONS))
    assert data["sessions"] == 3
    assert data["total_energy_kwh"] == 9.379
    assert data["charging_sessions"][1]["duration_minutes"] == 1798


async def test_signed_download(hass: HomeAssistant, hass_client_no_auth, freezer) -> None:
    """Signed links download without a login; unsigned or expired ones are refused."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.device.export_transactions.return_value = {"sessions": SESSIONS}
    entry.runtime_data = coordinator
    hass.http.register_view(AlfenExportView())
    client = await hass_client_no_auth()

    links = async_create_export_links(hass, entry.entry_id)

    response = await client.get(links["csv"])
    assert response.status == 200
    assert "attachment" in response.headers["Content-Disposition"]
    assert (await response.text()).startswith("id,socket,start,end")

    response = await client.get(links["json"])
    assert response.status == 200
    assert (await response.json())["sessions"] == 3

    unsigned = links["csv"].split("?")[0]
    assert (await client.get(unsigned)).status == 401

    freezer.tick(datetime.timedelta(hours=2))  # links are valid for 1 hour
    assert (await client.get(links["csv"])).status == 401


async def test_export_button_creates_notification(hass: HomeAssistant) -> None:
    """Pressing Export shows a native notification with both download links."""
    from homeassistant.components import persistent_notification

    from custom_components.alfen_wallbox.button import _export_history

    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.entry = entry
    coordinator.device.name = "Alfen"
    coordinator.device.transactions = SESSIONS

    await _export_history(coordinator)

    notifications = persistent_notification._async_get_or_create_notifications(hass)
    note = notifications[f"alfen_wallbox_export_{entry.entry_id}"]
    assert "3 charging sessions" in note["message"]
    assert "charging_sessions.csv?authSig=" in note["message"]
    assert "charging_sessions.json?authSig=" in note["message"]
    assert 'target="_blank"' in note["message"]
    assert coordinator.export_links["csv"] in note["message"]
