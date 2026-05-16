"""Хранение обработанных ID аккаунтов (in-memory cache + write-through)."""
import json
import os
from datetime import datetime
from typing import Optional

STORAGE_PATH = os.path.join(os.path.dirname(__file__), "processed.json")

# In-memory кэш: {uid: {...}} — загружается один раз при первом обращении
_cache: Optional[dict] = None


def _load() -> dict:
    global _cache
    if _cache is None:
        if os.path.exists(STORAGE_PATH):
            try:
                with open(STORAGE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                _cache = data.get("processed", {})
            except Exception:
                _cache = {}
        else:
            _cache = {}
    return _cache


def _flush() -> None:
    with open(STORAGE_PATH, "w", encoding="utf-8") as f:
        json.dump({"processed": _cache}, f, ensure_ascii=False, indent=2)


def is_processed(account_id: str) -> bool:
    return str(account_id) in _load()


def mark_processed(account_id: str, group_url: str = "") -> None:
    cache = _load()
    cache[str(account_id)] = {
        "date":  datetime.now().isoformat(timespec="seconds"),
        "group": group_url,
    }
    _flush()


def get_count() -> int:
    return len(_load())


def get_all() -> dict:
    return dict(_load())


def clear_all() -> None:
    global _cache
    _cache = {}
    _flush()


# ─── Счётчик пропуска (legacy, оставлен для совместимости) ───────────────────

COUNTER_PATH = os.path.join(os.path.dirname(__file__), "skip_counter.json")


def get_skip_count() -> int:
    if os.path.exists(COUNTER_PATH):
        try:
            with open(COUNTER_PATH, "r", encoding="utf-8") as f:
                return int(json.load(f).get("skip", 0))
        except Exception:
            pass
    return 0


def set_skip_count(n: int) -> None:
    with open(COUNTER_PATH, "w", encoding="utf-8") as f:
        json.dump({"skip": n}, f)


def reset_skip_count() -> None:
    set_skip_count(0)
