"""
应用层 — 签到用例编排

核心职责：
1. 接收输入 DTO，调用领域服务/端口
2. 协调签到流程：验证 → 执行 → 记录 → 通知
3. 发送领域事件
"""
import asyncio
from datetime import datetime
from typing import Optional

from astrbot.api import logger

from domain.enums import SignStatus, GamePlatform, NotificationPolicy, BindingStatus
from domain.models import (
    UserBinding, UserCredential, SignRecord,
    PushNotification, DidRecord,
)
from domain.ports import (
    UserBindingRepository, SignRecordRepository,
    SkylandApiClient, NotificationPort, DeviceFingerprintService,
)
from domain.errors import (
    UserNotBoundError, UserAlreadyBoundError,
    CredentialExpiredError, SignInProgressError,
    DomainError,
)
from domain.services import SignEvaluationService, CredentialService
from application.dto import (
    SignInDTO, SignResultDTO, UserInfoDTO,
    BatchSignResultDTO,
)


class SignService:
    """签到应用服务"""

    def __init__(
        self,
        binding_repo: UserBindingRepository,
        record_repo: SignRecordRepository,
        api_client: SkylandApiClient,
        notification_port: NotificationPort,
        device_fingerprint: DeviceFingerprintService,
    ):
        self._binding_repo = binding_repo
        self._record_repo = record_repo
        self._api_client = api_client
        self._notification_port = notification_port
        self._device_fingerprint = device_fingerprint
        self._sign_lock: set[str] = set()

    async def execute_sign(self, dto: SignInDTO) -> SignResultDTO:
        """执行单用户签到"""
        if dto.user_id in self._sign_lock:
            raise SignInProgressError(dto.user_id)

        self._sign_lock.add(dto.user_id)
        try:
            return await self._do_sign(dto)
        finally:
            self._sign_lock.discard(dto.user_id)

    async def execute_batch_sign(self, game: GamePlatform = None) -> BatchSignResultDTO:
        """执行所有活跃用户的批量签到"""
        bindings = await self._binding_repo.list_active()
        if game:
            bindings = [b for b in bindings if b.game == game]

        results = []
        for binding in bindings:
            try:
                dto = SignInDTO(user_id=binding.user_id, platform=binding.platform)
                result = await self.execute_sign(dto)
                results.append(result)
            except DomainError as e:
                results.append(SignResultDTO(
                    user_id=binding.user_id,
                    game=binding.game,
                    status=SignStatus.FAILED,
                    error_message=str(e),
                ))
            except Exception as e:
                logger.error(f"[批量签到] {binding.user_id} 异常: {e}", exc_info=True)
                results.append(SignResultDTO(
                    user_id=binding.user_id,
                    game=binding.game,
                    status=SignStatus.FAILED,
                    error_message=f"系统异常: {e}",
                ))
            await asyncio.sleep(1)  # 间隔防限流

        total = len(results)
        success = sum(1 for r in results if r.status == SignStatus.SUCCESS)
        failed = sum(1 for r in results if r.status == SignStatus.FAILED)
        skipped = sum(1 for r in results if r.status in (SignStatus.ALREADY_SIGNED, SignStatus.SKIPPED))

        # 发送管理员通知
        summary = (
            f"📊 批量签到完成\n"
            f"总计: {total} | ✅ 成功: {success} | ❌ 失败: {failed} | ⏭️ 跳过: {skipped}"
        )
        await self._notification_port.send_to_admin(summary)

        return BatchSignResultDTO(
            total=total,
            success=success,
            failed=failed,
            skipped=skipped,
            details=results,
        )

    async def get_user_info(self, user_id: str, platform: str) -> Optional[UserInfoDTO]:
        """获取用户信息"""
        binding = await self._binding_repo.find_by_user_id(user_id, platform)
        if not binding:
            return None

        return UserInfoDTO(
            user_id=binding.user_id,
            platform=binding.platform,
            game=binding.game.value if binding.game else "unknown",
            sign_time=binding.sign_time,
            notification_policy=binding.notification_policy,
            bound_at=binding.bound_at.isoformat() if binding.bound_at else None,
            last_sign_at=binding.last_sign_at.isoformat() if binding.last_sign_at else None,
            consecutive_days=binding.consecutive_days,
            total_signs=binding.total_signs,
            is_active=binding.is_active,
            credential_masked=binding.credential.safe_masked if binding.credential else "",
        )

    async def _do_sign(self, dto: SignInDTO) -> SignResultDTO:
        """内部签到逻辑"""
        binding = await self._binding_repo.find_by_user_id(dto.user_id, dto.platform)
        if not binding:
            raise UserNotBoundError(dto.user_id)

        if not binding.is_active:
            raise UserNotBoundError(dto.user_id)

        credential = binding.credential
        if credential is None:
            raise CredentialExpiredError(dto.user_id)

        # 检查凭证是否过期
        if CredentialService.is_credential_expired(credential):
            binding.status = BindingStatus.EXPIRED
            await self._binding_repo.save(binding)
            raise CredentialExpiredError(dto.user_id)

        # 获取设备指纹
        did = await self._device_fingerprint.get_or_create_did()
        game_id = self._game_to_api_id(binding.game)

        # 调用 API 签到
        try:
            response = await self._api_client.sign(
                token=credential.value,
                did=did,
                game_id=game_id,
            )
        except Exception as e:
            record = SignRecord(
                user_id=dto.user_id,
                game=binding.game,
                status=SignStatus.FAILED,
                signed_at=datetime.now().astimezone(),
                error_message=str(e),
            )
            await self._record_repo.save(record)
            return SignResultDTO(
                user_id=dto.user_id,
                game=binding.game,
                status=SignStatus.FAILED,
                error_message=str(e),
            )

        status = SignEvaluationService.evaluate(response)
        reward = response.get("data", {}).get("reward", None) if status == SignStatus.SUCCESS else None
        error_msg = response.get("message", None) if status == SignStatus.FAILED else None

        # 持久化记录
        record = SignRecord(
            user_id=dto.user_id,
            game=binding.game,
            status=status,
            signed_at=datetime.now().astimezone(),
            reward=reward,
            error_message=error_msg,
        )
        await self._record_repo.save(record)

        # 更新绑定状态
        if status == SignStatus.SUCCESS:
            binding.last_sign_at = datetime.now().astimezone()
            binding.consecutive_days += 1
            binding.total_signs += 1
        await self._binding_repo.save(binding)

        # 发送通知
        await self._send_sign_notification(binding, status, reward, error_msg)

        # 如果凭证相关异常，通知用户
        if status == SignStatus.FAILED and error_msg:
            logger.warning(f"[签到] {dto.user_id} 失败: {error_msg}")

        return SignResultDTO(
            user_id=dto.user_id,
            game=binding.game,
            status=status,
            reward=reward,
            error_message=error_msg,
        )

    async def _send_sign_notification(
        self,
        binding: UserBinding,
        status: SignStatus,
        reward: Optional[str] = None,
        error: Optional[str] = None,
    ):
        """根据通知策略发送签到结果通知"""
        policy = binding.notification_policy

        if policy == NotificationPolicy.NONE:
            return

        if policy == NotificationPolicy.FAILURE_ONLY and status == SignStatus.SUCCESS:
            return

        game_name = "明日方舟" if binding.game == GamePlatform.ARKNIENTS else "终末地"

        if status == SignStatus.SUCCESS:
            title = f"✅ {game_name} 签到成功"
            message = f"🎉 {game_name} 签到成功！"
            if reward:
                message += f"\n奖励: {reward}"
            message += f"\n连续签到: {binding.consecutive_days} 天"
        elif status == SignStatus.ALREADY_SIGNED:
            title = f"ℹ️ {game_name} 今日已签到"
            message = f"今日 {game_name} 已签到过了~\n连续签到: {binding.consecutive_days} 天"
        else:
            title = f"❌ {game_name} 签到失败"
            message = f"签到失败: {error or '未知错误'}"
            if binding.credential and CredentialService.is_credential_expired(binding.credential):
                message += "\n💡 凭证已过期，请使用 /skland login 重新绑定"

        notification = PushNotification(
            user_id=binding.user_id,
            title=title,
            message=message,
            notification_type="sign_result",
        )
        await self._notification_port.send(notification)

    @staticmethod
    def _game_to_api_id(game: GamePlatform) -> str:
        """游戏平台转 API game_id"""
        mapping = {
            GamePlatform.ARKNIENTS: "1",
            GamePlatform.ENDFIELD: "2",
        }
        return mapping.get(game, "1")
