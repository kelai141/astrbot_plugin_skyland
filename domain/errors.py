"""领域层异常定义 — 避免 Application 反向依赖 Infrastructure"""

from typing import Optional

class SkylandError(Exception):
    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code

class SkylandAuthError(SkylandError):
    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message, code)

class SkylandRateLimitError(SkylandError):
    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message, code)

class SkylandApiError(SkylandError):
    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message, code)
