"""StatusReader — watches Status.json and updates GameState on every change.

The game replaces Status.json atomically every ~1–4 seconds.
We read the entire file on each watchdog event; we never hold the handle open.
"""

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

logger = logging.getLogger(__name__)

_STATUS_FILE = "Status.json"
_POLL_INTERVAL = 1.0

# ------------------------------------------------------------------ #
# Flags bitmask constants                                              #
# ------------------------------------------------------------------ #
_F_DOCKED            = 1
_F_LANDED            = 2
_F_SHIELDS_UP        = 8
_F_SUPERCRUISE       = 16
_F_HARDPOINTS        = 64
_F_SCOOPING          = 2048
_F_FSD_MASSLOCKED    = 65536
_F_FSD_CHARGING      = 131072
_F_FSD_COOLDOWN      = 262144
_F_LOW_FUEL          = 524288
_F_OVERHEATING       = 1048576
_F_HAS_LAT_LON       = 2097152   # bit 21 — on planet / near surface
_F_IN_DANGER         = 4194304
_F_INTERDICTED       = 8388608
_F_FSD_JUMPING       = 1073741824


def _fsd_state(flags: int) -> str:
    """Derive FSD state string from Flags bitmask."""
    if flags & _F_FSD_JUMPING:
        return "jumping"
    if flags & _F_FSD_CHARGING:
        return "charging"
    if flags & _F_FSD_COOLDOWN:
        return "cooldown"
    if flags & _F_FSD_MASSLOCKED:
        return "masslock"
    return "ready"


def _parse_and_apply(path: str, state: GameState) -> None:
    """Read Status.json and push all relevant fields into GameState."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Status.json read skipped: %s", exc)
        return

    flags: int = data.get("Flags", 0)
    on_planet: bool = bool(flags & _F_HAS_LAT_LON)

    fuel_obj = data.get("Fuel", {})
    destination = data.get("Destination", {})

    # Only update jump_target from Destination if we don't already have a
    # better value from the journal (journal takes precedence — handled by
    # only setting if current value is None in the caller, but here we
    # always write; journal.py writes jump_target from FSDTarget which is
    # more reliable, so this serves as a fallback when journal hasn't fired)
    dest_name: Optional[str] = destination.get("Name") or None

    update_kwargs = dict(
        # Flags-derived booleans
        docked            = bool(flags & _F_DOCKED),
        landed            = bool(flags & _F_LANDED),
        shields           = bool(flags & _F_SHIELDS_UP),
        supercruise       = bool(flags & _F_SUPERCRUISE),
        hardpoints        = bool(flags & _F_HARDPOINTS),
        scooping          = bool(flags & _F_SCOOPING),
        low_fuel          = bool(flags & _F_LOW_FUEL),
        overheating       = bool(flags & _F_OVERHEATING),
        in_danger         = bool(flags & _F_IN_DANGER),
        being_interdicted = bool(flags & _F_INTERDICTED),
        fsd               = _fsd_state(flags),
        on_planet         = on_planet,
        # Pips
        pips              = list(data["Pips"]) if "Pips" in data else [4, 4, 4],
        # Fuel
        fuel              = fuel_obj.get("FuelMain"),
        fuel_reservoir    = fuel_obj.get("FuelReservoir"),
        # Misc
        cargo             = data.get("Cargo"),
        legal             = data.get("LegalState", "Clean"),
        # Surface coords (present only when on_planet)
        lat               = data.get("Latitude")  if on_planet else None,
        lon               = data.get("Longitude") if on_planet else None,
        alt               = data.get("Altitude")  if on_planet else None,
        hdg               = data.get("Heading")   if on_planet else None,
    )

    # Only overwrite jump_target if the status file has one and the
    # journal hasn't already set a more specific one
    if dest_name:
        update_kwargs["jump_target"] = dest_name

    state.update(**update_kwargs)
    logger.debug("Status updated — fsd=%s on_planet=%s fuel=%s",
                 update_kwargs["fsd"], on_planet, update_kwargs["fuel"])


class _StatusHandler(FileSystemEventHandler):
    def __init__(self, path: str, state: GameState) -> None:
        super().__init__()
        self._path = path
        self._state = state

    def on_modified(self, event):
        if not event.is_directory and os.path.basename(event.src_path) == _STATUS_FILE:
            _parse_and_apply(self._path, self._state)

    # Some OS/editors fire on_created instead of on_modified on atomic replace
    on_created = on_modified


class StatusReader:
    """Watches the journal folder for Status.json changes."""

    def __init__(self, journal_folder: str, state: GameState) -> None:
        self._folder = journal_folder
        self._state = state
        self._status_path = str(Path(journal_folder) / _STATUS_FILE)
        self._observer: Optional[Observer] = None
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._last_mtime: Optional[float] = None

    def start(self) -> None:
        """Do an immediate read, then start the watchdog observer."""
        if not os.path.isdir(self._folder):
            logger.error("Journal folder not found: %s — StatusReader not started",
                         self._folder)
            return

        self._running = True
        _parse_and_apply(self._status_path, self._state)
        self._last_mtime = self._mtime()

        handler = _StatusHandler(self._status_path, self._state)
        self._observer = Observer()
        self._observer.schedule(handler, self._folder, recursive=False)
        self._observer.start()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="StatusFilePoller",
            daemon=True,
        )
        self._poll_thread.start()
        logger.info("StatusReader watching %s", self._folder)

    def stop(self) -> None:
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=_POLL_INTERVAL + 1)
            self._poll_thread = None
        logger.info("StatusReader stopped")

    def _mtime(self) -> Optional[float]:
        try:
            return os.path.getmtime(self._status_path)
        except OSError:
            return None

    def _poll_loop(self) -> None:
        """Poll as a fallback for Status.json atomic replacement events."""
        while self._running:
            mtime = self._mtime()
            if mtime is not None and mtime != self._last_mtime:
                self._last_mtime = mtime
                _parse_and_apply(self._status_path, self._state)
            time.sleep(_POLL_INTERVAL)
