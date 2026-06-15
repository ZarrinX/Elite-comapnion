"""TrayApp — system tray icon and tkinter config window.

The tray icon is drawn programmatically with Pillow (no external asset needed).
The config window is a tkinter dialog opened on demand from the tray menu.

Thread model:
  - pystray runs via run_detached() in its own internal thread.
  - Each config window opens in its own daemon thread with its own Tk() instance.
  - Status polling inside the config window uses tkinter's after() scheduler.
"""

import logging
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw

from .serial_sender import list_ports

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Icon drawing                                                         #
# ------------------------------------------------------------------ #

def _make_tray_image(size: int = 64) -> Image.Image:
    """Draw a simple amber diamond icon — Elite's colour scheme."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy, pad = size // 2, size // 2, 4
    diamond = [(cx, pad), (size - pad, cy), (cx, size - pad), (pad, cy)]
    draw.polygon(diamond, fill=(255, 140, 0, 255))
    draw.line(diamond + [diamond[0]], fill=(255, 210, 60, 255), width=2)
    return img


# ------------------------------------------------------------------ #
# Config window                                                        #
# ------------------------------------------------------------------ #

class _ConfigWindow:
    """Tkinter config/status window.  Runs in its own thread."""

    def __init__(
        self,
        config: dict,
        on_save: Callable[[dict], None],
        get_status: Callable[[], tuple[bool, bool]],
    ) -> None:
        self._config = config
        self._on_save = on_save
        self._get_status = get_status   # returns (game_running, serial_connected)

    def run(self) -> None:
        """Build and run the window (blocks until closed)."""
        root = tk.Tk()
        root.title("Elite Companion — Config")
        root.resizable(False, False)
        root.columnconfigure(1, weight=1)

        pad = {"padx": 8, "pady": 4}

        # ── Serial port ──────────────────────────────────────────────
        tk.Label(root, text="Serial Port:").grid(row=0, column=0, sticky="e", **pad)
        port_var = tk.StringVar(value=self._config.get("serial_port") or "")
        port_combo = ttk.Combobox(root, textvariable=port_var, width=18)
        port_combo.grid(row=0, column=1, sticky="w", **pad)

        def refresh_ports():
            ports = list_ports()
            port_combo["values"] = ports
            if port_var.get() not in ports and ports:
                port_var.set(ports[0])

        refresh_ports()
        tk.Button(root, text="↺", width=2, command=refresh_ports).grid(
            row=0, column=2, padx=(0, 8)
        )

        # ── Baud rate ────────────────────────────────────────────────
        tk.Label(root, text="Baud Rate:").grid(row=1, column=0, sticky="e", **pad)
        baud_var = tk.StringVar(value=str(self._config.get("baud_rate", 115200)))
        baud_combo = ttk.Combobox(
            root,
            textvariable=baud_var,
            values=["9600", "19200", "38400", "57600", "115200", "230400"],
            width=18,
        )
        baud_combo.grid(row=1, column=1, sticky="w", **pad)

        # ── Journal folder ───────────────────────────────────────────
        tk.Label(root, text="Journal Folder:").grid(row=2, column=0, sticky="e", **pad)
        folder_var = tk.StringVar(value=self._config.get("journal_folder") or "")
        folder_entry = tk.Entry(root, textvariable=folder_var, width=40)
        folder_entry.grid(row=2, column=1, sticky="ew", **pad)

        def browse_folder():
            chosen = filedialog.askdirectory(
                title="Select Elite Dangerous Saved Games folder",
                initialdir=folder_var.get() or "/",
            )
            if chosen:
                folder_var.set(chosen)

        tk.Button(root, text="Browse…", command=browse_folder).grid(
            row=2, column=2, padx=(0, 8)
        )

        # ── Send interval ────────────────────────────────────────────
        tk.Label(root, text="Send Interval (ms):").grid(row=3, column=0, sticky="e", **pad)
        interval_var = tk.StringVar(value=str(self._config.get("send_interval_ms", 500)))
        tk.Entry(root, textvariable=interval_var, width=8).grid(
            row=3, column=1, sticky="w", **pad
        )

        # ── Status indicators ────────────────────────────────────────
        tk.ttk.Separator(root, orient="horizontal").grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=6
        )

        game_label = tk.Label(root, text="Game: …", anchor="w")
        game_label.grid(row=5, column=0, columnspan=2, sticky="w", padx=8)

        serial_label = tk.Label(root, text="Serial: …", anchor="w")
        serial_label.grid(row=6, column=0, columnspan=2, sticky="w", padx=8)

        def poll_status():
            try:
                game_on, ser_on = self._get_status()
                game_label.config(
                    text=f"Game: {'Running ✓' if game_on else 'Not detected'}",
                    fg="green" if game_on else "gray",
                )
                serial_label.config(
                    text=f"Serial: {'Connected ✓' if ser_on else 'Disconnected'}",
                    fg="green" if ser_on else "red",
                )
            except Exception:
                pass
            root.after(1000, poll_status)

        poll_status()

        # ── Save button ──────────────────────────────────────────────
        tk.ttk.Separator(root, orient="horizontal").grid(
            row=7, column=0, columnspan=3, sticky="ew", pady=6
        )

        def save():
            try:
                baud = int(baud_var.get())
                interval = int(interval_var.get())
            except ValueError:
                tk.messagebox.showerror(
                    "Invalid input", "Baud rate and interval must be integers."
                )
                return

            new_cfg = dict(self._config)
            new_cfg["serial_port"]     = port_var.get() or None
            new_cfg["baud_rate"]       = baud
            new_cfg["journal_folder"]  = folder_var.get() or None
            new_cfg["send_interval_ms"] = interval
            self._on_save(new_cfg)
            root.destroy()

        btn_frame = tk.Frame(root)
        btn_frame.grid(row=8, column=0, columnspan=3, pady=(0, 8))
        tk.Button(btn_frame, text="Save", width=10, command=save).pack(
            side="left", padx=4
        )
        tk.Button(btn_frame, text="Cancel", width=10, command=root.destroy).pack(
            side="left", padx=4
        )

        root.mainloop()


# ------------------------------------------------------------------ #
# TrayApp                                                              #
# ------------------------------------------------------------------ #

class TrayApp:
    """Manages the system tray icon and config window."""

    def __init__(
        self,
        config: dict,
        on_config_save: Callable[[dict], None],
        on_quit: Callable[[], None],
        get_status: Callable[[], tuple[bool, bool]],
    ) -> None:
        """
        Args:
            config:          Live config dict (will be mutated on save).
            on_config_save:  Called with the new config dict after user saves.
            on_quit:         Called when user selects Quit from the tray menu.
            get_status:      Returns (game_running, serial_connected).
        """
        self._config = config
        self._on_config_save = on_config_save
        self._on_quit = on_quit
        self._get_status = get_status
        self._icon: Optional[pystray.Icon] = None
        self._game_running = False
        self._serial_connected = False

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start the tray icon (non-blocking)."""
        self._icon = pystray.Icon(
            name="EliteCompanion",
            icon=_make_tray_image(),
            title=self._tooltip(),
            menu=self._build_menu(),
        )
        self._icon.run_detached()
        logger.info("TrayApp started")

    def stop(self) -> None:
        if self._icon:
            self._icon.stop()
            self._icon = None
        logger.info("TrayApp stopped")

    def update_status(self, game_running: bool, serial_connected: bool) -> None:
        """Refresh the tooltip and menu with current connection state."""
        self._game_running = game_running
        self._serial_connected = serial_connected
        if self._icon:
            self._icon.title = self._tooltip()
            self._icon.menu = self._build_menu()

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _tooltip(self) -> str:
        game   = "Running" if self._game_running   else "Not detected"
        serial = "Connected" if self._serial_connected else "Disconnected"
        return f"Elite Companion\nGame: {game}\nSerial: {serial}"

    def _build_menu(self) -> pystray.Menu:
        game_text   = ("Game: Running ✓"   if self._game_running   else "Game: Not detected")
        serial_text = ("Serial: Connected ✓" if self._serial_connected else "Serial: Disconnected")
        return pystray.Menu(
            pystray.MenuItem(game_text,   None, enabled=False),
            pystray.MenuItem(serial_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Config", self._open_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    def _open_config(self, icon=None, item=None) -> None:
        threading.Thread(target=self._run_config_window, daemon=True).start()

    def _run_config_window(self) -> None:
        try:
            win = _ConfigWindow(
                config=self._config,
                on_save=self._handle_save,
                get_status=self._get_status,
            )
            win.run()
        except Exception:
            logger.exception("Error in config window")

    def _handle_save(self, new_cfg: dict) -> None:
        self._config.update(new_cfg)
        try:
            self._on_config_save(new_cfg)
        except Exception:
            logger.exception("Error in on_config_save callback")

    def _quit(self, icon=None, item=None) -> None:
        self.stop()
        try:
            self._on_quit()
        except Exception:
            logger.exception("Error in on_quit callback")
