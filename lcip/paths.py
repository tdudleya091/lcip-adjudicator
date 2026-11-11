"""Where bundled resources live and where user data is saved (Linux and Windows)."""
import os
import sys
from pathlib import Path


def resource_dir() -> Path:
    """Project root, or PyInstaller's unpack folder when running as a built executable."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Per-user save folder: %APPDATA%\\LCIP on Windows, ~/.local/share/lcip elsewhere."""
    override = os.environ.get("LCIP_DATA_DIR")
    if override:
        path = Path(override)
    elif os.name == "nt":
        path = Path(os.environ.get("APPDATA", Path.home())) / "LCIP"
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "lcip"
    path.mkdir(parents=True, exist_ok=True)
    return path
