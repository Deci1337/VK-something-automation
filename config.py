import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULTS = {
    "group_url": "",
    "profile_path": "",
    "count": 20,
    "delay_min": 8,
    "delay_max": 20,
    "admin_hold_seconds": 15,
    "chrome_path": "",
}


def load() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**DEFAULTS, **data}
    return dict(DEFAULTS)


def save(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
