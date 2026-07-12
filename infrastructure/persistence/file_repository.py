"""
基础设施 — 文件仓储实现
"""
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional
from uuid import uuid4

from astrbot.api import logger

from domain.enums import (
    CredentialType, BindingStatus, GamePlatform, NotificationPolicy, SignStatus,
)
from domain.models import UserBinding, UserCredential, SignRecord, DidRecord
from domain.ports import UserBindingRepository, SignRecordRepository


class FileUserBindingRepository(UserBindingRepository):
    """基于 JSON 文件的用户绑定仓储"""

    def __init__(self, data_dir: str):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._bindings_file = self._data_dir / "bindings.json"
        self._cache: dict[str, UserBinding] = {}  # key: f"{user_id}:{platform}"
        self._loaded = False

    def _key(self, user_id: str, platform: str) -> str:
        return f"{user_id}:{platform}"

    def _load(self):
        if self._loaded:
            return
        self._cache.clear()
        if self._bindings_file.exists():
            try:
                raw = json.loads(self._bindings_file.read_text(encoding="utf-8"))
                for item in raw:
                    binding = self._dict_to_binding(item)
                    if binding:
                        k = self._key(binding.user_id, binding.platform)
                        self._cache[k] = binding
            except Exception as e:
                logger.error(f"[仓储] 加载 bindings 失败: {e}")
        self._loaded = True

    def _save(self):
        raw = [self._binding_to_dict(b) for b in self._cache.values()]
        self._bindings_file.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _binding_to_dict(b: UserBinding) -> dict:
        return {
            "id": b.id or str(uuid4()),
            "user_id": b.user_id,
            "platform": b.platform,
            "game": b.game.value if isinstance(b.game, GamePlatform) else b.game,
            "sign_time": b.sign_time,
            "notification_policy": b.notification_policy.value if isinstance(b.notification_policy, NotificationPolicy) else b.notification_policy,
            "status": b.status.value if isinstance(b.status, BindingStatus) else b.status,
            "bound_at": b.bound_at.isoformat() if b.bound_at else None,
            "last_sign_at": b.last_sign_at.isoformat() if b.last_sign_at else None,
            "consecutive_days": b.consecutive_days,
            "total_signs": b.total_signs,
            "credential": {
                "type": b.credential.type.value if isinstance(b.credential.type, CredentialType) else b.credential.type,
                "value": b.credential.value,
                "hypergryph_token": b.credential.hypergryph_token,
                "did": b.credential.did,
                "created_at": b.credential.created_at.isoformat() if b.credential.created_at else None,
                "expires_at": b.credential.expires_at.isoformat() if b.credential.expires_at else None,
            },
        }

    @staticmethod
    def _dict_to_binding(d: dict) -> Optional[UserBinding]:
        try:
            cred = d.get("credential", {})
            credential = UserCredential(
                type=CredentialType(cred.get("type", "token")),
                value=cred.get("value", ""),
                hypergryph_token=cred.get("hypergryph_token"),
                did=cred.get("did"),
                created_at=_parse_dt(cred.get("created_at")),
                expires_at=_parse_dt(cred.get("expires_at")),
            )
            return UserBinding(
                id=d.get("id"),
                user_id=d["user_id"],
                platform=d.get("platform", "aiocqhttp"),
                credential=credential,
                game=GamePlatform(d.get("game", "arknights")),
                sign_time=d.get("sign_time", "09:05"),
                notification_policy=NotificationPolicy(d.get("notification_policy", "all")),
                status=BindingStatus(d.get("status", "active")),
                bound_at=_parse_dt(d.get("bound_at")),
                last_sign_at=_parse_dt(d.get("last_sign_at")),
                consecutive_days=d.get("consecutive_days", 0),
                total_signs=d.get("total_signs", 0),
            )
        except Exception as e:
            logger.error(f"[仓储] 转换 binding 失败: {e}")
            return None

    async def find_by_user_id(self, user_id: str, platform: str) -> Optional[UserBinding]:
        self._load()
        return self._cache.get(self._key(user_id, platform))

    async def save(self, binding: UserBinding) -> UserBinding:
        self._load()
        if not binding.id:
            binding.id = str(uuid4())
        if not binding.bound_at:
            binding.bound_at = datetime.now().astimezone()
        k = self._key(binding.user_id, binding.platform)
        self._cache[k] = binding
        self._save()
        return binding

    async def delete(self, user_id: str, platform: str) -> bool:
        self._load()
        k = self._key(user_id, platform)
        if k in self._cache:
            del self._cache[k]
            self._save()
            return True
        return False

    async def list_all(self) -> list[UserBinding]:
        self._load()
        return list(self._cache.values())

    async def list_active(self) -> list[UserBinding]:
        self._load()
        return [b for b in self._cache.values() if b.is_active]


class FileSignRecordRepository(SignRecordRepository):
    """基于 JSON 文件的签到记录仓储"""

    def __init__(self, data_dir: str):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._records_file = self._data_dir / "sign_records.json"
        self._records: list[SignRecord] = []
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._records.clear()
        if self._records_file.exists():
            try:
                raw = json.loads(self._records_file.read_text(encoding="utf-8"))
                for item in raw:
                    record = SignRecord(
                        user_id=item["user_id"],
                        game=GamePlatform(item.get("game", "arknights")),
                        status=SignStatus(item.get("status", "failed")),
                        signed_at=_parse_dt(item["signed_at"]) or datetime.now().astimezone(),
                        reward=item.get("reward"),
                        error_message=item.get("error_message"),
                        id=item.get("id"),
                    )
                    self._records.append(record)
            except Exception as e:
                logger.error(f"[仓储] 加载签到记录失败: {e}")
        self._loaded = True

    def _save(self):
        raw = [
            {
                "user_id": r.user_id,
                "game": r.game.value,
                "status": r.status.value,
                "signed_at": r.signed_at.isoformat(),
                "reward": r.reward,
                "error_message": r.error_message,
                "id": r.id,
            }
            for r in self._records
        ]
        self._records_file.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    async def save(self, record: SignRecord) -> SignRecord:
        self._load()
        if not record.id:
            record.id = str(uuid4())
        self._records.append(record)
        # 只保留最近 1000 条
        if len(self._records) > 1000:
            self._records = self._records[-1000:]
        self._save()
        return record

    async def find_by_user_id(self, user_id: str, limit: int = 10) -> list[SignRecord]:
        self._load()
        user_records = [r for r in self._records if r.user_id == user_id]
        return user_records[-limit:]

    async def find_recent_by_user(self, user_id: str, days: int = 7) -> list[SignRecord]:
        self._load()
        from datetime import timedelta
        cutoff = datetime.now().astimezone() - timedelta(days=days)
        return [r for r in self._records if r.user_id == user_id and r.signed_at >= cutoff]


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
