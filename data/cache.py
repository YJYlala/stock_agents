"""File-based cache with TTL."""

import hashlib
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class DataCache:
    """Simple file-based JSON cache with TTL."""

    def __init__(self, cache_dir: Path, ttl_seconds: int = 900, enabled: bool = True):
        self.cache_dir = cache_dir
        self.ttl = ttl_seconds
        self.enabled = enabled
        if enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key_path(self, key: str) -> Path:
        hashed = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{hashed}.json"

    def get(self, key: str) -> dict | list | None:
        if not self.enabled:
            return None
        path = self._key_path(key)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if time.time() - entry.get("ts", 0) > self.ttl:
                path.unlink(missing_ok=True)
                return None
            return entry.get("data")
        except Exception:
            return None

    def set(self, key: str, data: dict | list) -> None:
        if not self.enabled:
            return
        path = self._key_path(key)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "data": data}, f, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning("Cache write failed for %s: %s", key, e)
