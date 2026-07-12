"""
绑定/登录/解绑处理器
"""
import asyncio
import re
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Plain

from domain.enums import GamePlatform
from domain.errors import UserAlreadyBoundError, UserNotBoundError, InvalidCredentialError


async def handle_bind(plugin, event: AstrMessageEvent, token: str = None):
    """处理 /skland bind <token> — 通过 Token 绑定"""
    if not token:
        yield event.chain_result([Plain(
            "❌ 请提供鹰角通行证 Token\n\n"
            "获取方法：打开森空岛Web端 (https://web.skland.com) → F12 → "
            "Application → Local Storage → 复制 skland 的 hypergryph_cred 值"
        )])
        return

    token = token.strip()

    # 检查是否已绑定
    existing = await plugin._binding_repo.find_by_user_id(
        event.get_sender_id(), plugin._platform
    )
    if existing and existing.is_active:
        yield event.chain_result([Plain(f"❌ 你已经绑定了森空岛账号 (凭证: {existing.credential.safe_masked})")])
        return

    # 检查 token 格式
    if not re.match(r'^[\w\-\.]+$', token):
        yield event.chain_result([Plain("❌ Token 格式异常，请检查是否完整复制")])
        return

    # 发送处理中提示
    yield event.chain_result([Plain("🔄 正在验证 Token 并绑定账号...")])

    try:
        binding = await plugin._account_service.bind_by_token(
            user_id=event.get_sender_id(),
            platform=plugin._platform,
            credential_value=token,
        )

        msg = (
            f"✅ 绑定成功！\n"
            f"🎮 游戏: {binding.game.value}\n"
            f"⏰ 签到时间: {binding.sign_time}\n"
            f"📊 已连续签到: {binding.consecutive_days} 天\n\n"
            "💡 使用 /skland sign 立即签到\n"
            "💡 使用 /skland status 查看状态\n"
            "💡 使用 /skland push off 关闭推送"
        )
        yield event.chain_result([Plain(msg)])

        # 绑定成功后自动签到一次
        asyncio.create_task(_auto_sign_after_bind(plugin, event.get_sender_id()))

    except InvalidCredentialError as e:
        yield event.chain_result([Plain(f"❌ Token 无效: {e}")])
    except Exception as e:
        logger.error(f"[绑定] Token 绑定失败: {e}", exc_info=True)
        yield event.chain_result([Plain(f"❌ 绑定失败: {e}")])


async def handle_login(plugin, event: AstrMessageEvent):
    """处理 /skland login — 手机号登录（分步进行）"""
    message = event.get_message_str().strip()

    # 检查是否已绑定
    existing = await plugin._binding_repo.find_by_user_id(
        event.get_sender_id(), plugin._platform
    )
    if existing and existing.is_active:
        yield event.chain_result([Plain(f"❌ 你已经绑定了森空岛账号 (凭证: {existing.credential.safe_masked})")])
        return

    # 提取手机号
    phone_match = re.search(r'(?:login\s+)?(1[3-9]\d{9})', message)
    if not phone_match:
        yield event.chain_result([Plain(
            "📱 手机号登录流程:\n\n"
            "1️⃣ 发送手机号:\n"
            "   /skland login 13800138000\n\n"
            "2️⃣ 收到验证码后:\n"
            "   /skland login 13800138000 123456\n\n"
            "⚠️ 验证码5分钟内有效"
        )])
        return

    phone = phone_match.group(1)

    # 检查是否已有验证码参数
    code_match = re.search(r'(\d{4,6})$', message.replace(phone, "").strip())
    code = code_match.group(1) if code_match else None

    if not code:
        # 第一步：发送验证码
        try:
            yield event.chain_result([Plain(f"📱 正在向 {phone[:3]}****{phone[-3:]} 发送验证码...")])
            result = await plugin._account_service.bind_by_phone(
                event.get_sender_id(), plugin._platform, phone
            )
            if result.get("code") == 0:
                yield event.chain_result([Plain(
                    f"✅ 验证码已发送至 {phone[:3]}****{phone[-3:]}\n\n"
                    f"请在5分钟内回复:\n"
                    f"   /skland login {phone} <验证码>\n\n"
                    f"例如: /skland login {phone} 123456"
                )])
            else:
                yield event.chain_result([Plain(f"❌ 发送验证码失败: {result.get('message', '未知错误')}")])
        except InvalidCredentialError as e:
            yield event.chain_result([Plain(f"❌ {e}")])
        except Exception as e:
            logger.error(f"[登录] 发送验证码失败: {e}")
            yield event.chain_result([Plain(f"❌ 发送验证码失败: {e}")])
    else:
        # 第二步：验证验证码并绑定
        try:
            yield event.chain_result([Plain("🔄 正在验证验证码并绑定账号...")])
            binding = await plugin._account_service.verify_and_bind(
                event.get_sender_id(), plugin._platform, phone, code
            )
            msg = (
                f"✅ 手机号绑定成功！\n"
                f"🎮 游戏: {binding.game.value}\n"
                f"⏰ 签到时间: {binding.sign_time}\n"
                f"📊 已连续签到: {binding.consecutive_days} 天\n\n"
                "💡 使用 /skland sign 立即签到\n"
                "💡 使用 /skland status 查看状态"
            )
            yield event.chain_result([Plain(msg)])

            # 绑定成功后自动签到一次
            asyncio.create_task(_auto_sign_after_bind(plugin, event.get_sender_id()))

        except InvalidCredentialError as e:
            yield event.chain_result([Plain(f"❌ 验证失败: {e}")])
        except Exception as e:
            logger.error(f"[登录] 验证码绑定失败: {e}")
            yield event.chain_result([Plain(f"❌ 绑定失败: {e}")])


async def handle_unbind(plugin, event: AstrMessageEvent):
    """处理 /skland unbind — 解绑账号"""
    try:
        result = await plugin._account_service.unbind(
            event.get_sender_id(), plugin._platform
        )
        if result:
            yield event.chain_result([Plain("✅ 已解绑森空岛账号，不再自动签到")])
        else:
            yield event.chain_result([Plain("❌ 解绑失败，请稍后重试")])
    except UserNotBoundError:
        yield event.chain_result([Plain("❌ 你还没有绑定森空岛账号")])
    except Exception as e:
        logger.error(f"[解绑] 解绑失败: {e}")
        yield event.chain_result([Plain(f"❌ 解绑失败: {e}")])


async def _auto_sign_after_bind(plugin, user_id: str):
    """绑定后自动签到一次（后台任务）"""
    try:
        await asyncio.sleep(1)
        from application.dto import SignInDTO
        dto = SignInDTO(user_id=user_id, platform=plugin._platform)
        result = await plugin._sign_service.execute_sign(dto)
        logger.info(f"[自动签到] 新绑定用户 {user_id} 自动签到完成: {result.status.value}")
    except Exception as e:
        logger.debug(f"[自动签到] 新绑定用户 {user_id} 自动签到跳过: {e}")
