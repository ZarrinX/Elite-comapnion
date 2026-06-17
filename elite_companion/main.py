"""Elite Companion — entry point.

Starts all threads, wires game-detection events to file watchers,
and handles graceful shutdown on SIGINT or tray Quit.

Run with:
    py -m elite_companion
"""

import logging
import os
import signal
import sys
import threading

from . import config as cfg_module
from .game_state import GameState
from .journal import JournalReader
from .nav_route_reader import NavRouteReader
from .serial_sender import SerialSender
from .status_reader import StatusReader
from .tray import TrayApp
from .watcher import ProcessWatcher

# ------------------------------------------------------------------ #
# Logging                                                              #
# ------------------------------------------------------------------ #

def _setup_logging() -> None:
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    log_dir = os.path.join(appdata, "EliteCompanion")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "app.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Application                                                          #
# ------------------------------------------------------------------ #

class App:
    def __init__(self) -> None:
        self._config = cfg_module.load()
        self._state = GameState()
        self._shutdown_event = threading.Event()

        # File-watcher components (created/destroyed per game session)
        self._journal_reader: JournalReader | None = None
        self._nav_route_reader: NavRouteReader | None = None
        self._status_reader: StatusReader | None = None

        # Long-lived components
        self._serial_sender = SerialSender(self._state, self._config)
        self._process_watcher = ProcessWatcher(
            on_game_start=self._on_game_start,
            on_game_stop=self._on_game_stop,
        )
        self._tray = TrayApp(
            config=self._config,
            on_config_save=self._on_config_save,
            on_quit=self._shutdown,
            get_status=self._get_status,
        )

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        logger.info("Elite Companion starting")

        self._serial_sender.start()
        self._process_watcher.start()
        self._tray.start()

        # Kick off a status-update loop in a daemon thread so the tray
        # tooltip stays fresh even when the config window isn't open
        threading.Thread(
            target=self._status_poll_loop,
            name="StatusPoller",
            daemon=True,
        ).start()

        # Block main thread until shutdown is requested
        self._shutdown_event.wait()

        logger.info("Elite Companion shutting down")
        self._stop_file_watchers()
        self._serial_sender.stop()
        self._process_watcher.stop()
        self._tray.stop()
        logger.info("Elite Companion stopped")

    def _shutdown(self) -> None:
        self._shutdown_event.set()

    # ------------------------------------------------------------------ #
    # Game detection callbacks                                            #
    # ------------------------------------------------------------------ #

    def _on_game_start(self) -> None:
        self._serial_sender.set_display_enabled(True)
        folder = self._config.get("journal_folder")
        if not folder:
            logger.warning("Game detected but journal_folder is not configured")
            self._tray.update_status(
                game_running=True,
                serial_connected=self._serial_sender.connected,
            )
            return

        self._journal_reader = JournalReader(folder, self._state)
        self._nav_route_reader = NavRouteReader(folder, self._state)
        self._status_reader  = StatusReader(folder, self._state)

        self._journal_reader.start()
        self._nav_route_reader.start()
        self._status_reader.start()

        self._tray.update_status(
            game_running=True,
            serial_connected=self._serial_sender.connected,
        )
        logger.info("File watchers started (folder: %s)", folder)

    def _on_game_stop(self) -> None:
        self._serial_sender.set_display_enabled(False)
        self._stop_file_watchers()
        self._tray.update_status(
            game_running=False,
            serial_connected=self._serial_sender.connected,
        )

    def _stop_file_watchers(self) -> None:
        if self._journal_reader:
            self._journal_reader.stop()
            self._journal_reader = None
        if self._nav_route_reader:
            self._nav_route_reader.stop()
            self._nav_route_reader = None
        if self._status_reader:
            self._status_reader.stop()
            self._status_reader = None

    # ------------------------------------------------------------------ #
    # Config save                                                          #
    # ------------------------------------------------------------------ #

    def _on_config_save(self, new_cfg: dict) -> None:
        self._config.update(new_cfg)
        cfg_module.save(self._config)
        # Apply new serial settings immediately
        self._serial_sender.stop()
        self._serial_sender = SerialSender(self._state, self._config)
        self._serial_sender.start()
        logger.info("Config saved and applied: port=%s baud=%s",
                    self._config.get("serial_port"),
                    self._config.get("baud_rate"))

    # ------------------------------------------------------------------ #
    # Status helpers                                                       #
    # ------------------------------------------------------------------ #

    def _get_status(self) -> tuple[bool, bool]:
        return self._process_watcher.game_running, self._serial_sender.connected

    def _status_poll_loop(self) -> None:
        """Refresh the tray tooltip every 5 seconds."""
        while not self._shutdown_event.is_set():
            game, serial = self._get_status()
            self._tray.update_status(game_running=game, serial_connected=serial)
            self._shutdown_event.wait(timeout=5)


# ------------------------------------------------------------------ #
# Entry point                                                          #
# ------------------------------------------------------------------ #

def main() -> None:
    _setup_logging()

    app = App()

    # Handle Ctrl-C gracefully
    def _sigint_handler(sig, frame):
        logger.info("SIGINT received — shutting down")
        app._shutdown()

    signal.signal(signal.SIGINT, _sigint_handler)

    app.run()


if __name__ == "__main__":
    main()
