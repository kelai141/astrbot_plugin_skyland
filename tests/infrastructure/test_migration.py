"""
数据迁移测试
"""
import json
import tempfile
from pathlib import Path

import pytest

from infrastructure.persistence.migration import DataMigration


@pytest.mark.asyncio
class TestDataMigration:
    @pytest.fixture
    def temp_dirs(self):
        with tempfile.TemporaryDirectory() as old_dir:
            with tempfile.TemporaryDirectory() as new_dir:
                yield old_dir, new_dir

    async def test_needs_migration_true(self, temp_dirs):
        old_dir, new_dir = temp_dirs
        store_file = Path(old_dir) / "store.json"
        store_file.write_text("[]", encoding="utf-8")
        migration = DataMigration(old_dir, new_dir)
        assert await migration.needs_migration() is True

    async def test_needs_migration_false(self, temp_dirs):
        old_dir, new_dir = temp_dirs
        # 新格式已经存在
        new_file = Path(new_dir) / "bindings.json"
        new_file.write_text("[]", encoding="utf-8")
        migration = DataMigration(old_dir, new_dir)
        assert await migration.needs_migration() is False

    async def test_migrate_empty_store(self, temp_dirs):
        old_dir, new_dir = temp_dirs
        store_file = Path(old_dir) / "store.json"
        store_file.write_text("[]", encoding="utf-8")
        migration = DataMigration(old_dir, new_dir)
        count = await migration.migrate()
        assert count == 0

    async def test_migrate_single_user(self, temp_dirs):
        old_dir, new_dir = temp_dirs
        store_file = Path(old_dir) / "store.json"
        store_file.write_text(json.dumps([{
            "user_id": "123456",
            "token": "test_token",
            "game": "arknights",
            "sign_time": "09:05",
        }], ensure_ascii=False), encoding="utf-8")
        migration = DataMigration(old_dir, new_dir)
        count = await migration.migrate()
        assert count == 1

        # 验证新文件
        new_file = Path(new_dir) / "bindings.json"
        assert new_file.exists()
        data = json.loads(new_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["user_id"] == "123456"
