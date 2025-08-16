# -*- coding: utf-8 -*-
import json
import os
from typing import Dict, List, Any
from astrbot.api import logger
import asyncio

# 定义数据存储路径
DATA_DIR = "data/learning_style"
STYLES_FILE = os.path.join(DATA_DIR, "styles.json")
CHAT_HISTORY_FILE = os.path.join(DATA_DIR, "chat_history.json")

class DataManager:
    """
    负责插件数据的加载、保存和管理。
    """
    def __init__(self):
        self.styles: Dict[str, List[Dict[str, Any]]] = {}
        self.chat_history: Dict[str, List[Dict[str, Any]]] = {}
        self._ensure_data_dir()
        self.load_styles()
        self.load_chat_history()
        self.lock = asyncio.Lock()

    def _ensure_data_dir(self):
        """
        确保数据目录存在。
        """
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
            logger.info(f"创建数据目录: {DATA_DIR}")

    def load_styles(self):
        """
        从文件加载学习到的风格。
        """
        if os.path.exists(STYLES_FILE):
            try:
                with open(STYLES_FILE, "r", encoding="utf-8") as f:
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
                with open(STYLES_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.styles, f, ensure_ascii=False, indent=4)
            except IOError as e:
                logger.error(f"保存风格文件失败: {e}")

    def load_chat_history(self):
        """
        从文件加载聊天记录。
        """
        if os.path.exists(CHAT_HISTORY_FILE):
            try:
                with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as f:
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
                with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.chat_history, f, ensure_ascii=False, indent=4)
            except IOError as e:
                logger.error(f"保存聊天记录文件失败: {e}")

    async def add_message_to_history(self, session_id: str, message: Dict[str, Any]):
        """
        向指定会话添加一条消息记录。

        :param session_id: 会话ID。
        :param message: 消息内容，应包含 'sender', 'content', 'timestamp'。
        """
        if session_id not in self.chat_history:
            self.chat_history[session_id] = []
        self.chat_history[session_id].append(message)
        await self.save_chat_history()

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
            await self.save_chat_history()

    def get_styles_for_session(self, session_id: str) -> List[Dict[str, Any]]:
        """
        获取指定会話的所有风格。

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

        for style in self.styles[session_id]:
            if style["content"] == style_content and style["type"] == style_type:
                style["proficiency"] = min(100, style.get("proficiency", 0) + 10)  # 熟练度增加，上限100
                style["last_updated"] = asyncio.get_event_loop().time()
                await self.save_styles()
                return

        # 如果是新风格
        new_style = {
            "content": style_content,
            "type": style_type,
            "proficiency": 10,  # 初始熟练度
            "created_at": asyncio.get_event_loop().time(),
            "last_updated": asyncio.get_event_loop().time(),
        }
        self.styles[session_id].append(new_style)
        await self.save_styles()