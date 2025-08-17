# -*- coding: utf-8 -*-
import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.star import StarTools

from .learning_style.data_manager import DataManager
from .learning_style.learning_manager import LearningManager
from .learning_style.scheduler import Scheduler

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

    async def terminate(self):
        """
        异步的插件销毁方法，当插件被卸载/停用时会调用。
        """
        await self.scheduler.stop()
        # 插件卸载时保存所有数据
        await self.data_manager.force_save()
        logger.info("学习风格插件已卸载并停止定时任务。")