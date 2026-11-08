"""CSV / JSON export of the saved charging history.

The "Export Charging History" button creates signed, time-limited download links
for an authenticated Home Assistant view, so the files (which contain RFID tags)
are never placed in the public ``www`` folder.
"""

from __future__ import annotations

import csv
import datetime
import io
import json
from typing import Any

from aiohttp import web
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import HomeAssistantView
from homeassistant.util import dt as dt_util

from .const import DOMAIN

EXPORT_URL = "/api/alfen_wallbox/{entry_id}/charging_sessions.{fmt}"
EXPORT_LINK_VALIDITY = datetime.timedelta(hours=1)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

CSV_COLUMNS = (
    "id",
    "socket",
    "start",
    "end",
    "duration_minutes",
    "energy_kwh",
    "start_meter_kwh",
    "stop_meter_kwh",
    "tag",
)


def session_rows(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise stored sessions into export rows (oldest first)."""
    rows = []
    for session in sessions:
        try:
            start = datetime.datetime.strptime(session.get("start_date") or "", _DATE_FORMAT)
            end = datetime.datetime.strptime(session.get("stop_date") or "", _DATE_FORMAT)
            duration = int((end - start).total_seconds() // 60)
        except ValueError:
            duration = None
        rows.append(
            {
                "id": session.get("id"),
                "socket": session.get("socket"),
                "start": session.get("start_date"),
                "end": session.get("stop_date"),
                "duration_minutes": duration,
                "energy_kwh": session.get("energy_kwh"),
                "start_meter_kwh": _number(session.get("start_kwh")),
                "stop_meter_kwh": _number(session.get("stop_kwh")),
                "tag": session.get("tag"),
            }
        )
    return sorted(rows, key=lambda row: row["start"] or row["end"] or "")


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_csv(sessions: list[dict[str, Any]]) -> str:
    """Return the sessions as CSV (header + one row per session)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for row in session_rows(sessions):
        writer.writerow({key: "" if value is None else value for key, value in row.items()})
    return buffer.getvalue()


def build_json(sessions: list[dict[str, Any]]) -> str:
    """Return the sessions as a JSON document."""
    rows = session_rows(sessions)
    return json.dumps(
        {
            "exported_at": dt_util.now().isoformat(),
            "sessions": len(rows),
            "total_energy_kwh": round(sum(row["energy_kwh"] or 0 for row in rows), 3),
            "charging_sessions": rows,
        },
        indent=2,
    )


class AlfenExportView(HomeAssistantView):
    """Authenticated download of the charging history."""

    url = "/api/alfen_wallbox/{entry_id}/charging_sessions.{fmt}"
    name = "api:alfen_wallbox:charging_sessions"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str, fmt: str) -> web.Response:
        """Return the CSV or JSON file."""
        hass: HomeAssistant = request.app["hass"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN or fmt not in ("csv", "json"):
            return web.Response(status=404)
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is None or coordinator.device is None:
            return web.Response(status=404)
        sessions = coordinator.device.export_transactions()["sessions"]
        body = build_csv(sessions) if fmt == "csv" else build_json(sessions)
        filename = f"alfen_charging_sessions_{dt_util.now():%Y%m%d}.{fmt}"
        return web.Response(
            body=body.encode(),
            content_type="text/csv" if fmt == "csv" else "application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


def async_create_export_links(hass: HomeAssistant, entry_id: str) -> dict[str, str]:
    """Return signed CSV / JSON download links valid for EXPORT_LINK_VALIDITY.

    When called from a button press in the UI, the links are signed for the
    user who pressed it.
    """
    expires = dt_util.now() + EXPORT_LINK_VALIDITY
    return {
        "csv": async_sign_path(
            hass, EXPORT_URL.format(entry_id=entry_id, fmt="csv"), EXPORT_LINK_VALIDITY
        ),
        "json": async_sign_path(
            hass, EXPORT_URL.format(entry_id=entry_id, fmt="json"), EXPORT_LINK_VALIDITY
        ),
        "expires": expires.isoformat(),
    }
