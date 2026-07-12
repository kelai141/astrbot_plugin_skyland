"""
基础设施 — 凭证缓存（可选 Redis 或内存）
"""
import time
from typing import Optional
from dataclasses import dataclass


@dataclass
class CachedCredential:
    """缓存的凭证"""
    value: str
    expires_at: float  # timestamp


class MemoryCredentialCache:
    """内存凭证缓存（默认实现）"""

    def __init__(self, default_ttl_seconds: int = 3600):
        self._cache: dict[str, CachedCredential] = {}
        self._default_ttl = default_ttl_seconds

    async def get(self, key: str) -> Optional[str]:
        cached = self._cache.get(key)
        if cached is None:
            return None
        if time.time() > cached.expires_at:
            del self._cache[key]
            return None
        return cached.value

    async def set(self, key: str, value: str, ttl_seconds: Optional[int] = None):
        ttl = ttl_seconds or self._default_ttl
        self._cache[key] = CachedCredential(
            value=value,
            expires_at=time.time() + ttl,
        )

    async def delete(self, key: str):
        self._cache.pop(key, None)

    async def clear(self):
        self._cache.clear()
