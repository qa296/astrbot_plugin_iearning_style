# -*- coding: utf-8 -*-
import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.star import StarTools

from .learning_style.data_manager import DataManager
from .learning_style.learning_manager import LearningManager
from .learning_style.scheduler import Scheduler
from .learning_style.style_injector import StyleInjector

@register("astrbot_plugin_iearning_style", "qa296", "从聊天中学习他人说话方式。", "0.1.0", "https://github.com/qa296/astrbot_plugin_iearning_style")
class IearningStylePlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        # 获取规范的数据目录
        plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_iearning_style")
        # 初始化插件的核心组件
        self.data_manager = DataManager(plugin_data_dir)
        self.learning_manager = LearningManager(self, self.data_manager, self.config)
        self.scheduler = Scheduler(self.data_manager, self.learning_manager, self.config)
        self.style_injector = StyleInjector(self.data_manager, self.config)

    async def initialize(self):
        """
        异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。
        """
        self.scheduler.start()
        logger.info("学习风格插件已加载并启动定时任务。")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """
        监听所有消息，记录到历史中用于后续分析。
        """
        # 忽略机器人自己发的消息
        if event.get_sender_id() == event.get_self_id():
            return

        session_id = event.unified_msg_origin
        message_content = event.get_message_str()
        
        if not message_content:
            return

        message = {
            "sender": event.get_sender_name(),
            "content": message_content,
            "timestamp": asyncio.get_running_loop().time()
        }
        
        await self.data_manager.add_message_to_history(session_id, message)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req):
        """
        在LLM请求前拦截并注入学习到的风格。
        """
        session_id = event.unified_msg_origin
        
        # 注入风格到system prompt
        original_prompt = req.system_prompt or ""
        new_prompt = self.style_injector.inject_style_to_prompt(session_id, original_prompt)
        req.system_prompt = new_prompt

    @filter.command("风格状态")
    async def style_status(self, event: AstrMessageEvent):
        """
        查看当前会话的风格学习状态。
        """
        session_id = event.unified_msg_origin
        summary = self.style_injector.get_style_summary(session_id)
        
        if not summary["has_styles"]:
            yield event.plain_result("当前会话还没有学习到任何风格特点。")
            return
            
        response = f"当前会话风格状态：\n"
        response += f"总学习风格数：{summary['total_styles']}\n"
        response += f"高熟练度风格：{summary['high_proficiency_styles']}\n"
        
        if summary['language_styles']:
            response += f"语言风格：{', '.join(summary['language_styles'])}\n"
            
        if summary['grammar_features']:
            response += f"语法特征：{', '.join(summary['grammar_features'])}\n"
            
        yield event.plain_result(response.strip())

    @filter.command("清空风格")
    async def clear_styles(self, event: AstrMessageEvent):
        """
        清空当前会话学习到的所有风格。
        """
        session_id = event.unified_msg_origin
        
        # 清空风格数据
        if session_id in self.data_manager.styles:
            self.data_manager.styles[session_id] = []
            self.data_manager._dirty_styles = True
            asyncio.create_task(self.data_manager.save_styles())
            
        yield event.plain_result("已清空当前会话的所有学习风格。")

    async def terminate(self):
        """
        异步的插件销毁方法，当插件被卸载/停用时会调用。
        """
        await self.scheduler.stop()
        # 插件卸载时保存所有数据
        await self.data_manager.force_save()
        logger.info("学习风格插件已卸载并停止定时任务。")