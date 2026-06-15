"""Watcher — monitors for the Elite: Dangerous process and manages file watchers.

Polls for EliteDangerous64.exe every 5 seconds using psutil.
When the process is detected, starts the journal and status file watchers.
When the process exits, stops them.
"""

import logging
import threading
import time
from typing import Callable, Optional

import psutil

logger = logging.getLogger(__name__)

_PROCESS_NAME = "EliteDangerous64.exe"
_POLL_INTERVAL = 5  # seconds


class ProcessWatcher:
    """Polls for the Elite: Dangerous process and fires callbacks on start/stop."""

    def __init__(
        self,
        on_game_start: Callable[[], None],
        on_game_stop: Callable[[], None],
    ) -> None:
        self._on_start = on_game_start
        self._on_stop = on_game_stop
        self._running = False
        self._game_running = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start the process poll loop in a daemon thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="ProcessWatcher",
            daemon=True,
        )
        self._thread.start()
        logger.info("ProcessWatcher started (polling for %s every %ds)",
                    _PROCESS_NAME, _POLL_INTERVAL)

    def stop(self) -> None:
        """Signal the poll loop to stop and wait for the thread to exit."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=_POLL_INTERVAL + 1)

    @property
    def game_running(self) -> bool:
        return self._game_running

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _poll_loop(self) -> None:
        while self._running:
            try:
                detected = self._is_game_running()
            except Exception:
                logger.exception("Error checking for game process — will retry")
                time.sleep(_POLL_INTERVAL)
                continue

            if detected and not self._game_running:
                self._game_running = True
                logger.info("Elite: Dangerous detected — activating watchers")
                try:
                    self._on_start()
                except Exception:
                    logger.exception("Error in on_game_start callback")

            elif not detected and self._game_running:
                self._game_running = False
                logger.info("Elite: Dangerous exited — deactivating watchers")
                try:
                    self._on_stop()
                except Exception:
                    logger.exception("Error in on_game_stop callback")

            time.sleep(_POLL_INTERVAL)

    @staticmethod
    def _is_game_running() -> bool:
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] == _PROCESS_NAME:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False
