"""NavRouteReader — watches NavRoute.json for plotted jump routes."""

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

_NAV_ROUTE_FILE = "NavRoute.json"
_POLL_INTERVAL = 1.0


def target_from_route(route: list, current_system: Optional[str]) -> Optional[str]:
    """Return the next route system, skipping the current system if present."""
    for entry in route:
        system = entry.get("StarSystem")
        if system and system != current_system:
            return system

    if route:
        return route[0].get("StarSystem")

    return None


def _parse_and_apply(path: str, state: GameState) -> None:
    """Read NavRoute.json and push the next jump target into GameState."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("NavRoute.json read skipped: %s", exc)
        return

    route = data.get("Route", [])
    if not route:
        state.update(jump_target=None, jumps_remaining=None)
        return

    target = target_from_route(route, state.star_system)
    state.update(
        jump_target=target,
        jumps_remaining=len(route),
    )
    logger.debug("Nav route updated — target=%s jumps=%s", target, len(route))


class _NavRouteHandler(FileSystemEventHandler):
    def __init__(self, reader: "NavRouteReader") -> None:
        super().__init__()
        self._reader = reader

    def on_modified(self, event):
        if not event.is_directory and os.path.basename(event.src_path) == _NAV_ROUTE_FILE:
            self._reader.read_now()

    on_created = on_modified

    def on_deleted(self, event):
        if not event.is_directory and os.path.basename(event.src_path) == _NAV_ROUTE_FILE:
            self._reader.clear()


class NavRouteReader:
    """Watches the journal folder for NavRoute.json changes."""

    def __init__(self, journal_folder: str, state: GameState) -> None:
        self._folder = journal_folder
        self._state = state
        self._path = str(Path(journal_folder) / _NAV_ROUTE_FILE)
        self._observer: Optional[Observer] = None
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._last_mtime: Optional[float] = None

    def start(self) -> None:
        if not os.path.isdir(self._folder):
            logger.error("Journal folder not found: %s — NavRouteReader not started",
                         self._folder)
            return

        self._running = True
        self.read_now()
        self._last_mtime = self._mtime()

        handler = _NavRouteHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, self._folder, recursive=False)
        self._observer.start()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="NavRoutePoller",
            daemon=True,
        )
        self._poll_thread.start()
        logger.info("NavRouteReader watching %s", self._folder)

    def stop(self) -> None:
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=_POLL_INTERVAL + 1)
            self._poll_thread = None
        logger.info("NavRouteReader stopped")

    def read_now(self) -> None:
        _parse_and_apply(self._path, self._state)
        self._last_mtime = self._mtime()

    def clear(self) -> None:
        self._state.update(jump_target=None, jumps_remaining=None)
        self._last_mtime = None

    def _mtime(self) -> Optional[float]:
        try:
            return os.path.getmtime(self._path)
        except OSError:
            return None

    def _poll_loop(self) -> None:
        """Poll as a fallback for NavRoute.json replacement events."""
        while self._running:
            mtime = self._mtime()
            if mtime is None:
                if self._last_mtime is not None:
                    self.clear()
                time.sleep(_POLL_INTERVAL)
                continue

            if mtime != self._last_mtime:
                self.read_now()

            time.sleep(_POLL_INTERVAL)
