"""
森空岛安全模块 — 设备指纹(dId)生成与管理
"""
import hashlib
import json
import time
import os
from typing import Optional

from astrbot.api import logger

from infrastructure.persistence.credential_cache import MemoryCredentialCache


class DeviceFingerprintManager:
    """设备指纹管理器"""

    def __init__(self, cache_dir: str = "", cache: Optional[MemoryCredentialCache] = None):
        self._cache = cache or MemoryCredentialCache()
        self._cache_dir = cache_dir
        self._did: Optional[str] = None

    async def get_or_create(self) -> str:
        """获取或生成本地设备指纹"""
        if self._did:
            return self._did

        # 尝试从缓存读取
        cached = await self._cache.get("device_did")
        if cached:
            self._did = cached
            return cached

        # 尝试从文件读取
        did = self._load_from_file()
        if did:
            self._did = did
            await self._cache.set("device_did", did)
            return did

        # 生成新的设备指纹
        did = self._generate()
        self._did = did
        await self._cache.set("device_did", did)
        self._save_to_file(did)
        return did

    async def refresh(self) -> str:
        """强制刷新设备指纹"""
        self._did = None
        return await self.get_or_create()

    def _generate(self) -> str:
        """基于本地信息生成设备指纹"""
        raw = json.dumps({
            "ts": int(time.time()),
            "host": os.name,
            "pid": os.getpid(),
            "seed": os.urandom(8).hex(),
        }, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    def _load_from_file(self) -> Optional[str]:
        """从文件加载设备指纹"""
        if not self._cache_dir:
            return None
        did_file = os.path.join(self._cache_dir, "device_did.json")
        try:
            if os.path.exists(did_file):
                with open(did_file, "r") as f:
                    data = json.load(f)
                    return data.get("did")
        except Exception as e:
            logger.debug(f"读取设备指纹文件失败: {e}")
        return None

    def _save_to_file(self, did: str):
        """保存设备指纹到文件"""
        if not self._cache_dir:
            return
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            did_file = os.path.join(self._cache_dir, "device_did.json")
            with open(did_file, "w") as f:
                json.dump({"did": did, "created_at": int(time.time())}, f)
        except Exception as e:
            logger.debug(f"保存设备指纹文件失败: {e}")
