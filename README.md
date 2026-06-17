# Elite Companion

A Windows background application that monitors Elite: Dangerous and streams live flight data to external displays connected via USB serial.

The app reads the game's journal files in real time, aggregates state, and sends structured JSON to an ESP32 microcontroller driving OLED/LCD screens — giving you a heads-up instrument panel without any in-game overlays.

## Features

- Automatically detects when Elite: Dangerous is running and activates file watchers
- Reads `Status.json` every ~1–4 seconds: fuel, pips (SYS/ENG/WEP), shields, FSD state, heading/altitude, legal status
- Tails live Journal log events: star system, jump target, route progress, hull health, docking state
- Reads `NavRoute.json` to populate the next jump destination for the OLED
- Streams compact newline-delimited JSON over USB serial to an ESP32 at a configurable interval
- Blanks the OLED automatically when Elite: Dangerous is not running to reduce burn-in risk
- Runs silently in the system tray with a small config window for port/folder settings
- Handles serial disconnects gracefully — retries every 5 seconds without crashing

## Hardware (POC)

| Component | Detail |
|-----------|--------|
| Display | HiLetgo 2.42" SSD1309 128×64 OLED |
| MCU | Freenove ESP32-S3 WROOM |
| I²C wiring | SDA → GPIO21, SCL → GPIO22 |
| USB serial | 115200 baud (configurable) |

## Repository Layout

```
Elite-comapnion/
├── elite_companion/        # Windows Python app (host)
├── arduino/
│   └── firmware/
│       └── firmware.ino  # ESP32 firmware (Arduino IDE)
├── AGENTS.md
├── README.md
└── todo.md
```

## Architecture

```
EliteDangerous64.exe
        │  psutil process detection
        ▼
  watcher.py  ──── watchdog FileSystemEventHandler
        ├── status_reader.py   (Status.json on every file change)
        ├── journal.py         (Journal.*.log replay + live tail)
        └── nav_route_reader.py (NavRoute.json next jump target)
                    ▼
              game_state.py    (single source of truth)
                    ▼
            serial_sender.py   (newline-delimited JSON → ESP32)
```

## Serial Payload

The current OLED proof-of-concept receives a compact display payload rather than the full internal game state:

```json
{
  "type": "status",
  "seq": 12,
  "ship": "Asp Explorer",
  "sys": "LHS 3885",
  "tgt": "Sol"
}
```

`seq` is a heartbeat counter used for serial diagnostics.

When Elite is not running, the app sends a blanking command:

```json
{
  "type": "blank",
  "seq": 13
}
```

The firmware clears the OLED for `type: "blank"`. This prevents static text from sitting on the display while the game is closed.

The richer `GameState.to_payload()` schema still exists internally for future multi-display/status work.
Its `fsd` values are `"ready"` | `"charging"` | `"cooldown"` | `"masslock"` | `"jumping"`.
Fields with no current value in that full schema should remain explicit `null` values rather than omitted.

The firmware uses fixed-size serial and JSON buffers, so any future wire-format expansion must include a buffer-size check on the ESP32 side.

## Getting Started

```powershell
# Install dependencies
py -m pip install -r requirements.txt

# Run in development
py -m elite_companion

# Build standalone .exe
py -m PyInstaller elite_companion.spec
```

After changing firmware, upload `arduino/firmware/firmware.ino` from the Arduino IDE.

On first run the app will auto-detect the journal folder at:
```
%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous\
```

Open the config window from the system tray icon to set the COM port and adjust settings.

## Config

Stored at `%APPDATA%\EliteCompanion\config.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `serial_port` | `null` | COM port for the ESP32 (e.g. `COM3`) |
| `baud_rate` | `115200` | Serial baud rate |
| `journal_folder` | auto-detected | Path to Elite Dangerous saved games folder |
| `send_interval_ms` | `500` | How often to push state updates (ms) |

## Requirements

- Windows 10/11
- Python 3.11+
- Elite: Dangerous (Horizons or Odyssey)
- ESP32 connected via USB
- Arduino IDE libraries for firmware:
  - Adafruit SSD1306
  - Adafruit GFX Library
  - ArduinoJson

## Diagnostics

The app writes logs to:

```
%APPDATA%\EliteCompanion\app.log
```

Useful serial log lines include:

- `Serial payload display fields: ...`
- `Serial payload display fields: blank`
- `Serial heartbeat: seq=...`
- `ESP32: {"ack":...}`
