"""
签到信息推送系统 — 消息格式化与推送策略

职责：
- 签到结果消息格式化（多种模板）
- 推送策略判断（是否应该推送、推送到哪里）
- 消息内容生成

不依赖 AstrBot 消息发送机制，只产出消息内容，
由上层 (main.py / handlers) 负责实际发送。
"""
from typing import Optional

from .skyland_engine import SignResult, UserSignState
from .timeutil import beijing_today


class NotificationTemplates:
    """消息模板集合"""

    @staticmethod
    def sign_success(state: UserSignState, result: SignResult) -> str:
        """签到成功通知"""
        today = beijing_today().isoformat()
        lines = [
            "🌠 森空岛自动签到完成",
            f"📅 {today}",
        ]
        if result.messages:
            lines.extend(result.messages)
        else:
            lines.append("今日无可用签到项目")

        # 附加提示
        lines.append("")
        lines.append("💡 发送 /skland push off 关闭每日推送")

        return "\n".join(lines)

    @staticmethod
    def sign_already_signed(state: UserSignState, result: SignResult) -> str:
        """已在签到时间前通过其他方式签到过"""
        today = beijing_today().isoformat()
        lines = [
            "🌠 森空岛签到状态",
            f"📅 {today}",
        ]
        if result.messages:
            lines.extend(result.messages)
        lines.append("")
        lines.append("💡 今天已经签到过了，无需重复操作~")
        lines.append("💡 发送 /skland push off 关闭每日推送")

        return "\n".join(lines)

    @staticmethod
    def sign_failed(state: UserSignState, result: SignResult) -> str:
        """签到失败通知"""
        lines = [
            "⚠️ 森空岛签到异常",
            f"📅 {beijing_today().isoformat()}",
            f"❌ {result.error or '未知错误'}",
            "",
            "🔧 可能的原因：",
            "  • Token 已过期 → 请重新绑定 /skland bind <token>",
            "  • 网络问题 → 稍后自动重试",
            "  • 森空岛服务器维护 → 请稍后再试",
            "",
            "💡 发送 /skland push off 关闭每日推送",
        ]
        return "\n".join(lines)

    @staticmethod
    def sign_manual(state: UserSignState, result: SignResult) -> str:
        """手动签到结果"""
        today = beijing_today().isoformat()
        lines = [
            "🌠 森空岛签到完成",
            f"📅 {today}",
        ]
        if result.messages:
            lines.extend(result.messages)
        else:
            lines.append("今日无可用签到项目")
        return "\n".join(lines)

    @staticmethod
    def sign_partial(state: UserSignState, result: SignResult) -> str:
        """部分成功通知（某些游戏签到成功，某些失败）"""
        today = beijing_today().isoformat()
        lines = [
            "⚠️ 森空岛签到部分完成",
            f"📅 {today}",
        ]
        lines.extend(result.messages)
        lines.append("")
        lines.append("💡 部分游戏签到失败，可稍后手动重试 /skland sign")
        return "\n".join(lines)

    @staticmethod
    def bind_success(game_info: str, sign_time: str = "09:05") -> str:
        """绑定成功通知"""
        return (
            f"✅ 绑定成功！🎉\n"
            f"检测到角色：{game_info}\n\n"
            f"📌 每天 {sign_time} 将自动签到\n"
            f"💪 现在发送 /skland sign 立即签到试试吧！"
        )

    @staticmethod
    def status_report(state: UserSignState) -> str:
        """签到状态报告"""
        today = beijing_today().isoformat()
        is_signed = (state.last_sign_date == today and
                     state.last_sign_result.startswith("✅"))

        push_status = "🟢 已开启" if state.push_enabled else "🔴 已关闭"

        return (
            f"📊 森空岛签到状态\n"
            f"🆔 绑定角色: {state.game_info}\n"
            f"📅 绑定时间: {state.bound_at[:10] if state.bound_at else '未知'}\n"
            f"⏰ 签到时间: 每天 {state.sign_time}\n"
            f"📢 推送通知: {push_status}\n"
            f"✅ 今日已签到: {'是 🎉' if is_signed else '否'}\n"
            f"📋 上次结果: {state.last_sign_result or '暂无记录'}"
        )

    @staticmethod
    def admin_broadcast(msg: str) -> str:
        """管理员群发消息"""
        return f"📢 管理员消息\n{msg}"


class PushDecision:
    """推送决策"""

    def __init__(
        self,
        should_push: bool,
        message: str = "",
        reason: str = "",
    ):
        self.should_push = should_push
        self.message = message
        self.reason = reason


class PushPolicy:
    """推送策略引擎"""

    @staticmethod
    def decide(
        state: UserSignState,
        result: SignResult,
        is_manual: bool = False,
    ) -> PushDecision:
        """决定是否推送以及推送内容

        Args:
            state: 用户签到状态
            result: 签到结果
            is_manual: 是否为手动签到

        Returns:
            PushDecision
        """
        # 手动签到始终展示结果（在命令响应中）
        if is_manual:
            if result.success:
                msg = NotificationTemplates.sign_manual(state, result)
            else:
                msg = f"❌ 签到失败: {result.error}"
            return PushDecision(should_push=True, message=msg, reason="manual")

        # 自动签到：仅当用户开启推送时发送
        if not state.push_enabled:
            return PushDecision(should_push=False, reason="push_disabled")

        # 全部已签到（API 确认今天已通过其他方式签到）
        if result.is_all_already_signed:
            return PushDecision(
                should_push=True,
                message=NotificationTemplates.sign_already_signed(state, result),
                reason="auto_already_signed",
            )

        # 全部成功
        if result.success and all(
            m.startswith("✅") for m in result.messages if m
        ):
            return PushDecision(
                should_push=True,
                message=NotificationTemplates.sign_success(state, result),
                reason="auto_success",
            )

        # 全部失败
        if not result.success or all(
            m.startswith("❌") for m in result.messages if m
        ):
            return PushDecision(
                should_push=True,
                message=NotificationTemplates.sign_failed(state, result),
                reason="auto_failed",
            )

        # 部分成功（含部分已签、部分失败等混合场景）
        return PushDecision(
            should_push=True,
            message=NotificationTemplates.sign_partial(state, result),
            reason="auto_partial",
        )
