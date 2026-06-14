# Elite Companion — Work Tracker

## Phase 1: Project Scaffold + Config

- [ ] Create `pyproject.toml` with project metadata and dependencies
- [ ] Create `requirements.txt` (`watchdog`, `pyserial`, `psutil`, `pystray`, `Pillow`)
- [ ] Create `elite_companion/` package with `__init__.py`
- [ ] Create `elite_companion/config.py`
  - [ ] Define config schema (`serial_port`, `baud_rate`, `journal_folder`, `send_interval_ms`)
  - [ ] Auto-detect journal folder from `%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous\`
  - [ ] Load config from `%APPDATA%\EliteCompanion\config.json` (create with defaults if missing)
  - [ ] Save config back to disk

## Phase 2: Game State Model

- [ ] Create `elite_companion/game_state.py`
  - [ ] Define `GameState` dataclass with all tracked fields
  - [ ] Add `threading.Lock` for write operations
  - [ ] Implement `to_payload()` method that serialises to the serial JSON schema
  - [ ] Ensure `null` (not omitted) for fields with no value (lat/lon/alt/hdg when not on planet)

## Phase 3: Game Process Detection

- [ ] Create `elite_companion/watcher.py`
  - [ ] Poll for `EliteDangerous64.exe` every 5 seconds using `psutil`
  - [ ] Emit start event → activate journal + status file watchers
  - [ ] Emit stop event → deactivate watchers, notify serial sender
  - [ ] Run in a daemon thread; stop cleanly on app shutdown

## Phase 4: Status.json Reader

- [ ] Create `elite_companion/status_reader.py`
  - [ ] Register watchdog `FileSystemEventHandler` for `Status.json` changes
  - [ ] Read entire file on each change event (do not hold file handle open)
  - [ ] Decode `Flags` bitmask: Docked, Landed, Shields Up, Supercruise, Hardpoints, Scooping, Low Fuel, Overheating, In Danger, Being Interdicted, FSD Mass Locked, FSD Charging, FSD Cooldown, FSD Jump in Progress
  - [ ] Extract `Pips` `[SYS, ENG, WEP]`
  - [ ] Extract `Fuel.FuelMain`, `Fuel.FuelReservoir`
  - [ ] Extract `Cargo`, `LegalState`
  - [ ] Extract `Latitude`, `Longitude`, `Altitude`, `Heading` (set `on_planet` flag from Flags bit 21)
  - [ ] Extract `Destination.Name` as nav target fallback
  - [ ] Write all extracted values into `GameState` under lock
  - [ ] Skip gracefully on `json.JSONDecodeError` or missing file

## Phase 5: Journal Log Reader

- [ ] Create `elite_companion/journal.py`
  - [ ] Find the most recent `Journal.*.log` file in the journal folder
  - [ ] Replay all existing lines on startup to reconstruct current state
  - [ ] Register watchdog handler to tail the file for new lines in real time
  - [ ] Detect new `Journal.*.log` file creation (new game session) and switch tail to new file
  - [ ] Handle each event type:
    - [ ] `LoadGame` → `ship`, `fuel_level`, `fuel_cap`, `credits`
    - [ ] `Location` → `star_system`, `body`, `docked`
    - [ ] `Loadout` → `ship`, `ship_name`, `hull`, `fuel_cap`, `max_jump_range`
    - [ ] `FSDJump` → `star_system`, `fuel_level`, `jump_dist`
    - [ ] `FSDTarget` → `jump_target`, `jumps_remaining`
    - [ ] `NavRoute` → `jump_target` from first route entry
    - [ ] `NavRouteClear` → clear route/target data
    - [ ] `StartJump` → set `fsd` state to `"jumping"`
    - [ ] `SupercruiseEntry` / `SupercruiseExit` → update `star_system`
    - [ ] `Docked` → `station_name`, `star_system`, set docked flag
    - [ ] `Undocked` → clear station, clear docked flag
    - [ ] `ShieldState` → `shields`
    - [ ] `HullDamage` → `hull`
    - [ ] `UnderAttack` → set `attack` flag (auto-clear after interval)
  - [ ] Open files with `encoding="utf-8"`; skip lines on `json.JSONDecodeError`

## Phase 6: Serial Sender

- [ ] Create `elite_companion/serial_sender.py`
  - [ ] Open configured COM port at configured baud rate
  - [ ] Send `GameState.to_payload()` as newline-terminated JSON at `send_interval_ms`
  - [ ] Send immediately on state change (in addition to interval)
  - [ ] Handle port loss gracefully: log error, mark disconnected, retry every 5 seconds
  - [ ] Do not propagate serial exceptions to watcher threads
  - [ ] Close port cleanly on shutdown

## Phase 7: System Tray + Config UI

- [ ] Create `elite_companion/tray.py`
  - [ ] Render tray icon using Pillow (draw simple icon programmatically; no external asset required for POC)
  - [ ] Tray menu items: **Open Config**, **Status** (game detected / not detected, serial connected / disconnected), **Quit**
  - [ ] Config window (tkinter):
    - [ ] COM port dropdown (enumerate available ports via `serial.tools.list_ports`)
    - [ ] Baud rate field (default 115200)
    - [ ] Journal folder path field + Browse button
    - [ ] Send interval (ms) field
    - [ ] Live status indicators: game detected, serial connected
    - [ ] Save button → write config and apply without restart
  - [ ] Tray icon tooltip shows current game/serial state

## Phase 8: Entry Point + Thread Orchestration

- [ ] Create `elite_companion/main.py`
  - [ ] Instantiate and start all threads: process watcher, serial sender, tray
  - [ ] Wire game-detected/stopped events to start/stop file watchers
  - [ ] Handle `SIGINT` / window close → graceful shutdown of all threads
  - [ ] Support `python -m elite_companion` invocation

## Phase 9: Error Handling + Robustness

- [ ] Verify no thread can crash the app on serial port loss
- [ ] Verify journal reader recovers from file-not-found (game not running, folder wrong)
- [ ] Verify watchdog stops cleanly when game exits mid-session
- [ ] Verify `Status.json` read-on-change does not hold a file lock
- [ ] Add logging (`logging` stdlib) to file at `%APPDATA%\EliteCompanion\app.log`

## Phase 10: Packaging

- [ ] Create `elite_companion.spec` for PyInstaller
  - [ ] Single-file `.exe` output
  - [ ] Bundle tray icon asset
  - [ ] Hide console window (`noconsole=True`)
- [ ] Test packaged `.exe` on clean machine (no Python installed)
- [ ] Update `README.md` with install and usage instructions

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
