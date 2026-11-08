
# Alfen Wallbox - HomeAssistant Integration

This is a custom component to allow control of Alfen Wallboxes in [HomeAssistant](https://home-assistant.io).

The component is a fork of the [Garo Wallbox custom integration](https://github.com/sockless-coding/garo_wallbox) and [egnerfl custom integration](https://github.com/egnerfl/alfen_wallbox)

## Recent Improvements

### Eve Connect feature parity & dashboard (November 2026, v3.6.0)

Home Assistant now uses the *same* charging profiles as the official
**Eve Connect** app, so pausing, boosting, the maximum power and the weekly schedule are
shared: change it in one, see it in the other.

- 🏠 **Charge Control** — `Charging` / `Paused` / `Boost` (3 h at full power), like the app's home screen
- 🔋 **Session** — energy, duration and peak power of the current session
- 🚦 **Charging Status** with the app's messages, plus **Charging Restricted** / **Charging Limited By** (load balancing, vehicle, installation)
- ⚡ **Maximum Charging Power** (kW) — the app's Power-tab slider
- 📅 **Weekly schedule** — up to 7 time slots per day, "apply schedule" switch, and a time-slot editor usable from any dashboard
- 📊 **Ready-made dashboard** with Home, Power, Schedule, Insights and Settings tabs — see [Eve Connect dashboard](#eve-connect-dashboard)

### Charging Schedule Calendar & Insights (June 2026)

**New entities for schedule visibility and session history:**
- 📅 **Charging Schedule Calendar** — shows all active charging windows as calendar events, with correct local timezone support
- 📊 **Insights sensor** — tracks all charging sessions (start/stop times, energy delivered, RFID tag)
- 🔄 **Refresh Charging Schedule button** — force-fetch the latest schedule immediately after changing it in Eve Connect
- ⏱️ **Faster schedule refresh** — schedule profiles now auto-refresh every ~5 minutes (down from ~20 minutes)

### Wallbox Crash Prevention (January 2026)

**Configurable category fetching to prevent wallbox crashes:**
- 🛡️ **Prevents watchdog resets** - Configurable settings to eliminate memory/CPU spikes that cause wallbox crashes
- ⚡ **Configurable API load** - Adjust categories per cycle (1-15) and fetch delay (0-5s) if needed
- 🔄 **Smart rotation** - When reduced, categories rotate across multiple cycles
- ⚡ **Fast update cycles** - Default 20s interval with all categories fetched per cycle
- ✨ **User commands unaffected** - Value updates and commands processed immediately
- 📊 **Tunable settings** - Adjust via integration options if you experience instability

**Benefits:** By default, all categories are fetched every cycle for maximum responsiveness. If you experience wallbox instability, you can reduce categories per cycle or add fetch delays via integration options.

### Responsiveness Improvements (January 2026)

**Better responsiveness and reduced API load:**
- ⚡ **Forced refresh after value updates** - Changes now apply immediately instead of waiting for next cycle
- ⚡ **Optimized default scan interval** - Default 20s for responsive updates (configurable 1-300s)
- ⚡ **Smarter update scheduling** - Automatic immediate refresh when users change settings
- 🔧 Users can configure different intervals via integration options if needed

**Benefits:** User changes (like current limit adjustments) are now visible immediately. Lower API traffic means better stability and less interference with the wallbox's single-session limitation.

### Performance Optimizations (January 2026)

**Major performance and efficiency improvements:**
- ⚡ Eliminated 60-second blocking on timeout - faster recovery from network issues
- ⚡ Optimized property updates with dictionary comprehensions
- ⚡ Improved log parsing using regex patterns (faster, less CPU)
- ⚡ Limited log memory usage to prevent unbounded growth (deque with maxlen=500)
- ⚡ Better error handling with timing metrics and detailed logging
- ⚡ Reduced retry backoff from 5s to 2s for faster recovery

**Benefits:** Lower memory usage, faster updates, better resilience, improved observability. See [CHANGELOG.md](CHANGELOG.md) for details.

### Reliability Fixes (January 2026)

**10 critical bug fixes for reliability:**
- ✅ Fixed race conditions causing silent failures when setting values
- ✅ Eliminated deadlocks from improper lock handling
- ✅ Fixed bitwise OR bugs in validation logic (current limit, green share, comfort power)
- ✅ Added automatic retry for failed updates
- ✅ Improved error logging and visibility

Previously, users experienced "silent failures" when changing settings (e.g., max current) - values wouldn't update and required manual retry. This has been resolved.

> After reverse engineering the API myself I found out that there is already a Python libary wrapping the Alfen API.
> https://gitlab.com/LordGaav/alfen-eve/-/tree/develop/alfeneve
> 
> https://github.com/leeyuentuen/alfen_wallbox/wiki/API-paramID

## Installation

### Install using HACS (recommended)
If you do not have HACS installed yet visit https://hacs.xyz for installation instructions.

To add the this repository to HACS in your Home Assistant instance, use this My button:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?repository=alfen_wallbox&owner=leeyuentuen&category=Integration)

After installation, please reboot. Home Assistant usually **discovers the wallbox on
your network automatically** (Zeroconf) and shows it under *Settings → Devices &
services → Discovered*; otherwise add the Alfen Wallbox device with this My button:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=alfen_wallbox)

<details>
<summary><b><svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 24 24"><path fill="currentColor" d="m13.75 10.19l.63.13l4.17 2.08c.7.23 1.16.92 1.1 1.66v.26l-.9 6.12c-.06.43-.25.83-.6 1.11c-.31.3-.72.45-1.15.45h-6.88c-.49 0-.94-.18-1.27-.53L2.86 15.5l.9-1c.24-.25.62-.39.98-.37h.29L9 15V4.5a2 2 0 0 1 2-2a2 2 0 0 1 2 2v5.69z"></path></svg> Manual configuration steps</b></summary>

> - In HACS, go to the Integrations section and add the custom repository via the 3 dot menu on the top right. Enter ```https://github.com/>> leeyuentuen/alfen_wallbox``` in the Repository field, choose the ```Integration``` category, then click add.
Hit the big + at the bottom right and search for **Alfen Wallbox**. Click it, then click the download button.
> - Clone or copy this repository and copy the folder 'custom_components/alfen_wallbox' into '<homeassistant config>/custom_components/alfen_wallbox'
> - Once installed the Alfen Wallbox integration can be configured via the Home Assistant integration interface
where you can enter the IP address of the device.
</details>

### Home Assistant Energy Dashboard
The wallbox can be added to the Home Assistant Energy Dashboard using the `_meter_reading` sensor.

## Settings
The wallbox can be configured using the Integrations settings menu:

<img src="doc/screenshots/configure.png" alt="drawing" style="width:600px;"/>

### Configuration Options

- **Scan Interval** (1-300s, default: 20s) - How often to update data from the wallbox
- **Timeout** (1-30s, default: 30s) - Request timeout for API calls
- **Categories per Cycle** (1-15, default: 15) - Number of property categories to fetch per update cycle
- **Category Fetch Delay** (0-5s, default: 0s) - Delay between fetching categories to reduce wallbox load
- **Refresh Categories** - Select which property categories to fetch regularly (others load once at startup)

**Configurable Category Fetching:** By default, all categories are fetched every cycle for maximum responsiveness. If you experience wallbox instability (crashes, watchdog resets), you can reduce the categories per cycle and/or add a fetch delay via integration options. When categories per cycle is reduced below the total enabled categories, the integration rotates through them across multiple cycles.

Categories that are not selected will only load when the integration starts. The exception to this rule is the `transactions` category, which will load only if explicitly selected.

To locate a category, start by selecting all categories. Allow the integration to load, then find the desired entity. The category will be displayed in the entity's attributes.

<img src="doc/screenshots/attribute category.png" alt="drawing" style="width:400px;"/>

**Note:** If you reduce the categories per cycle below the total enabled categories, reducing the number of selected categories will enhance update frequency (fewer categories means faster rotation). The scan interval, categories per cycle, and fetch delay can all be adjusted via integration options to find the best balance for your wallbox.

### Which entities belong to which category

The wallbox decides which property is in which category. This list was taken from an Eve Single Pro-line with firmware 7.4.6; on other models or firmware a property can be in a different category.

| Category | Entities |
|---|---|
| `generic` | Active Load Balancing, Auth. Connection Timeout (s), Auth. Local List, Auth. Mode, Auth. Plug & Charge ID, Auth. Re-authorize after Power Outage (s), Auth. Restart after Power Outage, Auth. Whitelist, Backoffice Short Name, Boot Reason, Car Disconnect Action, Car Disconnection Timeout (s), Car Time to Report Not Charging (s), Car Time to Unlock Not Charging (s), Charge Point Vendor, Customer Ident. number, Display & LED Brightness, Display Language, Display Light Auto Dim, Ethernet MAC address, Firmware Version, GPRS DNS 1, GPRS DNS 2, GPRS Gateway Address, GPRS IP Address, GPRS Netmask, GPRS Network Mode, GPRS Provider, GPRS SIM IMSI, GPRS SIM Serial, GPRS Signal, GPRS Technology, Heartbeat interval (s), Load Balancing Max. Meter Current, Load Balancing Phase Connection, Load Balancing Received Measurements, Load Balancing Safe Current, Main Active LB Max Current Socket 1, Main Active LB Max Current Socket 2, Main Active Max Current Socket 1, Main Active Max Current Socket 2, Main External Max Current Socket 1, Main External Max Current Socket 2, Main External Min Current Socket 1, Main External Min Current Socket 2, Main Static LB Max Current Socket 1, Main Static LB Max Current Socket 2, Main Station Active Max Current Socket 1, Manufacturer Hardware Version, Manufacturer Software Version, Minimum Chameleon Current, Mobile Weak Signal Threshold, Model, Number of Sockets, Number of bootups, Object Number, Platform Type, Power Connector External Max Current Socket 1, Power Connector Max Current Socket 1, Power Connector Max Current Socket 2, Protocol Version, Socket 1 Operation Mode, Socket 1.2 Max Current, Socket 2.2 Max Current, Socket Type Socket 1, Socket Type Socket 2, Station maximum Current, System Datetime, System Daylight Savings, System Uptime, Timezone, WiFi DNS 1, WiFi DNS 2, WiFi Gateway Address, WiFi IP Address, WiFi Netmask, Wired DNS 1, Wired DNS 2, Wired Gateway Address, Wired IP Address, Wired Netmask |
| `generic2` | Bootloader Version, CPO Name, Display Error Number Socket 1, Display Error Number Socket 2, Display State Socket 1, Display State Socket 2, Installation Direct External Suspend Signal, Installation Max. Allowed Phases, Installation Max. Imbalance Current between phases, Last Modify Config datetime, Load Balancing Charging profiles random delay, Load Balancing Enable Phase Switching, P1 Meter Phase 1 Current, P1 Meter Phase 2 Current, P1 Meter Phase 3 Current, Proxy Address And Port, Proxy Enabled, Proxy Username, Solar Charging Boost Socket 1, Solar Charging Boost Socket 2, Solar Charging Mode, Solar Comfort Level, Solar Green Share, WiFi Enabled |
| `states` | Car CP Voltage High Socket 1, Car CP Voltage High Socket 2, Car CP Voltage Low Socket 1, Car CP Voltage Low Socket 2, Car PP resistance Socket 1, Car PP resistance Socket 2, Car PWM Duty Cycle Socket 1, Car PWM Duty Cycle Socket 2, Connector 1 Max Allowed of Phases, Connector 2 Max Allowed of Phases, Main State Socket 1, Main State Socket 2, Modbus TCP/IP Connection State, Mode3 State Socket 1, Mode3 State Socket 2, OCPP Boot Accept Time, OCPP Boot Last Time Send, OCPP Boot notification State, OCPP Heartbeat Last Failed, OCPP Heartbeat Last Sent, Power State Socket 1, Power State Socket 2, Status Code Socket 1, Status Code Socket 2 |
| `meter1` | Active Power Total Socket 1, Current L1 Socket 1, Current L2 Socket 1, Current L3 Socket 1, Current N Socket 1, Frequency Socket 1, Meter Reading Socket 1, Voltage L1N Socket 1, Voltage L2N Socket 1, Voltage L3N Socket 1 |
| `meter2` | Active Power Total Socket 2, Current L1 Socket 2, Current L2 Socket 2, Current L3 Socket 2, Current N Socket 2, Current total Socket 2, Frequency Socket 2, Meter Reading Socket 2, Smart Meter Real Power L1, Smart Meter Real Power L2, Smart Meter Real Power L3, Smart Meter Real Power Sum, Voltage L1N Socket 2, Voltage L2N Socket 2, Voltage L3N Socket 2 |
| `meter4` | Load Balancing DSMR/SMR Interface, Load Balancing Protocol, Smart Meter Active Power Total, Smart Meter Current L1, Smart Meter Current L2, Smart Meter Current L3, Smart Meter Current total, Smart Meter Voltage L1N, Smart Meter Voltage L2N, Smart Meter Voltage L3N |
| `temp` | Alarm Temperature High, Alarm Temperature low, Max Temperature, Minimum Temperature, Temperature |
| `comm` | Auth. Remote Transaction requests, OCPP Mobile OCPP reply timeout (s), OCPP Mobile OCPP send timeout (s), OCPP Wired OCPP reply timeout (s), OCPP Wired OCPP send timeout (s), WiFi AP Enabled, WiFi AP Start on Boot, WiFi Password, WiFi RSSI, WiFi SSID, WiFi Security, WiFi Status |
| `display` | Price Start Tariff, Price other, Price other description, Price per kWh, Price per minute |
| `ocpp` | Backoffice Network 1 Connection Priority (Ethernet), Backoffice Network 2 Connection Priority (GPRS) |
| `MbusTCP` | Load Balancing Data Source |
| `logs` | Tag Socket 1, Tag Socket 2 (see [Tag and Transaction Sensors](#tag-and-transaction-sensors)) |
| `transactions` | Transaction Socket 1/2 Charging, Charging Time, Last Charge, Last Charge Time, Transaction Socket 2 Stop |

Smart Meter Power L1, L2, L3 and Total are calculated from the voltage (`meter4`) and the current (`generic2`), so they need both categories.

## Simultaneous Use of the App and Integration
The Alfen charger allows only one active login session at a time. This means the Alfen MyEve or Eve Connect app cannot be used concurrently with the Home Assistant integration.

To manage this, the integration includes two buttons: HTTPS API Login and HTTPS API Logout.

- To switch to the Alfen app: Click the Logout button in the Home Assistant integration, then use your preferred Alfen app.
- To return to the integration: Click the Login button to reconnect the Home Assistant integration.

The HTTPS API Login Status binary sensor shows the current state of the login session.

## Tag and Transaction Sensors
The tag and transaction sensors (`sensor.<device>_tag_socket_1` and the
`sensor.<device>_transaction_socket_1_*` sensors) are built from the `logs` and
`transactions` categories of the wallbox. Those categories are **not refreshed by
default**, to limit the load on the wallbox API, so those sensors keep reporting
`No Tag` and `unknown` until they are selected.

To enable them, open the integration options (Configure) and add `logs` and
`transactions` to the refresh categories. They are then read in the first update
cycle after a restart and afterwards every ~7 (logs) and ~20 (transactions) minutes,
with their own time budget so a slow wallbox cannot time out the update. You can
also press **Load history** (the *Force Fetch Transaction* button) to read the full
charging history once; it is saved and survives restarts. The integration logs a
warning on setup while those categories are missing.

## Services
Example of running in Services:
Note; The name of the configured charging point is "wallbox" in these examples.

### - Changing Green Share %
```
service: alfen_wallbox.set_green_share
data:
  entity_id: number.wallbox_solar_green_share
  value: 80
```

### - Changing Comfort Charging Power in Watt
```
service: alfen_wallbox.set_comfort_power
data:
  entity_id: number.wallbox_solar_comfort_level
  value: 1400
```

### - Enable phase switching
```
service: alfen_wallbox.enable_phase_switching
data:
  entity_id: switch.wallbox_enable_phase_switching
```


### - Disable phase switching
```
service: alfen_wallbox.disable_phase_switching
data:
  entity_id: switch.wallbox_enable_phase_switching
```

### - Enable RFID Authorization Mode
```
service: alfen_wallbox.enable_rfid_authorization_mode
data:
  entity_id: select.wallbox_authorization_mode
```

### - Disable RFID Authorization Mode
```
service: alfen_wallbox.disable_rfid_authorization_mode
data:
  entity_id: select.wallbox_authorization_mode
```

### - Reboot wallbox
```
service: alfen_wallbox.reboot_wallbox
data:
  entity_id: alfen_wallbox.garage
```

### - Add a charging time slot

Adds a time slot to the weekly schedule, in the same format as the Eve Connect app.
Existing slots are kept, overlapping slots are rejected (max. 7 per day), and a stop
time at or before the start time continues into the next day. Use `max_power` (kW,
like the app) or `max_current` (A); without either the station maximum is used.
Replace `sensor.wallbox_status_code_socket_1` with an entity of your wallbox.

```yaml
# Every day 09:00-17:00 at 16 A
service: alfen_wallbox.add_charging_profile
data:
  entity_id: sensor.wallbox_status_code_socket_1
  start_time: "09:00"
  stop_time: "17:00"
  max_current: 16
  recurrency: DAILY
```

```yaml
# Weeknights 22:00-06:00 at 7.4 kW (each night is split into 22-24 and 00-06)
service: alfen_wallbox.add_charging_profile
data:
  entity_id: sensor.wallbox_status_code_socket_1
  start_time: "22:00"
  stop_time: "06:00"
  max_power: 7.4
  recurrency: WEEKLY
  days: [Monday, Tuesday, Wednesday, Thursday, Friday]
```

### - Replace the time slots of one day

```yaml
service: alfen_wallbox.set_schedule_day
data:
  entity_id: sensor.wallbox_status_code_socket_1
  day: Saturday
  timeslots:
    - {start: "00:00", end: "07:00", max_power: 11}
    - {start: "12:00", end: "15:00", max_current: 10}
```

An empty `timeslots` list clears the day.

### - Clear the schedule

```yaml
# Only the weekend; omit `days` to clear the whole schedule
service: alfen_wallbox.clear_charging_schedule
data:
  entity_id: sensor.wallbox_status_code_socket_1
  days: [Saturday, Sunday]
```

The schedule only *restricts* charging to its time slots while the
**Charging Schedule** switch (the app's "Apply schedule") is on.

### - Set the maximum charging power

```yaml
service: alfen_wallbox.set_max_power
data:
  entity_id: sensor.wallbox_status_code_socket_1
  power: 7.4  # kW
```

### - Clear all charging profiles

Removes **everything**: schedule, maximum power, boost and pause.

```yaml
service: alfen_wallbox.clear_charging_profiles
data:
  entity_id: sensor.wallbox_status_code_socket_1
```

## Charging Schedule Calendar

The integration creates a **Charging Schedule** calendar entity (`calendar.wallbox_charging_schedule`) that shows your configured charging windows as calendar events. Each event displays the charging power in kW and the current/phase details.

The calendar is **editable** with Home Assistant's own calendar dialog (Calendar page in the sidebar, or tap an event on a calendar card):

- **Add**: pick the Charging Schedule calendar, set a start and end time and put the power in the title, e.g. `7.4 kW` or `16 A` (no power = station maximum). *Repeat daily* or *repeat weekly on …* chooses the days; without a repeat the slot applies every week on that weekday, because the wallbox schedule is weekly.
- **Edit / delete**: identical slots on several days form one repeating series. *This event* changes only that weekday; *this and following events* changes every day of the series.
- Slots past midnight are split over two days, up to 7 slots per day, overlaps are rejected, and all-day or monthly events are not supported.

The calendar refreshes automatically every ~5 minutes. After changing a schedule in Eve Connect, you can also press the **Refresh Charging Schedule** button to fetch the latest schedule immediately without waiting.

### Weekly calendar card

Add this to your Lovelace dashboard to see the full week at a glance:

```yaml
type: calendar
entities:
  - calendar.wallbox_charging_schedule
initial_view: dayGridWeek
title: Charging Schedule
```

For a day-by-day view instead:

```yaml
type: calendar
entities:
  - calendar.wallbox_charging_schedule
initial_view: dayGridDay
title: Charging Schedule
```

Available `initial_view` options:
| Value | Description |
|---|---|
| `dayGridMonth` | Full month grid (default) |
| `dayGridWeek` | 7-day week grid |
| `dayGridDay` | Single day |
| `listWeek` | Agenda list for the week |

> **Tip:** Combine the calendar with other entities to see when your car was actually charging alongside the scheduled windows:
> ```yaml
> type: calendar
> entities:
>   - calendar.wallbox_charging_schedule
> initial_view: dayGridWeek
> ```

## Insights (Charging Sessions)

The **Insights** sensor (`sensor.wallbox_insights`) tracks all charging sessions stored on the wallbox. The sensor value shows the total number of sessions; the full list is available as a state attribute.

Each session entry contains:

| Field | Description |
|---|---|
| `id` | Unique transaction ID (hex) |
| `socket` | Socket number |
| `start_date` | Session start date and time |
| `start_kwh` | Meter reading at start (kWh) |
| `stop_date` | Session stop date and time |
| `stop_kwh` | Meter reading at stop (kWh) |
| `energy_kwh` | Energy delivered in this session (kWh) |
| `tag` | RFID tag used to start the session |

Sessions are sorted by most recent first, capped at the last 500 sessions in the sensor.
They are saved in Home Assistant's storage (`.storage/alfen_wallbox.<entry>.transactions`,
up to 5000 sessions) and restored after a restart, together with the read position, so
**Load history** (Insights tab) only reads new log entries after the first full load.

To enable the Insights sensor, add `transactions` to the **Refresh Categories** in the integration options. The data refreshes automatically every ~20 minutes; you can also press **Force Fetch Transaction** to update immediately.

## Eve Connect dashboard

[`dashboards/alfen_wallbox.yaml`](dashboards/alfen_wallbox.yaml) recreates the Eve
Connect app with built-in cards only (Home Assistant 2024.8+):

| Tab | Contents |
|---|---|
| **Home** | Status message, Charge Control (Charging / Paused / Boost), Boost · Pause · Charge buttons, restriction alert, session tile (charged, duration, power, peak), power gauge and 24 h history, live phase currents/voltages, solar / grid split and green share (with a solar mode) |
| **Power** | Preferred maximum power slider, solar mode (Disable / Comfort / Green) with comfort level, green share and solar override |
| **Schedule** | Apply-schedule switch, "time slot active now", a table with the time slots and power per weekday, and an editor: pick days (their slot is loaded), set from/to/power, *Save*, *Add extra slot* or *Clear*. The *Calendar* button opens HA's calendar for the same slots |
| **Insights** | Charged energy this month / last month / this year / total and the last session (native table), *Load history* with progress, and an *Export charging history* button; the CSV / JSON download links appear in HA's notifications |
| **Settings** | Model, serial, firmware, phases, connector, uptime, WiFi; log out/in (to use the app locally), refresh schedule, reboot |

### Installing the dashboard

Requirements: Home Assistant **2024.8 or newer** and this integration **3.6.0 or newer**.

**1. Find your entity prefix.** The dashboard uses entity IDs that start with
`alfen_wallbox_` (a wallbox named *Alfen Wallbox* during setup). To see yours, open
*Settings → Devices & services → Alfen Wallbox → entities* and look at any entity ID,
e.g. `select.garage_alfen_wallbox_auth_mode` → prefix `garage_alfen_wallbox_`.

> Renaming the device later does **not** change existing entity IDs, so always check
> the actual IDs.

**2. Adjust the file if your prefix differs.** Replace `alfen_wallbox_` with your
prefix, e.g. in a terminal (macOS/Linux) — this also copies the result to the
clipboard on macOS:

```bash
sed 's/\([a-z_]\.\)alfen_wallbox_/\1garage_alfen_wallbox_/g' dashboards/alfen_wallbox.yaml > my_dashboard.yaml
pbcopy < my_dashboard.yaml   # macOS; or open the file and copy everything
```

**3. Create the dashboard.**
1. *Settings → Dashboards → **+ Add dashboard** → **New dashboard from scratch***.
   Name it e.g. *Alfen Wallbox*, icon `mdi:ev-station`, and open it from the sidebar.
2. Click the **pencil** (top right) → **⋮** → **Raw configuration editor**.
3. Click inside the text box, press **Ctrl/⌘ + A** to select the existing text, then
   **Ctrl/⌘ + V** to replace it with the dashboard file. It starts with
   `# Alfen Wallbox dashboard` and `title: Alfen Wallbox`.
4. Click **Save**, close the editor with **✕** and click **Done**.

You should now see the tabs *Home, Power, Schedule, Insights, Settings*.

**4. Load the charging history.** On the *Insights* tab press **Load history** once
(the first run reads the whole log and can take a few minutes; after that the
history is saved and only new sessions are read). To keep it updated automatically,
enable the `transactions` category in the integration options.

<details>
<summary>Alternative: YAML-mode dashboard (file in the config folder)</summary>

Copy the (adjusted) file to `<config>/dashboards/alfen_wallbox.yaml`, add this to
`configuration.yaml` and restart Home Assistant. Changes to the file then show up
after a browser refresh.

```yaml
lovelace:
  dashboards:
    alfen-wallbox:
      mode: yaml
      filename: dashboards/alfen_wallbox.yaml
      title: Alfen Wallbox
      icon: mdi:ev-station
      show_in_sidebar: true
```
</details>

## Development & Testing

### Setup

**Install dependencies:**
```bash
uv pip install -r requirements_test.txt
```

### Running Tests

**Run all tests:**
```bash
pytest tests/
```

**Run with coverage:**
```bash
pytest tests/ --cov=custom_components.alfen_wallbox --cov-report=term-missing
```

**Run specific test file:**
```bash
pytest tests/test_config_flow.py -v
```

### Code Quality

**Type checking with mypy:**
```bash
mypy custom_components/alfen_wallbox
```

**Linting with ruff:**
```bash
# Check for issues
ruff check .

# Auto-fix issues
ruff check --fix .

# Format code
ruff format .
```

**Run all checks:**
```bash
# Full quality check
pytest tests/ && mypy custom_components/alfen_wallbox && ruff check .
```

### Test Structure

- `tests/test_config_flow.py` - Config flow and options flow tests
- `tests/test_init.py` - Integration setup and teardown tests
- `tests/test_coordinator.py` - Coordinator update cycle tests
- `tests/test_alfen_device.py` - Device API communication tests

All tests use mocked device communication to avoid requiring a physical wallbox.

## Screenshots
<img src="doc/screenshots/wallbox-1.png"/>

![Wallbox 2](<doc/screenshots/wallbox-2.png>)

![Wallbox 3](<doc/screenshots/wallbox-3.png>)
