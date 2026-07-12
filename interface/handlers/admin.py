"""
管理员命令处理器
"""
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Plain

from domain.errors import UserNotBoundError


async def handle_list_users(plugin, event: AstrMessageEvent):
    """管理员查看所有绑定用户"""
    try:
        bindings = await plugin._account_service.list_all_bindings()

        if not bindings:
            yield event.chain_result([Plain(text="📭 目前没有任何绑定用户")])
            return

        lines = [f"📋 已绑定用户 ({len(bindings)}):"]
        for i, b in enumerate(bindings, 1):
            masked = b.credential.safe_masked if b.credential else "N/A"
            lines.append(
                f"{i}. {b.user_id} | {b.game.value} | "
                f"签到: {b.sign_time} | "
                f"连续: {b.consecutive_days}天 | "
                f"凭证: {masked}"
            )

        yield event.chain_result([Plain("\n".join(lines))])
    except Exception as e:
        logger.error(f"[管理员] 查看用户列表失败: {e}")
        yield event.chain_result([Plain(f"❌ 获取用户列表失败: {e}")])


async def handle_remove_user(plugin, event: AstrMessageEvent, user_id: str = None):
    """管理员移除用户绑定"""
    if not user_id:
        yield event.chain_result([Plain("❌ 请指定要移除的用户 ID，例如：/skland remove 123456")])
        return

    try:
        result = await plugin._account_service.remove_binding(user_id, "aiocqhttp")
        if result:
            logger.info(f"[管理员] 已移除用户 {user_id} 的绑定")
            yield event.chain_result([Plain(f"✅ 已移除用户 {user_id} 的绑定")])
        else:
            yield event.chain_result([Plain(f"❌ 移除用户 {user_id} 失败")])
    except UserNotBoundError:
        yield event.chain_result([Plain(f"❌ 用户 {user_id} 未绑定")])
    except Exception as e:
        logger.error(f"[管理员] 移除用户失败: {e}")
        yield event.chain_result([Plain(f"❌ 移除用户失败: {e}")])


async def handle_broadcast(plugin, event: AstrMessageEvent):
    """管理员群发消息"""
    message = event.get_message_str()
    # 提取 "/skland broadcast " 后面的内容
    for prefix in ["/skland broadcast ", "/skland broadcast", "广播"]:
        if message.startswith(prefix):
            message = message[len(prefix):].strip()
            break

    if not message:
        yield event.chain_result([Plain("❌ 请提供要群发的消息，例如：/skland broadcast 服务器维护通知...")])
        return

    try:
        bindings = await plugin._account_service.list_all_bindings()
        success = 0
        fail = 0

        for b in bindings:
            try:
                await plugin._notification_port.send_to_admin(
                    f"📢 {message}"
                )
                success += 1
            except Exception:
                fail += 1

        logger.info(f"[管理员] 群发完成: 成功{success}, 失败{fail}")
        yield event.chain_result([Plain(f"✅ 群发完成 (成功: {success}, 失败: {fail})")])
    except Exception as e:
        logger.error(f"[管理员] 群发失败: {e}")
        yield event.chain_result([Plain(f"❌ 群发失败: {e}")])
