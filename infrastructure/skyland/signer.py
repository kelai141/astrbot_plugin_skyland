"""
森空岛 API 签名实现
"""
import hashlib
import hmac
import json
import time
from typing import Optional

from astrbot.api import logger


class SkylandSigner:
    """森空岛 API 请求签名器"""

    # 森空岛已知的签名常量
    _HEADER_NAME = "x-skland-signature"
    _SALT = "xSk23@7#lD9^qF!p"  # 内部 salt

    def __init__(self, salt: Optional[str] = None):
        self._salt = salt or self._SALT

    def sign(self, path: str, body: Optional[dict] = None, timestamp: Optional[int] = None) -> str:
        """生成签名

        Args:
            path: 请求路径（不含域名）
            body: 请求体（如果是 POST 请求）
            timestamp: 时间戳（默认当前时间）

        Returns:
            签名字符串
        """
        ts = timestamp or int(time.time())
        data = f"{path}{ts}"

        if body:
            # 按 key 排序后序列化
            sorted_body = json.dumps(body, separators=(",", ":"), sort_keys=True)
            data += sorted_body

        signature = hmac.new(
            self._salt.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return f"{ts},{signature}"

    def to_header(self, path: str, body: Optional[dict] = None) -> dict:
        """生成签名头"""
        ts = int(time.time())
        signature = self.sign(path, body, ts)
        return {
            self._HEADER_NAME: signature,
            "x-skland-timestamp": str(ts),
        }

    @staticmethod
    def verify(signature: str, path: str, body: Optional[dict] = None, max_age_seconds: int = 300) -> bool:
        """验证签名（服务端使用）

        Args:
            signature: 完整的签名字符串 (timestamp,signature)
            path: 请求路径
            body: 请求体
            max_age_seconds: 最大有效时间

        Returns:
            签名是否有效
        """
        try:
            parts = signature.split(",", 1)
            if len(parts) != 2:
                return False

            ts_str, sig = parts
            ts = int(ts_str)

            # 检查时间戳新鲜度
            now = int(time.time())
            if abs(now - ts) > max_age_seconds:
                return False

            # 重新计算签名
            expected = SkylandSigner().sign(path, body, ts)
            return hmac.compare_digest(sig, expected.split(",", 1)[1])
        except (ValueError, IndexError):
            return False
