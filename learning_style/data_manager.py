# -*- coding: utf-8 -*-
import json
import os
from typing import Dict, List, Any
from astrbot.api import logger
import asyncio

class DataManager:
    """
    负责插件数据的加载、保存和管理。
    """
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.styles_file = os.path.join(data_dir, "styles.json")
        self.chat_history_file = os.path.join(data_dir, "chat_history.json")
        
        self.styles: Dict[str, List[Dict[str, Any]]] = {}
        self.chat_history: Dict[str, List[Dict[str, Any]]] = {}
        self._ensure_data_dir()
        self.load_styles()
        self.load_chat_history()
        self.lock = asyncio.Lock()
        
        # 批量保存相关
        self._dirty_styles = False
        self._dirty_chat_history = False
        self._save_timer = None
        self._save_delay = 5.0  # 5秒后保存

    def _ensure_data_dir(self):
        """
        确保数据目录存在。
        """
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            logger.info(f"创建数据目录: {self.data_dir}")

    def load_styles(self):
        """
        从文件加载学习到的风格。
        """
        if os.path.exists(self.styles_file):
            try:
                with open(self.styles_file, "r", encoding="utf-8") as f:
                    self.styles = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"加载风格文件失败: {e}")
                self.styles = {}
        else:
            self.styles = {}

    async def save_styles(self):
        """
        将学习到的风格保存到文件。
        """
        async with self.lock:
            try:
                with open(self.styles_file, "w", encoding="utf-8") as f:
                    json.dump(self.styles, f, ensure_ascii=False, indent=4)
                self._dirty_styles = False
            except IOError as e:
                logger.error(f"保存风格文件失败: {e}")

    def load_chat_history(self):
        """
        从文件加载聊天记录。
        """
        if os.path.exists(self.chat_history_file):
            try:
                with open(self.chat_history_file, "r", encoding="utf-8") as f:
                    self.chat_history = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"加载聊天记录文件失败: {e}")
                self.chat_history = {}
        else:
            self.chat_history = {}

    async def save_chat_history(self):
        """
        将聊天记录保存到文件。
        """
        async with self.lock:
            try:
                with open(self.chat_history_file, "w", encoding="utf-8") as f:
                    json.dump(self.chat_history, f, ensure_ascii=False, indent=4)
                self._dirty_chat_history = False
            except IOError as e:
                logger.error(f"保存聊天记录文件失败: {e}")

    async def _schedule_save(self):
        """
        安排延迟保存，避免频繁写入。
        """
        if self._save_timer is not None:
            self._save_timer.cancel()
        
        self._save_timer = asyncio.create_task(self._delayed_save())

    async def _delayed_save(self):
        """
        延迟保存数据。
        """
        await asyncio.sleep(self._save_delay)
        
        if self._dirty_styles:
            await self.save_styles()
        
        if self._dirty_chat_history:
            await self.save_chat_history()
        
        self._save_timer = None

    async def force_save(self):
        """
        立即保存所有数据。
        """
        if self._save_timer is not None:
            self._save_timer.cancel()
            self._save_timer = None
        
        if self._dirty_styles:
            await self.save_styles()
        
        if self._dirty_chat_history:
            await self.save_chat_history()

    async def perform_maintenance(self, config: dict):
        """
        执行风格维护：衰减和清理操作，最后统一保存。
        
        :param config: 配置字典，包含维护相关参数
        """
        current_time = asyncio.get_running_loop().time()
        decay_rate = config.get("proficiency_decay_rate", 1)
        
        # 执行衰减操作
        for session_id, styles in self.styles.items():
            for style in styles:
                # 简单的线性衰减，可以根据需求调整
                time_since_update = current_time - style.get("last_updated", current_time)
                # 根据维护周期和每日衰减率计算衰减量
                decay_amount = int(time_since_update / 86400) * decay_rate
                if decay_amount > 0:
                    style["proficiency"] = max(0, style.get("proficiency", 0) - decay_amount)
                    style["last_updated"] = current_time
        
        # 清理熟练度为0的风格
        for session_id, styles in self.styles.items():
            self.styles[session_id] = [s for s in styles if s.get("proficiency", 0) > 0]

        # 处理容量限制
        max_styles = config.get("max_styles_per_session", 100)
        for session_id, styles in self.styles.items():
            if len(styles) > max_styles:
                # 按熟练度升序排序，移除最低的
                sorted_styles = sorted(styles, key=lambda s: s.get("proficiency", 0))
                self.styles[session_id] = sorted_styles[-max_styles:]
        
        # 标记需要保存
        self._dirty_styles = True
        await self._schedule_save()

    async def add_message_to_history(self, session_id: str, message: Dict[str, Any]):
        """
        向指定会话添加一条消息记录。

        :param session_id: 会话ID。
        :param message: 消息内容，应包含 'sender', 'content', 'timestamp'。
        """
        if session_id not in self.chat_history:
            self.chat_history[session_id] = []
        self.chat_history[session_id].append(message)
        self._dirty_chat_history = True
        await self._schedule_save()

    def get_chat_history(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取指定会话的聊天记录。

        :param session_id: 会话ID。
        :param limit: 返回的记录条数上限。
        :return: 聊天记录列表。
        """
        return self.chat_history.get(session_id, [])[-limit:]

    async def clear_chat_history(self, session_id: str):
        """
        清空指定会话的聊天记录。

        :param session_id: 会话ID。
        """
        if session_id in self.chat_history:
            self.chat_history[session_id] = []
            self._dirty_chat_history = True
            await self._schedule_save()

    def get_styles_for_session(self, session_id: str) -> List[Dict[str, Any]]:
        """
        获取指定会话的所有风格。

        :param session_id: 会话ID。
        :return: 风格列表。
        """
        return self.styles.get(session_id, [])

    async def add_or_update_style(self, session_id: str, style_content: str, style_type: str):
        """
        添加或更新一个风格。如果风格已存在，则增加其熟练度。

        :param session_id: 会话ID。
        :param style_content: 风格内容。
        :param style_type: 风格类型 ('language_style' 或 'grammar_feature')。
        """
        if session_id not in self.styles:
            self.styles[session_id] = []

        current_time = asyncio.get_running_loop().time()
        
        for style in self.styles[session_id]:
            if style["content"] == style_content and style["type"] == style_type:
                style["proficiency"] = min(100, style.get("proficiency", 0) + 10)  # 熟练度增加，上限100
                style["last_updated"] = current_time
                self._dirty_styles = True
                await self._schedule_save()
                return

        # 如果是新风格
        new_style = {
            "content": style_content,
            "type": style_type,
            "proficiency": 10,  # 初始熟练度
            "created_at": current_time,
            "last_updated": current_time,
        }
        self.styles[session_id].append(new_style)
        self._dirty_styles = True
        await self._schedule_save()