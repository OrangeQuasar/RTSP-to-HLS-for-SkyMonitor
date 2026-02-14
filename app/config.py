from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE_DIR / "config.json"

_lock = Lock()


def load_config() -> Dict[str, Any]:
    with _lock:
        if not CONFIG_PATH.exists():
            raise FileNotFoundError(f"Missing config: {CONFIG_PATH}")
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config: Dict[str, Any]) -> None:
    with _lock:
        CONFIG_PATH.write_text(
            json.dumps(config, indent=2, ensure_ascii=True), encoding="utf-8"
        )


def ensure_hls_root(config: Dict[str, Any]) -> Path:
    hls_root = Path(config.get("hls_root") or "hls")
    if not hls_root.is_absolute():
        hls_root = BASE_DIR / hls_root
    hls_root.mkdir(parents=True, exist_ok=True)
    return hls_root
