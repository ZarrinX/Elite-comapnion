"""Config load/save for Elite Companion.

Config is persisted to %APPDATA%\\EliteCompanion\\config.json.
On first run the journal folder is auto-detected from the default
Elite Dangerous saved games location.
"""

import json
import os
from pathlib import Path

_APP_NAME = "EliteCompanion"
_CONFIG_FILE = "config.json"

_DEFAULT_JOURNAL_FOLDER = str(
    Path(os.environ.get("USERPROFILE", "~"))
    / "Saved Games"
    / "Frontier Developments"
    / "Elite Dangerous"
)

DEFAULTS: dict = {
    "serial_port": None,
    "baud_rate": 115200,
    "journal_folder": None,
    "send_interval_ms": 500,
}


def _config_path() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home())
    return Path(appdata) / _APP_NAME / _CONFIG_FILE


def _detect_journal_folder() -> str | None:
    """Return the default journal folder if it exists, else None."""
    candidate = Path(_DEFAULT_JOURNAL_FOLDER)
    return str(candidate) if candidate.is_dir() else None


def load() -> dict:
    """Load config from disk, creating it with defaults if absent."""
    path = _config_path()

    if not path.exists():
        cfg = dict(DEFAULTS)
        cfg["journal_folder"] = _detect_journal_folder()
        save(cfg)
        return cfg

    with open(path, encoding="utf-8") as f:
        on_disk = json.load(f)

    # Fill in any keys added in newer versions
    cfg = dict(DEFAULTS)
    cfg.update(on_disk)

    # Auto-detect journal folder if not yet set
    if not cfg.get("journal_folder"):
        cfg["journal_folder"] = _detect_journal_folder()

    return cfg


def save(cfg: dict) -> None:
    """Persist config to disk."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
