"""
基础设施 — 数据迁移：从 v1/v2 格式迁移到 v3
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from astrbot.api import logger

from domain.enums import (
    CredentialType, BindingStatus, GamePlatform, NotificationPolicy,
)
from domain.models import UserBinding, UserCredential


class DataMigration:
    """从旧版文件格式迁移到新版仓储"""

    def __init__(self, old_data_dir: str, new_data_dir: str):
        self._old_dir = Path(old_data_dir)
        self._new_dir = Path(new_data_dir)

    async def needs_migration(self) -> bool:
        """检查是否需要迁移"""
        # 如果新格式已存在，跳过
        if (self._new_dir / "bindings.json").exists():
            return False
        # 如果旧格式存在，需要迁移
        return await self._has_old_data()

    async def _has_old_data(self) -> bool:
        """检查是否存在旧版数据文件"""
        old_files = [
            "store.json",
            "users.json",
            "bindings.json",
        ]
        for f in old_files:
            if (self._old_dir / f).exists():
                return True
        return False

    async def migrate(self) -> int:
        """执行迁移，返回迁移的用户数"""
        count = 0
        bindings = []

        # 尝试从旧版 store.json 迁移
        store_file = self._old_dir / "store.json"
        if store_file.exists():
            try:
                raw = json.loads(store_file.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    for item in raw:
                        binding = self._convert_old_store_item(item)
                        if binding:
                            bindings.append(binding)
                            count += 1
                elif isinstance(raw, dict):
                    # 旧版可能是 dict of users
                    for key, item in raw.items():
                        binding = self._convert_old_store_item(item, key)
                        if binding:
                            bindings.append(binding)
                            count += 1
                logger.info(f"[迁移] 从 store.json 迁移了 {count} 个用户")
            except Exception as e:
                logger.error(f"[迁移] 解析 store.json 失败: {e}")

        # 写入新格式
        if bindings:
            new_file = self._new_dir / "bindings.json"
            new_file.write_text(
                json.dumps(
                    [self._binding_to_dict(b) for b in bindings],
                    ensure_ascii=False, indent=2, default=str,
                ),
                encoding="utf-8",
            )
            logger.info(f"[迁移] 已写入 {len(bindings)} 条绑定到新格式")

        return count

    def _convert_old_store_item(self, item: dict, fallback_key: str = "") -> Optional[UserBinding]:
        """转换旧版 store 条目到新版 UserBinding"""
        try:
            user_id = item.get("user_id") or item.get("qq") or item.get("uid") or fallback_key
            if not user_id:
                return None

            token = item.get("token") or item.get("credential", "")
            credential = UserCredential(
                type=CredentialType.TOKEN,
                value=token,
                hypergryph_token=item.get("hypergryph_token") or token,
                did=item.get("did"),
            )

            game_str = item.get("game", "arknights")
            try:
                game = GamePlatform(game_str)
            except ValueError:
                game = GamePlatform.ARKNIENTS

            policy_str = item.get("push_policy", "all")
            try:
                policy = NotificationPolicy(policy_str)
            except ValueError:
                policy = NotificationPolicy.ALL

            return UserBinding(
                user_id=str(user_id),
                platform=item.get("platform", "aiocqhttp"),
                credential=credential,
                game=game,
                sign_time=item.get("sign_time", "09:05"),
                notification_policy=policy,
                status=BindingStatus.ACTIVE,
                bound_at=_parse_dt(item.get("bound_at")),
                last_sign_at=_parse_dt(item.get("last_sign_at")),
                consecutive_days=item.get("consecutive_days", 0),
                total_signs=item.get("total_signs", 0),
            )
        except Exception as e:
            logger.warning(f"[迁移] 转换条目失败: {e}")
            return None

    @staticmethod
    def _binding_to_dict(b: UserBinding) -> dict:
        return {
            "id": b.id,
            "user_id": b.user_id,
            "platform": b.platform,
            "game": b.game.value,
            "sign_time": b.sign_time,
            "notification_policy": b.notification_policy.value,
            "status": b.status.value,
            "bound_at": b.bound_at.isoformat() if b.bound_at else None,
            "last_sign_at": b.last_sign_at.isoformat() if b.last_sign_at else None,
            "consecutive_days": b.consecutive_days,
            "total_signs": b.total_signs,
            "credential": {
                "type": b.credential.type.value,
                "value": b.credential.value,
                "hypergryph_token": b.credential.hypergryph_token,
                "did": b.credential.did,
                "created_at": b.credential.created_at.isoformat() if b.credential.created_at else None,
                "expires_at": b.credential.expires_at.isoformat() if b.credential.expires_at else None,
            },
        }


def _parse_dt(s) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, str):
        try:
            return datetime.fromisoformat(s)
        except (ValueError, TypeError):
            return None
    if isinstance(s, (int, float)):
        return datetime.fromtimestamp(s).astimezone()
    return None
