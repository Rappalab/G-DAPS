"""G-DAPS runtime configuration loaded from .env for non-Docker/server deployment."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
# Loads .env when present. Existing shell/systemd env values still take precedence.
load_dotenv(ENV_PATH, override=False)


def env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def env_list(name: str, defaults: List[str] | tuple[str, ...]) -> List[str]:
    raw = os.getenv(name, "").strip()
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return list(defaults)


def data_path(filename: str = "gdaps.db") -> str:
    data_dir = env_str("GDAPS_DATA_DIR", str(PROJECT_ROOT / "data"))
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    return str(Path(data_dir) / filename)
