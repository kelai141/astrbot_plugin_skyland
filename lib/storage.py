"""
数据持久化层 — 用户数据 & 插件状态的统一存储

特性：
- 原子写入（临时文件 + rename）防数据损坏
- 自动备份与恢复
- 旧版本数据迁移
- AstrBot KV 存储兼容接口（>= 4.9.2）
"""
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .timeutil import beijing_now

try:
    from astrbot.api import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# ==================== 数据模型 ====================

def _make_empty_store() -> dict:
    """创建空的存储结构"""
    return {
        "users": {},
        "stats": {
            "total_bindings": 0,
            "total_signs": 0,
            "last_auto_sign": None,
        },
        "meta": {
            "version": 2,
            "created_at": beijing_now().isoformat(),
        },
    }


# ==================== 文件存储 ====================

class FileStore:
    """基于 JSON 文件的持久化存储

    特性：
    - 原子写入（tmp → replace）
    - 自动备份（主文件损坏时从 .bak 恢复）
    - 旧版本迁移
    """

    def __init__(self, data_dir: str):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._data_file = str(self._data_dir / "users.json")
        self._backup_file = str(self._data_dir / "users.json.bak")
        self._data: Optional[dict] = None

    # ---- 加载 ----

    def load(self) -> dict:
        """加载数据（带备份恢复）"""
        if self._data is not None:
            return self._data

        # 尝试主文件
        if os.path.exists(self._data_file):
            try:
                with open(self._data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._validate(data)
                self._data = data
                return data
            except (json.JSONDecodeError, ValueError, Exception) as e:
                logger.error(f"加载数据文件失败 ({e})，尝试从备份恢复…")

        # 尝试备份
        if os.path.exists(self._backup_file):
            try:
                with open(self._backup_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._validate(data)
                logger.info("已从备份文件成功恢复数据")
                # 写回主文件
                with open(self._data_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                self._data = data
                return data
            except Exception as be:
                logger.error(f"备份文件也损坏: {be}")

        # 创建新数据
        logger.info("创建新的数据文件")
        data = _make_empty_store()
        self._data = data
        return data

    def reload(self) -> dict:
        """强制重新加载（忽略缓存）"""
        self._data = None
        return self.load()

    # ---- 保存 ----

    def save(self, data: Optional[dict] = None):
        """原子化保存数据（防御性：失败不抛异常，但会记录错误日志）"""
        if data is not None:
            self._data = data

        if self._data is None:
            return

        tmp_path = ""
        succeeded = False
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._data_dir), prefix="users_", suffix=".json"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)

            if os.path.exists(self._data_file):
                shutil.copy2(self._data_file, self._backup_file)

            os.replace(tmp_path, self._data_file)
            tmp_path = ""  # 已替换，不清理

            # 写入后校验
            file_size = os.path.getsize(self._data_file)
            if file_size < 10:
                raise IOError(f"文件大小异常: {file_size} bytes")
            succeeded = True
            logger.debug(f"数据已保存 ({len(self._data.get('users', {}))} 用户, {file_size} bytes)")

        except Exception as e:
            logger.error(f"❌ 保存数据到磁盘失败: {e}", exc_info=True)
            # 尝试从备份恢复内存
            if os.path.exists(self._backup_file):
                try:
                    with open(self._backup_file, "r", encoding="utf-8") as f:
                        self._data = json.load(f)
                    logger.info("已从备份文件恢复内存数据")
                except Exception as be:
                    logger.error(f"备份恢复也失败: {be}")

        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        return succeeded

    def flush(self):
        """强制将内存数据写入磁盘（terminate 等关键时机调用）

        与 save() 不同：flush 失败会记录 critical 级别日志，
        因为这意味着插件重载后用户数据会丢失。
        """
        if self._data is None:
            return
        user_count = len(self._data.get("users", {}))
        ok = self.save(self._data)
        if ok:
            logger.info(f"数据已安全刷入磁盘 ({user_count} 用户)")
        else:
            logger.critical(
                f"⚠️ 数据写入磁盘失败！{user_count} 个用户数据可能在下一次重载后丢失。"
                f"请检查磁盘空间和目录权限: {self._data_file}"
            )

    # ---- 用户操作 ----

    def get_users(self) -> dict:
        return self.load().get("users", {})

    def get_user(self, sender_id: str) -> Optional[dict]:
        return self.get_users().get(sender_id)

    def set_user(self, sender_id: str, info: dict):
        data = self.load()
        data["users"][sender_id] = info
        data["stats"]["total_bindings"] = len(data["users"])
        self.save(data)

    def remove_user(self, sender_id: str) -> Optional[dict]:
        data = self.load()
        removed = data["users"].pop(sender_id, None)
        if removed:
            data["stats"]["total_bindings"] = len(data["users"])
            self.save(data)
        return removed

    def has_user(self, sender_id: str) -> bool:
        return sender_id in self.get_users()

    # ---- 统计 ----

    def get_stats(self) -> dict:
        return self.load().get("stats", {})

    def increment_signs(self):
        data = self.load()
        data["stats"]["total_signs"] = data["stats"].get("total_signs", 0) + 1
        data["stats"]["last_auto_sign"] = beijing_now().isoformat()
        self.save(data)

    # ---- 内部 ----

    @staticmethod
    def _validate(data: dict):
        """验证数据结构完整性"""
        if "users" not in data or "stats" not in data:
            raise ValueError("数据结构不完整，缺少 users 或 stats 字段")


# ==================== 迁移 ====================

def migrate_from_old(store: FileStore, old_name: str = "astrbot_plugin_skland"):
    """从旧插件名迁移数据"""
    try:
        old_base = Path(str(store._data_dir)).parent / old_name
        old_file = str(old_base / "users.json")
        if os.path.exists(old_file):
            with open(old_file, "r", encoding="utf-8") as f:
                old_data = json.load(f)
            if "users" in old_data:
                new_data = store.load()
                for sid, info in old_data["users"].items():
                    if sid not in new_data["users"]:
                        new_data["users"][sid] = info
                new_data["stats"]["total_bindings"] = len(new_data["users"])
                store.save(new_data)
                logger.info(f"已从 {old_name} 迁移 {len(old_data['users'])} 个用户")

                # 重命名旧文件防止重复迁移
                shutil.move(old_file, old_file + ".migrated")
    except Exception as e:
        logger.warning(f"数据迁移失败: {e}")
