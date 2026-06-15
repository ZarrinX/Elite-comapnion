"""SerialSender — manages the USB serial connection to the ESP32.

Sends the current GameState payload as newline-terminated JSON at a
configurable interval.  Also exposes trigger_send() for immediate sends
on state change.

Port loss (USB unplug) is handled gracefully: the error is logged, the port
is marked disconnected, and reconnection is retried every 5 seconds.
Exceptions never propagate to the watcher threads.
"""

import json
import logging
import threading
import time
from typing import Optional

import serial
import serial.tools.list_ports

from .game_state import GameState

logger = logging.getLogger(__name__)

_RETRY_INTERVAL = 5.0   # seconds between reconnect attempts


class SerialSender:
    """Periodically sends GameState JSON over a USB serial port."""

    def __init__(self, state: GameState, config: dict) -> None:
        self._state = state
        self._config = config
        self._port: Optional[serial.Serial] = None
        self._running = False
        self._send_event = threading.Event()   # set to trigger an immediate send
        self._thread: Optional[threading.Thread] = None
        self._connected = False
        self._last_display_values: Optional[tuple] = None
        self._last_send_at = 0.0
        self._sequence = 0
        self._last_heartbeat_log = 0

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def connected(self) -> bool:
        return self._connected

    def trigger_send(self) -> None:
        """Request an immediate send on the next loop iteration."""
        self._send_event.set()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name="SerialSender",
            daemon=True,
        )
        self._thread.start()
        logger.info("SerialSender started")

    def stop(self) -> None:
        self._running = False
        self._send_event.set()   # unblock any wait
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=_RETRY_INTERVAL + 1)
        self._close_port()
        logger.info("SerialSender stopped")

    # ------------------------------------------------------------------ #
    # Internal loop                                                        #
    # ------------------------------------------------------------------ #

    def _run(self) -> None:
        while self._running:
            if not self._connected:
                self._try_connect()
                if not self._connected:
                    # Wait before retrying, but wake immediately on stop
                    self._send_event.wait(timeout=_RETRY_INTERVAL)
                    self._send_event.clear()
                    continue

            interval_s = self._config.get("send_interval_ms", 500) / 1000.0
            # Wait for interval or an immediate-send trigger
            self._send_event.wait(timeout=interval_s)
            self._send_event.clear()

            if not self._running:
                break

            send_at = self._last_send_at + interval_s
            while self._running:
                remaining = send_at - time.monotonic()
                if remaining <= 0:
                    break
                self._send_event.wait(timeout=remaining)
                self._send_event.clear()

            if not self._running:
                break

            self._send_payload()

    def _try_connect(self) -> None:
        port_name = self._config.get("serial_port")
        baud = self._config.get("baud_rate", 115200)

        if not port_name:
            return   # No port configured yet

        try:
            self._port = serial.Serial(
                port=port_name,
                baudrate=baud,
                timeout=1,
                write_timeout=1,
            )
            self._connected = True
            logger.info("Serial connected: %s @ %d baud", port_name, baud)
        except serial.SerialException as exc:
            logger.warning("Serial connect failed (%s): %s", port_name, exc)
            self._port = None
            self._connected = False

    def _send_payload(self) -> None:
        try:
            payload = self._display_payload()
            line = json.dumps(payload, separators=(",", ":")) + "\n"
            self._port.write(line.encode("utf-8"))
            self._drain_device_messages()
            self._last_send_at = time.monotonic()
            display_values = (payload.get("ship"), payload.get("sys"), payload.get("tgt"))
            if display_values != self._last_display_values:
                self._last_display_values = display_values
                logger.info(
                    "Serial payload display fields: ship=%r sys=%r tgt=%r",
                    display_values[0],
                    display_values[1],
                    display_values[2],
                )
            if payload["seq"] - self._last_heartbeat_log >= 20:
                self._last_heartbeat_log = payload["seq"]
                logger.info("Serial heartbeat: seq=%s bytes=%s",
                            payload["seq"], len(line))
            logger.debug("Sent %d bytes", len(line))
        except (serial.SerialException, OSError) as exc:
            logger.error("Serial write failed: %s — will retry in %ds",
                         exc, _RETRY_INTERVAL)
            self._close_port()
            self._connected = False
        except Exception as exc:
            # Catch-all: never let a send error crash the thread
            logger.exception("Unexpected error in _send_payload: %s", exc)

    def _drain_device_messages(self) -> None:
        """Read any diagnostic lines emitted by the ESP32 firmware."""
        if not self._port:
            return

        waiting = self._port.in_waiting
        if waiting <= 0:
            return

        data = self._port.read(min(waiting, 512))
        for line in data.decode("utf-8", errors="replace").splitlines():
            logger.info("ESP32: %s", line)

    def _display_payload(self) -> dict:
        """Return the compact payload needed by the current OLED firmware."""
        self._sequence += 1
        return {
            "type": "status",
            "seq": self._sequence,
            "ship": self._state.ship,
            "sys": self._state.star_system,
            "tgt": self._state.jump_target,
        }

    def _close_port(self) -> None:
        if self._port:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None


# ------------------------------------------------------------------ #
# Helper: enumerate available COM ports                               #
# ------------------------------------------------------------------ #

def list_ports() -> list[str]:
    """Return a sorted list of available serial port names."""
    return sorted(p.device for p in serial.tools.list_ports.comports())
