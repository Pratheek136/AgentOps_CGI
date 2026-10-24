"""Reads config/app.env once at startup."""
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "app.env"


def load_config(path: Path = CONFIG_PATH) -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg
