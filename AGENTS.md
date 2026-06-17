# Elite Companion — Project Guidelines

## Project Overview

A Windows background application that monitors Elite: Dangerous, reads its live journal files, aggregates game state, and streams structured JSON over USB serial to an ESP32-based display system.

The initial hardware target is a HiLetgo 2.42" SSD1309 128×64 OLED connected to a Freenove ESP32-WROOM (SDA → GPIO21, SCL → GPIO22). The architecture is designed to support multiple displays as the project grows.

## Architecture

```
EliteDangerous64.exe (process)
        │ psutil detection
        ▼
  watcher.py  ──── watchdog FileSystemEventHandler
        │
        ├── status_reader.py  → reads Status.json on every file-change event
        └── journal.py        → replays Journal.*.log on startup, then tails for new events
                    │
                    ▼
              game_state.py   (GameState dataclass — single source of truth)
                    │
                    ▼
            serial_sender.py  → newline-delimited JSON → ESP32 over USB serial
                    │
              tray.py         → pystray system tray + tkinter config window
              config.py       → JSON config persisted to %APPDATA%\EliteCompanion\
```

- `game_state.py` is the single mutable state store. All readers write into it; the serial sender reads from it.
- File watchers only activate when `EliteDangerous64.exe` is detected. They stop when the process exits.
- The serial sender is decoupled from the watchers — port loss or ESP32 disconnect must not crash the watcher loop.

## Tech Stack

- **Language**: Python 3.11+
- **Key libraries**: `watchdog`, `pyserial`, `psutil`, `pystray`, `Pillow`, `tkinter` (stdlib)
- **Packaging**: PyInstaller for single `.exe` distribution
- **Config**: JSON file at `%APPDATA%\EliteCompanion\config.json`

## Source Files

| File | Responsibility |
|------|---------------|
| `elite_companion/main.py` | Entry point; starts all threads; handles clean shutdown |
| `elite_companion/tray.py` | pystray tray icon; tkinter config window |
| `elite_companion/watcher.py` | watchdog observer; starts/stops on game detect |
| `elite_companion/journal.py` | Journal log replay + live tail; handles new session file creation |
| `elite_companion/status_reader.py` | Status.json reader; decodes Flags bitmask |
| `elite_companion/game_state.py` | GameState dataclass; thread-safe field updates |
| `elite_companion/serial_sender.py` | pyserial port lifecycle; sends JSON payload |
| `elite_companion/config.py` | Load/save config; auto-detect journal folder |

## Elite Dangerous Journal Format

### File Locations
`C:\Users\<Name>\Saved Games\Frontier Developments\Elite Dangerous\`

| File | Update Trigger |
|------|---------------|
| `Journal.<date>.<part>.log` | Continuously appended, line-delimited JSON |
| `Status.json` | Whole file replaced every ~1–4 seconds on any state change |
| `Market.json` | When player opens Commodities market screen |
| `Outfitting.json` | When player opens Outfitting screen |
| `Shipyard.json` | When player opens Shipyard screen |
| `NavRoute.json` | When a multi-jump route is plotted or cleared |
| `Cargo.json` | When cargo changes |

### Status.json — Fields Used

| Field | Type | Description |
|-------|------|-------------|
| `Flags` | int bitmask | Primary ship/player state (see bit table below) |
| `Flags2` | int bitmask | Odyssey on-foot state |
| `Pips` | `[int, int, int]` | Energy pips: `[SYS, ENG, WEP]` in half-pips; sum = 12 |
| `Fuel.FuelMain` | float | Main tank fuel in tons |
| `Fuel.FuelReservoir` | float | Reserve tank fuel in tons |
| `Cargo` | float | Cargo mass in tons |
| `LegalState` | string | `Clean`, `Wanted`, `Hostile`, `IllegalCargo`, etc. |
| `Latitude` | float | Present only when near/on a planet |
| `Longitude` | float | Present only when near/on a planet |
| `Altitude` | float | Present only when near/on a planet |
| `Heading` | float | Present only when near/on a planet |
| `Destination.Name` | string | Current nav target name |

**Flags bitmask bits relevant to this project:**

| Bit | Value | Meaning |
|-----|-------|---------|
| 0 | 1 | Docked |
| 1 | 2 | Landed |
| 3 | 8 | Shields Up |
| 4 | 16 | Supercruise |
| 6 | 64 | Hardpoints Deployed |
| 11 | 2048 | Scooping Fuel |
| 16 | 65536 | FSD Mass Locked |
| 17 | 131072 | FSD Charging |
| 18 | 262144 | FSD Cooldown |
| 19 | 524288 | Low Fuel (< 25%) |
| 20 | 1048576 | Overheating |
| 22 | 4194304 | In Danger |
| 23 | 8388608 | Being Interdicted |
| 30 | 1073741824 | FSD Jump In Progress |

### Journal Events Tracked

| Event | Fields Used |
|-------|------------|
| `LoadGame` | `Ship`, `ShipName`, `FuelLevel`, `FuelCapacity`, `Credits` |
| `Location` | `StarSystem`, `Body`, `Docked` |
| `Loadout` | `Ship`, `ShipName`, `ShipIdent`, `HullHealth`, `FuelCapacity`, `MaxJumpRange` |
| `FSDJump` | `StarSystem`, `FuelUsed`, `FuelLevel`, `JumpDist` |
| `FSDTarget` | `StarSystem`, `RemainingJumpsInRoute` |
| `NavRoute` | `Route[]` (first entry = next jump target) |
| `NavRouteClear` | (clears route data) |
| `SupercruiseEntry` / `SupercruiseExit` | `StarSystem` |
| `Docked` | `StationName`, `StarSystem` |
| `Undocked` | `StationName` |
| `ShieldState` | `ShieldsUp` |
| `HullDamage` | `Health` |
| `UnderAttack` | `Target` |
| `StartJump` | `JumpType`, `StarSystem` |

## Serial Protocol

The Windows app sends **newline-terminated JSON** (`\n`) at a configurable interval (default 500ms) or immediately on state change.

### Current OLED POC Payload Schema

For the current three-line OLED firmware, the Windows app sends a compact display payload:

```json
{
  "type": "status",
  "seq": 12,
  "ship": "Asp Explorer",
  "sys": "Sol",
  "tgt": "Alpha Centauri"
}
```

`seq` is a heartbeat counter so serial traffic can be distinguished from repeated unchanged values.

### Full State Payload Schema

```json
{
  "type": "status",
  "sys": "Sol",
  "tgt": "Alpha Centauri",
  "jumps": 3,
  "fuel": 12.4,
  "fuel_cap": 16.0,
  "low_fuel": false,
  "pips": [4, 4, 4],
  "shields": true,
  "hardpoints": false,
  "fsd": "ready",
  "legal": "Clean",
  "attack": false,
  "lat": 12.34,
  "lon": 45.67,
  "alt": 1200.5,
  "hdg": 180.3,
  "on_planet": false,
  "ship": "Asp Explorer",
  "hull": 1.0
}
```

**`fsd` values:** `"ready"` | `"charging"` | `"cooldown"` | `"masslock"` | `"jumping"`

**`type` field:** reserved for multi-display routing in future (e.g. `"nav"`, `"ship"`, `"market"`). Always `"status"` for now.

**Omitted fields:** Ship speed is not available in the Elite journal API — do not attempt to add it.

**Null handling:** Fields that have no value yet (e.g. `lat`/`lon`/`alt`/`hdg` when not on a planet) must be sent as `null`, not omitted, so the ESP32 parser always receives a consistent schema.

**Firmware buffer sizing:** Whenever the serial payload schema changes, always confirm the ESP32 serial line buffer and ArduinoJson document/filter sizes can accept the full newline-delimited JSON payload without truncation or parse failure.

## Config Schema (`config.json`)

```json
{
  "serial_port": "COM3",
  "baud_rate": 115200,
  "journal_folder": "C:\\Users\\<Name>\\Saved Games\\Frontier Developments\\Elite Dangerous",
  "send_interval_ms": 500
}
```

- `journal_folder` is auto-detected from `%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous\` on first run.
- If the folder does not exist (game not installed), store `null` and prompt the user in the config window.

## Conventions

- **Thread safety**: `GameState` fields are updated from multiple threads (journal thread, status thread). Use `threading.Lock` for all writes. Reads in the serial sender do not need a lock (stale reads are acceptable for display purposes).
- **No crash on serial loss**: If the serial port disappears (USB unplug), log the error, mark the port as disconnected, and retry connection every 5 seconds. Do not propagate the exception to the watcher threads.
- **Journal file rotation**: Elite creates a new `Journal.*.log` file each game session. `journal.py` must detect new file creation via watchdog and switch to tailing the new file, discarding the old tail.
- **Encoding**: All journal files are UTF-8. Open with `encoding="utf-8"`.
- **Line parsing**: Each journal line is independent JSON. Skip lines that fail to parse (`json.JSONDecodeError`) without crashing.
- **Serial buffer safety**: Any change to payload shape or firmware parsing must explicitly account for serial input buffer length and ArduinoJson capacity/filter sizing on the ESP32.
- **Status.json race**: The file is replaced atomically by the game. Read the entire file on each change event; do not hold a file handle open.
- **Process detection polling interval**: 5 seconds is sufficient. Do not use a watchdog for process detection.

## Build and Run

```powershell
# Install dependencies
py -m pip install -r requirements.txt

# Run in development
py -m elite_companion

# Build standalone exe
py -m PyInstaller elite_companion.spec
```

## Hardware Reference (POC)

- **Display**: HiLetgo 2.42" SSD1309 128×64 OLED
- **MCU**: Freenove ESP32-S3 WROOM
- **I²C wiring**: SDA → GPIO21, SCL → GPIO22
- **USB serial**: default 115200 baud

## Display Hardware Findings

The verified expanded hardware setup supports three displays at once:

| Position | Display | Bus | Pins |
|----------|---------|-----|------|
| Left | ST7789 TFT 170×320 | HSPI | SCLK GPIO14, MOSI GPIO13, CS GPIO27, DC GPIO33, RST GPIO26 |
| Right | ST7789 TFT 170×320 | VSPI | SCLK GPIO18, MOSI GPIO23, CS GPIO25, DC GPIO16, RST GPIO4 |
| Auxiliary | SSD1309 OLED 128×64 | I²C | SDA GPIO21, SCL GPIO22 |

These pins are the known-good ST7789/TFT topology from hardware testing. Keep the two TFTs on separate SPI buses (`HSPI` and `VSPI`) unless there is a deliberate retest, and keep the OLED on I²C. The OLED has been verified to operate at the same time as both TFT displays without SPI/I²C conflicts.

When changing ESP32 display firmware:

- Prefer the verified ST7789 split-bus pin map above for dual TFT work.
- Use `Adafruit_GFX`/`Adafruit_ST7789` for the TFTs and U8g2 or Adafruit SSD1306-compatible support for the SSD1309 OLED, matching the current sketch being edited.
- Account for Adafruit_GFX text rendering cost. A Matrix-style text animation across the TFTs measured about 8-9 FPS; many small text draws and repeated full-screen updates are the limiting factor more than ESP32 CPU saturation.
- For smoother TFT animation, reduce per-frame text draw count, update only dirty regions where practical, and avoid unnecessary full-screen clears.
- The dual ST7789 displays have been verified as one virtual 340×320 display for cross-screen animation; preserve the left/right orientation and coordinate assumptions when building dual-screen effects.
- The LCARS dual-TFT demo plus OLED scrolling text has been verified stable with all three displays active.
- The SSD1309 OLED may produce audible buzz/whine while still functioning normally. The likely causes are charge-pump or passive-component resonance and frequent full-buffer refreshes.
- If OLED noise is an issue, test slower refresh intervals first (`150ms`, `250ms`, `500ms`), then lower contrast (`40`, `80`, `120`), and consider local decoupling near the OLED (`0.1uF` ceramic plus `10uF` electrolytic).

## ESP32 Firmware

The firmware lives in `arduino/` — an Arduino IDE sketch targeting the Freenove ESP32-S3 WROOM.

| Item | Detail |
|------|--------|
| Board | `Freenove ESP32-S3 WROOM` |
| IDE | Arduino IDE |
| Entry point | `arduino/firmware/firmware.ino` |

The firmware is responsible for:
- Receiving newline-delimited JSON over USB serial
- Parsing the payload
- Maintaining serial input and JSON parse buffers large enough for the full host payload
- Rendering data on the SSD1309 128×64 OLED via I²C
