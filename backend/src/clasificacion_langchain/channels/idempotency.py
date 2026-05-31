from __future__ import annotations

import time


class InMemoryIdempotencyStore:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, float] = {}

    def mark_if_new(self, key: str) -> bool:
        now = time.time()
        self._cleanup(now)

        expires_at = self._items.get(key)
        if expires_at and expires_at > now:
            return False

        self._items[key] = now + self.ttl_seconds
        return True

    def _cleanup(self, now: float) -> None:
        expired = [item_key for item_key, expires in self._items.items() if expires <= now]
        for item_key in expired:
            self._items.pop(item_key, None)


class RedisIdempotencyStore:
    def __init__(
        self,
        redis_url: str,
        key_prefix: str = "wa_dedup",
        ttl_seconds: int = 300,
    ) -> None:
        try:
            import redis
        except ImportError as exc:
            raise ImportError(
                "redis no esta instalado. Corre pip install -r requirements.txt"
            ) from exc

        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds

    def mark_if_new(self, key: str) -> bool:
        namespaced = f"{self.key_prefix}:{key}"
        created = self.client.set(namespaced, "1", nx=True, ex=self.ttl_seconds)
        return bool(created)
