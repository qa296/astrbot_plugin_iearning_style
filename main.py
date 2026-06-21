import asyncio

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

from .learning_style.data_manager import DataManager
from .learning_style.learning_manager import LearningManager
from .learning_style.scheduler import Scheduler
from .learning_style.style_injector import StyleInjector


@register(
    "astrbot_plugin_iearning_style",
    "qa296",
    "从聊天中学习他人说话方式。",
    "0.2.0",
    "https://github.com/qa296/astrbot_plugin_iearning_style",
)
class IearningStylePlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_iearning_style")

        self.data_manager = DataManager(plugin_data_dir, self.config)
        self.learning_manager = LearningManager(self, self.data_manager, self.config)
        self.scheduler = Scheduler(
            self.data_manager, self.learning_manager, self.config
        )
        self.style_injector = StyleInjector(self.data_manager, self.config)

    async def initialize(self):
        """异步的插件初始化方法。"""
        self.scheduler.start()
        logger.info("学习风格插件已加载并启动定时任务。")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """监听所有消息，记录到历史中用于后续分析。"""
        if event.get_sender_id() == event.get_self_id():
            return

        session_id = event.unified_msg_origin
        message_content = event.get_message_str()

        if not message_content:
            return

        message = {
            "sender": event.get_sender_name(),
            "content": message_content,
            "timestamp": asyncio.get_running_loop().time(),
        }

        await self.data_manager.add_message_to_history(session_id, message)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req):
        """在 LLM 请求前拦截并注入学习到的风格。"""
        session_id = event.unified_msg_origin
        user_message = event.get_message_str() or ""

        original_prompt = req.system_prompt or ""
        new_prompt = self.style_injector.inject_style_to_prompt(
            session_id, original_prompt, user_message=user_message
        )
        req.system_prompt = new_prompt

    @filter.command("风格状态")
    async def style_status(self, event: AstrMessageEvent):
        """查看当前会话的风格学习状态"""
        session_id = event.unified_msg_origin
        summary = self.style_injector.get_style_summary(session_id)

        if not summary["has_styles"]:
            yield event.plain_result("当前会话还没有学习到任何风格特点。")
            return

        response = "当前会话风格状态：\n"
        response += f"通用表征：{summary['universal_count']} 条\n"
        response += f"特定表征：{summary['specific_count']} 条\n"

        if summary["universal_preview"]:
            response += (
                f"通用 Top-3：{', '.join(summary['universal_preview'])}\n"
            )

        if summary["specific_preview"]:
            response += (
                f"特定 Top-3：{', '.join(summary['specific_preview'])}\n"
            )

        yield event.plain_result(response.strip())

    @filter.command("清空风格")
    async def clear_styles(self, event: AstrMessageEvent):
        """清空当前会话学习到的所有风格"""
        session_id = event.unified_msg_origin

        if session_id in self.data_manager.universal:
            self.data_manager.universal[session_id] = []
            self.data_manager._dirty_universal = True
        if session_id in self.data_manager.specific:
            self.data_manager.specific[session_id] = []
            self.data_manager._dirty_specific = True

        asyncio.create_task(self.data_manager._schedule_save())
        yield event.plain_result("已清空当前会话的所有学习风格。")

    async def terminate(self):
        """异步的插件销毁方法。"""
        await self.scheduler.stop()
        await self.data_manager.force_save()
        logger.info("学习风格插件已卸载并停止定时任务。")
