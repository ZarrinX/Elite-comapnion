"""JournalReader — replays and tails Elite: Dangerous journal log files.

On start:
  1. Finds the most recent Journal.*.log in the journal folder.
  2. Replays all existing lines to reconstruct current game state.
  3. Starts a watchdog observer to tail new lines as they arrive.

Session rotation:
  When Elite creates a new Journal.*.log (new game session), the watchdog
  detects the file creation and switches the tail to the new file.

Thread safety:
  All GameState writes go through GameState.update() which holds the write lock.
  The UnderAttack flag is auto-cleared via a threading.Timer.
"""

import glob
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .game_state import GameState
from .nav_route_reader import target_from_route

logger = logging.getLogger(__name__)

_JOURNAL_GLOB = "Journal.*.log"
_ATTACK_CLEAR_DELAY = 10.0   # seconds before auto-clearing UnderAttack flag
_POLL_INTERVAL = 1.0


def _fuel_capacity_main(value):
    """Return main tank capacity from either a number or Elite's dict shape."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, dict):
        for key in ("Main", "FuelMain", "Capacity"):
            candidate = value.get(key)
            if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
                return candidate
    return None


def _latest_journal(folder: str) -> Optional[str]:
    """Return the path of the most recent Journal.*.log, or None."""
    pattern = os.path.join(folder, _JOURNAL_GLOB)
    matches = glob.glob(pattern)
    if not matches:
        return None
    return max(matches)   # lexicographic sort works because filenames are ISO timestamps


# ------------------------------------------------------------------ #
# Event dispatch                                                       #
# ------------------------------------------------------------------ #

class _EventDispatcher:
    """Parses a single journal JSON line and updates GameState."""

    def __init__(self, state: GameState) -> None:
        self._state = state
        self._attack_timer: Optional[threading.Timer] = None

    def dispatch(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return

        event = ev.get("event")
        if not event:
            return

        handler = getattr(self, f"_on_{event}", None)
        if handler:
            try:
                handler(ev)
            except Exception:
                logger.exception("Error handling journal event %s", event)

    # ------------------------------------------------------------------ #
    # Event handlers                                                       #
    # ------------------------------------------------------------------ #

    def _on_LoadGame(self, ev: dict) -> None:
        logger.info("Journal LoadGame: ship=%s", ev.get("Ship"))
        self._state.update(
            ship       = ev.get("Ship"),
            ship_name  = ev.get("ShipName"),
            ship_ident = ev.get("ShipIdent"),
            fuel       = ev.get("FuelLevel"),
            fuel_cap   = _fuel_capacity_main(ev.get("FuelCapacity")),
            credits    = ev.get("Credits"),
        )

    def _on_Location(self, ev: dict) -> None:
        logger.info("Journal Location: system=%s", ev.get("StarSystem"))
        self._state.update(
            star_system = ev.get("StarSystem"),
            body        = ev.get("Body"),
            docked      = bool(ev.get("Docked", False)),
        )

    def _on_Loadout(self, ev: dict) -> None:
        self._state.update(
            ship           = ev.get("Ship"),
            ship_name      = ev.get("ShipName"),
            ship_ident     = ev.get("ShipIdent"),
            hull           = ev.get("HullHealth", 1.0),
            fuel_cap       = _fuel_capacity_main(ev.get("FuelCapacity")),
            max_jump_range = ev.get("MaxJumpRange"),
        )

    def _on_FSDJump(self, ev: dict) -> None:
        logger.info("Journal FSDJump: system=%s", ev.get("StarSystem"))
        self._state.update(
            star_system = ev.get("StarSystem"),
            fuel        = ev.get("FuelLevel"),
            # Clear jump target and route on arrival — FSDTarget will repopulate
            jump_target      = None,
            jumps_remaining  = None,
        )

    def _on_FSDTarget(self, ev: dict) -> None:
        logger.info(
            "Journal FSDTarget: target=%s jumps=%s",
            ev.get("StarSystem"),
            ev.get("RemainingJumpsInRoute"),
        )
        self._state.update(
            jump_target     = ev.get("StarSystem"),
            jumps_remaining = ev.get("RemainingJumpsInRoute"),
        )

    def _on_NavRoute(self, ev: dict) -> None:
        route = ev.get("Route", [])
        if route:
            target = target_from_route(route, self._state.star_system)
            logger.info("Journal NavRoute: target=%s count=%s", target, len(route))
            self._state.update(jump_target=target, jumps_remaining=len(route))

    def _on_NavRouteClear(self, ev: dict) -> None:
        logger.info("Journal NavRouteClear")
        self._state.update(
            jump_target     = None,
            jumps_remaining = None,
        )

    def _on_StartJump(self, ev: dict) -> None:
        if ev.get("JumpType") == "Hyperspace":
            self._state.update(fsd = "jumping")

    def _on_SupercruiseEntry(self, ev: dict) -> None:
        self._state.update(
            star_system = ev.get("StarSystem"),
            supercruise = True,
        )

    def _on_SupercruiseExit(self, ev: dict) -> None:
        self._state.update(
            star_system = ev.get("StarSystem"),
            supercruise = False,
        )

    def _on_Docked(self, ev: dict) -> None:
        self._state.update(
            station_name = ev.get("StationName"),
            star_system  = ev.get("StarSystem"),
            docked       = True,
        )

    def _on_Undocked(self, ev: dict) -> None:
        self._state.update(
            station_name = None,
            docked       = False,
        )

    def _on_ShieldState(self, ev: dict) -> None:
        self._state.update(shields = bool(ev.get("ShieldsUp", True)))

    def _on_HullDamage(self, ev: dict) -> None:
        self._state.update(hull = ev.get("Health", 1.0))

    def _on_UnderAttack(self, ev: dict) -> None:
        self._state.update(under_attack = True)
        # Cancel any existing timer before starting a new one
        if self._attack_timer and self._attack_timer.is_alive():
            self._attack_timer.cancel()
        self._attack_timer = threading.Timer(
            _ATTACK_CLEAR_DELAY,
            lambda: self._state.update(under_attack=False),
        )
        self._attack_timer.daemon = True
        self._attack_timer.start()

    def _on_Repair(self, ev: dict) -> None:
        pass   # Hull health is updated via HullDamage events; no action needed

    def _on_RepairAll(self, ev: dict) -> None:
        self._state.update(hull = 1.0)

    def cancel_timers(self) -> None:
        if self._attack_timer and self._attack_timer.is_alive():
            self._attack_timer.cancel()


# ------------------------------------------------------------------ #
# Watchdog handler                                                     #
# ------------------------------------------------------------------ #

class _JournalHandler(FileSystemEventHandler):
    """Handles file-system events for the journal folder."""

    def __init__(self, reader: "JournalReader") -> None:
        super().__init__()
        self._reader = reader

    def on_modified(self, event):
        if event.is_directory:
            return
        if os.path.abspath(event.src_path) == self._reader.current_path:
            self._reader._read_new_lines()

    def on_created(self, event):
        if event.is_directory:
            return
        name = os.path.basename(event.src_path)
        # Switch to a new Journal file if one is created
        if name.startswith("Journal.") and name.endswith(".log"):
            new_path = os.path.abspath(event.src_path)
            if new_path != self._reader.current_path:
                logger.info("New journal file detected: %s", name)
                self._reader._switch_to(new_path)


# ------------------------------------------------------------------ #
# Public class                                                         #
# ------------------------------------------------------------------ #

class JournalReader:
    """Replays and live-tails Elite: Dangerous journal log files."""

    def __init__(self, journal_folder: str, state: GameState) -> None:
        self._folder = journal_folder
        self._state = state
        self._dispatcher = _EventDispatcher(state)
        self._observer: Optional[Observer] = None
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._current_path: Optional[str] = None
        self._file_pos: int = 0
        self._lock = threading.Lock()   # guards _current_path and _file_pos

    @property
    def current_path(self) -> Optional[str]:
        with self._lock:
            return self._current_path

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if not os.path.isdir(self._folder):
            logger.error("Journal folder not found: %s — JournalReader not started",
                         self._folder)
            return

        self._running = True

        latest = _latest_journal(self._folder)
        if latest:
            self._replay(latest)
        else:
            logger.warning("No journal files found in %s", self._folder)

        handler = _JournalHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, self._folder, recursive=False)
        self._observer.start()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="JournalPoller",
            daemon=True,
        )
        self._poll_thread.start()
        logger.info("JournalReader watching %s (current: %s)",
                    self._folder, os.path.basename(latest) if latest else "none")

    def stop(self) -> None:
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=_POLL_INTERVAL + 1)
            self._poll_thread = None
        self._dispatcher.cancel_timers()
        logger.info("JournalReader stopped")

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _replay(self, path: str) -> None:
        """Read all existing lines in a journal file and update state."""
        with self._lock:
            self._current_path = os.path.abspath(path)
            self._file_pos = 0

        try:
            with open(path, encoding="utf-8") as f:
                while True:
                    line = f.readline()
                    if not line:
                        break
                    self._dispatcher.dispatch(line)
                with self._lock:
                    self._file_pos = f.tell()
        except OSError as exc:
            logger.warning("Could not read journal %s: %s", path, exc)

    def _switch_to(self, path: str) -> None:
        """Switch tail to a new journal file (new game session)."""
        self._replay(path)

    def _read_new_lines(self) -> None:
        """Read any lines appended since last read."""
        with self._lock:
            path = self._current_path
            pos = self._file_pos

        if not path:
            return

        try:
            with open(path, encoding="utf-8") as f:
                if os.path.getsize(path) < pos:
                    pos = 0
                f.seek(pos)
                lines = f.readlines()
                new_pos = f.tell()
        except OSError as exc:
            logger.warning("Could not tail journal: %s", exc)
            return

        with self._lock:
            self._file_pos = new_pos

        for line in lines:
            self._dispatcher.dispatch(line)

    def _poll_loop(self) -> None:
        """Poll as a fallback for journal updates missed by watchdog."""
        while self._running:
            latest = _latest_journal(self._folder)
            current = self.current_path

            if latest:
                latest = os.path.abspath(latest)
                if latest != current:
                    logger.info("Journal poll detected active file: %s",
                                os.path.basename(latest))
                    self._switch_to(latest)
                else:
                    self._read_new_lines()

            time.sleep(_POLL_INTERVAL)
