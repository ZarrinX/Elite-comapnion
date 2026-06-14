"""GameState — single source of truth for all Elite: Dangerous data.

All reader threads (status_reader, journal) write into this object under the
write lock.  The serial sender reads from it without a lock; stale reads are
acceptable for a display use-case.
"""

import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GameState:
    # ------------------------------------------------------------------ #
    # Lock — acquire for all writes                                        #
    # ------------------------------------------------------------------ #
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

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
    def update(self, **kwargs) -> None:
        """Thread-safe bulk update of one or more fields."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)

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
            "fuel":       round(self.fuel, 2) if self.fuel is not None else None,
            "fuel_cap":   round(self.fuel_cap, 2) if self.fuel_cap is not None else None,
            "low_fuel":   self.low_fuel,
            "pips":       list(self.pips),
            "shields":    self.shields,
            "hardpoints": self.hardpoints,
            "fsd":        self.fsd,
            "legal":      self.legal,
            "attack":     self.under_attack,
            "lat":        round(self.lat, 4) if self.lat is not None else None,
            "lon":        round(self.lon, 4) if self.lon is not None else None,
            "alt":        round(self.alt, 1) if self.alt is not None else None,
            "hdg":        round(self.hdg, 1) if self.hdg is not None else None,
            "on_planet":  self.on_planet,
            "ship":       self.ship,
            "hull":       round(self.hull, 3),
        }
