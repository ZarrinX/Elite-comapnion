# Elite Companion — Work Tracker

## Phase 1: Project Scaffold + Config ✅

- [x] Create `pyproject.toml` with project metadata and dependencies
- [x] Create `requirements.txt` (`watchdog`, `pyserial`, `psutil`, `pystray`, `Pillow`)
- [x] Create `elite_companion/` package with `__init__.py`
- [x] Create `elite_companion/config.py`
  - [x] Define config schema (`serial_port`, `baud_rate`, `journal_folder`, `send_interval_ms`)
  - [x] Auto-detect journal folder from `%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous\`
  - [x] Load config from `%APPDATA%\EliteCompanion\config.json` (create with defaults if missing)
  - [x] Save config back to disk

## Phase 2: Game State Model ✅

- [x] Create `elite_companion/game_state.py`
  - [x] Define `GameState` dataclass with all tracked fields
  - [x] Add `threading.Lock` for write operations
  - [x] Implement `to_payload()` method that serialises to the serial JSON schema
  - [x] Ensure `null` (not omitted) for fields with no value (lat/lon/alt/hdg when not on planet)

## Phase 3: Game Process Detection ✅

- [x] Create `elite_companion/watcher.py`
  - [x] Poll for `EliteDangerous64.exe` every 5 seconds using `psutil`
  - [x] Emit start event → activate journal + status file watchers
  - [x] Emit stop event → deactivate watchers, notify serial sender
  - [x] Run in a daemon thread; stop cleanly on app shutdown

## Phase 4: Status.json Reader ✅

- [x] Create `elite_companion/status_reader.py`
  - [x] Register watchdog `FileSystemEventHandler` for `Status.json` changes
  - [x] Read entire file on each change event (do not hold file handle open)
  - [x] Decode `Flags` bitmask: Docked, Landed, Shields Up, Supercruise, Hardpoints, Scooping, Low Fuel, Overheating, In Danger, Being Interdicted, FSD Mass Locked, FSD Charging, FSD Cooldown, FSD Jump in Progress
  - [x] Extract `Pips` `[SYS, ENG, WEP]`
  - [x] Extract `Fuel.FuelMain`, `Fuel.FuelReservoir`
  - [x] Extract `Cargo`, `LegalState`
  - [x] Extract `Latitude`, `Longitude`, `Altitude`, `Heading` (set `on_planet` flag from Flags bit 21)
  - [x] Extract `Destination.Name` as nav target fallback
  - [x] Write all extracted values into `GameState` under lock
  - [x] Skip gracefully on `json.JSONDecodeError` or missing file

## Phase 5: Journal Log Reader ✅

- [x] Create `elite_companion/journal.py`
  - [x] Find the most recent `Journal.*.log` file in the journal folder
  - [x] Replay all existing lines on startup to reconstruct current state
  - [x] Register watchdog handler to tail the file for new lines in real time
  - [x] Detect new `Journal.*.log` file creation (new game session) and switch tail to new file
  - [x] Handle each event type:
    - [x] `LoadGame` → `ship`, `fuel_level`, `fuel_cap`, `credits`
    - [x] `Location` → `star_system`, `body`, `docked`
    - [x] `Loadout` → `ship`, `ship_name`, `hull`, `fuel_cap`, `max_jump_range`
    - [x] `FSDJump` → `star_system`, `fuel_level`, `jump_dist`
    - [x] `FSDTarget` → `jump_target`, `jumps_remaining`
    - [x] `NavRoute` → `jump_target` from first route entry
    - [x] `NavRouteClear` → clear route/target data
    - [x] `StartJump` → set `fsd` state to `"jumping"`
    - [x] `SupercruiseEntry` / `SupercruiseExit` → update `star_system`
    - [x] `Docked` → `station_name`, `star_system`, set docked flag
    - [x] `Undocked` → clear station, clear docked flag
    - [x] `ShieldState` → `shields`
    - [x] `HullDamage` → `hull`
    - [x] `UnderAttack` → set `attack` flag (auto-clear after interval)
  - [x] Open files with `encoding="utf-8"`; skip lines on `json.JSONDecodeError`

## Phase 6: Serial Sender ✅

- [x] Create `elite_companion/serial_sender.py`
  - [x] Open configured COM port at configured baud rate
  - [x] Send `GameState.to_payload()` as newline-terminated JSON at `send_interval_ms`
  - [x] Send immediately on state change (in addition to interval)
  - [x] Handle port loss gracefully: log error, mark disconnected, retry every 5 seconds
  - [x] Do not propagate serial exceptions to watcher threads
  - [x] Close port cleanly on shutdown

## Phase 7: System Tray + Config UI ✅

- [x] Create `elite_companion/tray.py`
  - [x] Render tray icon using Pillow (draw simple icon programmatically; no external asset required for POC)
  - [x] Tray menu items: **Open Config**, **Status** (game detected / not detected, serial connected / disconnected), **Quit**
  - [x] Config window (tkinter):
    - [x] COM port dropdown (enumerate available ports via `serial.tools.list_ports`)
    - [x] Baud rate field (default 115200)
    - [x] Journal folder path field + Browse button
    - [x] Send interval (ms) field
    - [x] Live status indicators: game detected, serial connected
    - [x] Save button → write config and apply without restart
  - [x] Tray icon tooltip shows current game/serial state

## Phase 8: Entry Point + Thread Orchestration ✅

- [x] Create `elite_companion/main.py`
  - [x] Instantiate and start all threads: process watcher, serial sender, tray
  - [x] Wire game-detected/stopped events to start/stop file watchers
  - [x] Handle `SIGINT` / window close → graceful shutdown of all threads
  - [x] Support `python -m elite_companion` invocation

## Phase 9: Error Handling + Robustness ✅

- [x] Verify no thread can crash the app on serial port loss
- [x] Verify journal reader recovers from file-not-found (game not running, folder wrong)
- [x] Verify watchdog stops cleanly when game exits mid-session
- [x] Verify `Status.json` read-on-change does not hold a file lock
- [x] Add logging (`logging` stdlib) to file at `%APPDATA%\EliteCompanion\app.log`

## Phase 10: Packaging ✅

- [x] Create `elite_companion.spec` for PyInstaller
  - [x] Single-file `.exe` output
  - [x] Bundle tray icon asset
  - [x] Hide console window (`noconsole=True`)
- [x] Test packaged `.exe` on clean machine (no Python installed)
- [x] Update `README.md` with install and usage instructions

---

## Verification Checklist

- [ ] `python -m elite_companion` starts; tray icon appears
- [ ] Config window opens; COM ports enumerate; journal folder auto-detected
- [ ] Launch Elite: Dangerous → tray status changes to "Game detected"
- [ ] Connect ESP32 → serial connects; JSON lines visible in serial monitor
- [ ] Change system / take damage in-game → payload updates correctly
- [ ] Unplug ESP32 → app logs error, retries every 5s, does not crash
- [ ] Quit Elite → watchers stop; serial closes cleanly
- [ ] Packaged `.exe` runs without Python installed
