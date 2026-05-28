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


def _aliases(account_id: str) -> list:
    """Возвращает все варианты одного ID для проверки.

    VK может показывать одного пользователя как 'id123' или как vanity-алиас.
    Храним оба варианта чтобы не пропустить уже обработанного.
    """
    s = str(account_id)
    variants = [s]
    # id123456 → также проверяем '123456'
    if s.startswith("id") and s[2:].isdigit():
        variants.append(s[2:])
    # 123456 → также проверяем 'id123456'
    elif s.isdigit():
        variants.append("id" + s)
    return variants


def _cache_key(account_id: str, group_url: str) -> str:
    """Составной ключ id::group — позволяет хранить разные группы независимо."""
    if group_url:
        return f"{account_id}::{group_url}"
    return account_id


def is_processed(account_id: str, group_url: str = "") -> bool:
    cache = _load()
    for v in _aliases(account_id):
        key = _cache_key(v, group_url)
        if key in cache:
            return True
        # Обратная совместимость: старые записи без суффикса группы
        if not group_url and v in cache:
            return True
    return False


def mark_processed(account_id: str, group_url: str = "") -> None:
    cache = _load()
    entry = {
        "date":  datetime.now().isoformat(timespec="seconds"),
        "group": group_url,
    }
    for v in _aliases(account_id):
        cache[_cache_key(v, group_url)] = entry
    _flush()


def get_count() -> int:
    return len(_load())


def get_all() -> dict:
    return dict(_load())


def clear_all() -> None:
    global _cache
    _cache = {}
    _flush()


# ─── Список игнорируемых ID ───────────────────────────────────────────────────

IGNORE_PATH = os.path.join(os.path.dirname(__file__), "ignore.json")
_ignore_cache: Optional[set] = None


def _load_ignore() -> set:
    global _ignore_cache
    if _ignore_cache is None:
        if os.path.exists(IGNORE_PATH):
            try:
                with open(IGNORE_PATH, "r", encoding="utf-8") as f:
                    _ignore_cache = set(json.load(f).get("ignore", []))
            except Exception:
                _ignore_cache = set()
        else:
            _ignore_cache = set()
    return _ignore_cache


def _flush_ignore() -> None:
    with open(IGNORE_PATH, "w", encoding="utf-8") as f:
        json.dump({"ignore": sorted(_ignore_cache)}, f, ensure_ascii=False, indent=2)


def is_ignored(account_id: str) -> bool:
    return str(account_id) in _load_ignore()


def add_ignore(account_id: str) -> None:
    ids = _load_ignore()
    ids.add(str(account_id).strip())
    _flush_ignore()


def remove_ignore(account_id: str) -> None:
    ids = _load_ignore()
    ids.discard(str(account_id))
    _flush_ignore()


def get_all_ignored() -> list:
    return sorted(_load_ignore())


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
