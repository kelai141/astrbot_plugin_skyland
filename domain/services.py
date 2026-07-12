"""
领域服务接口 — 定义核心业务逻辑接口，由 Application 层实现。
"""

from abc import ABC, abstractmethod
from typing import Optional
from .models import Account, TaskResult


class SignServiceInterface(ABC):
    @abstractmethod
    async def execute_sign(self, account: Account) -> TaskResult: ...
    @abstractmethod
    async def refresh_credential(self, account: Account) -> bool: ...

class AccountServiceInterface(ABC):
    @abstractmethod
    async def bind_with_token(self, sender_id: str, raw_token: str) -> tuple[Account, str]: ...
    @abstractmethod
    async def bind_with_phone(self, sender_id: str, phone: str, code: str) -> tuple[Account, str]: ...
    @abstractmethod
    async def unbind(self, sender_id: str) -> Optional[Account]: ...

class PushPolicyInterface(ABC):
    @abstractmethod
    def decide(self, account: Account, result: TaskResult, is_manual: bool = False) -> tuple[bool, str]: ...
