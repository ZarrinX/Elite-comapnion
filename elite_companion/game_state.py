"""GameState — single source of truth for all Elite: Dangerous data.

All reader threads (status_reader, journal) write into this object under the
write lock.  The serial sender reads from it without a lock; stale reads are
acceptable for a display use-case.
"""

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional


def _round_number(value, digits: int):
    """Round numeric values, returning None for unexpected journal shapes."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(value, digits)
    return None


@dataclass
class GameState:
    # ------------------------------------------------------------------ #
    # Lock — acquire for all writes                                        #
    # ------------------------------------------------------------------ #
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _on_change: Optional[Callable[[], None]] = field(default=None, repr=False)

    # ------------------------------------------------------------------ #
    # Location / navigation                                                #
    # ------------------------------------------------------------------ #
    star_system: Optional[str] = None        # Current star system
    body: Optional[str] = None               # Current body (planet/station)
    jump_target: Optional[str] = None        # FSD target system
    jumps_remaining: Optional[int] = None    # Remaining jumps in plotted route

    # ------------------------------------------------------------------ #
    # Ship identity                                                        #
    # ------------------------------------------------------------------ #
    ship: Optional[str] = None               # Ship type (e.g. "Asp Explorer")
    ship_name: Optional[str] = None          # Commander-given name
    ship_ident: Optional[str] = None         # Ship callsign

    # ------------------------------------------------------------------ #
    # Fuel                                                                 #
    # ------------------------------------------------------------------ #
    fuel: Optional[float] = None             # Main tank (tons)
    fuel_cap: Optional[float] = None         # Main tank capacity (tons)
    fuel_reservoir: Optional[float] = None   # Reserve tank (tons)

    # ------------------------------------------------------------------ #
    # Combat / shields                                                     #
    # ------------------------------------------------------------------ #
    shields: bool = True                     # Shields up
    hardpoints: bool = False                 # Hardpoints deployed
    hull: float = 1.0                        # 0.0–1.0
    under_attack: bool = False               # UnderAttack event active

    # ------------------------------------------------------------------ #
    # FSD state                                                            #
    # ------------------------------------------------------------------ #
    # Values: "ready" | "charging" | "cooldown" | "masslock" | "jumping"
    fsd: str = "ready"

    # ------------------------------------------------------------------ #
    # Pips [SYS, ENG, WEP] in half-pips (each 0–8, sum = 12)             #
    # ------------------------------------------------------------------ #
    pips: list = field(default_factory=lambda: [4, 4, 4])

    # ------------------------------------------------------------------ #
    # Status flags                                                         #
    # ------------------------------------------------------------------ #
    docked: bool = False
    landed: bool = False
    supercruise: bool = False
    scooping: bool = False
    low_fuel: bool = False
    overheating: bool = False
    in_danger: bool = False
    being_interdicted: bool = False

    # ------------------------------------------------------------------ #
    # Legal state                                                          #
    # ------------------------------------------------------------------ #
    legal: str = "Clean"

    # ------------------------------------------------------------------ #
    # Planet surface (only valid when on_planet is True)                  #
    # ------------------------------------------------------------------ #
    on_planet: bool = False
    lat: Optional[float] = None
    lon: Optional[float] = None
    alt: Optional[float] = None
    hdg: Optional[float] = None

    # ------------------------------------------------------------------ #
    # Station                                                              #
    # ------------------------------------------------------------------ #
    station_name: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Misc                                                                 #
    # ------------------------------------------------------------------ #
    cargo: Optional[float] = None
    credits: Optional[int] = None
    max_jump_range: Optional[float] = None

    # ------------------------------------------------------------------ #
    # Write helpers                                                        #
    # ------------------------------------------------------------------ #
    def set_change_callback(self, callback: Callable[[], None]) -> None:
        """Set a callback fired after any field changes."""
        self._on_change = callback

    def update(self, **kwargs) -> None:
        """Thread-safe bulk update of one or more fields."""
        changed = False
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key) and getattr(self, key) != value:
                    setattr(self, key, value)
                    changed = True

        if changed and self._on_change:
            self._on_change()

    # ------------------------------------------------------------------ #
    # Serialisation                                                        #
    # ------------------------------------------------------------------ #
    def to_payload(self) -> dict:
        """Return the JSON payload dict to send over serial.

        Fields with no value are always included as null so the ESP32
        receives a consistent schema on every packet.
        """
        return {
            "type": "status",
            "sys":        self.star_system,
            "tgt":        self.jump_target,
            "jumps":      self.jumps_remaining,
            "fuel":       _round_number(self.fuel, 2),
            "fuel_cap":   _round_number(self.fuel_cap, 2),
            "low_fuel":   self.low_fuel,
            "pips":       list(self.pips),
            "shields":    self.shields,
            "hardpoints": self.hardpoints,
            "fsd":        self.fsd,
            "legal":      self.legal,
            "attack":     self.under_attack,
            "lat":        _round_number(self.lat, 4),
            "lon":        _round_number(self.lon, 4),
            "alt":        _round_number(self.alt, 1),
            "hdg":        _round_number(self.hdg, 1),
            "on_planet":  self.on_planet,
            "ship":       self.ship,
            "hull":       _round_number(self.hull, 3),
        }
