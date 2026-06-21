import asyncio
import difflib
import json
import os
import re
from typing import Any

from astrbot.api import logger


class DataManager:
    """
    负责插件数据的加载、保存和管理。
    维护两套独立表征：通用表征（stable，LLM 全量重写）和特定表征（per-round，trigger_regex 匹配）。
    """

    def __init__(self, data_dir: str, config: dict):
        self.data_dir = data_dir
        self.universal_file = os.path.join(data_dir, "universal.json")
        self.specific_file = os.path.join(data_dir, "specific.json")
        self.chat_history_file = os.path.join(data_dir, "chat_history.json")

        self.universal: dict[str, list[dict[str, Any]]] = {}
        self.specific: dict[str, list[dict[str, Any]]] = {}
        self.chat_history: dict[str, list[dict[str, Any]]] = {}

        self.config = config

        self._ensure_data_dir()
        self._handle_old_format()
        self.load_universal()
        self.load_specific()
        self.load_chat_history()
        self.lock = asyncio.Lock()

        # 批量保存
        self._dirty_universal = False
        self._dirty_specific = False
        self._dirty_chat_history = False
        self._save_timer = None
        self._save_delay = 5.0

    def _ensure_data_dir(self):
        """确保数据目录存在。"""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            logger.info(f"创建数据目录: {self.data_dir}")

    def _handle_old_format(self):
        """检测旧版 styles.json，检测到则重命名备份，从零开始。"""
        old_file = os.path.join(self.data_dir, "styles.json")
        if os.path.exists(old_file):
            logger.warning(
                "检测到旧版数据格式 (styles.json)，已重命名为 styles.json.bak，将使用新存储结构"
            )
            os.rename(old_file, old_file + ".bak")

    # ==================== 通用表征 ====================

    def load_universal(self):
        """从文件加载通用表征。"""
        if os.path.exists(self.universal_file):
            try:
                with open(self.universal_file, encoding="utf-8") as f:
                    self.universal = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"加载通用表征文件失败: {e}")
                self.universal = {}
        else:
            self.universal = {}

    def get_universal_for_session(self, session_id: str) -> list[dict[str, Any]]:
        """获取指定会话的所有通用表征。"""
        return self.universal.get(session_id, [])

    def replace_universal(self, session_id: str, contents: list[str]):
        """
        全量替换通用表征（由 LearningManager 在 LLM 分析后调用）。
        - 延续的表征 proficiency +5，confirmed_rounds +1
        - 新增的表征 proficiency=10，confirmed_rounds=1
        - 不出现在 contents 中的表征自动消亡
        """
        current_time = asyncio.get_running_loop().time()
        old_map = {}
        for trait in self.universal.get(session_id, []):
            old_map[trait["content"]] = trait

        new_traits = []
        for content in contents:
            if content in old_map:
                old = old_map[content]
                new_traits.append({
                    "content": content,
                    "proficiency": min(100, old.get("proficiency", 0) + 5),
                    "confirmed_rounds": old.get("confirmed_rounds", 0) + 1,
                    "last_updated": current_time,
                })
            else:
                new_traits.append({
                    "content": content,
                    "proficiency": 10,
                    "confirmed_rounds": 1,
                    "last_updated": current_time,
                })

        self.universal[session_id] = new_traits
        self._dirty_universal = True
        asyncio.create_task(self._schedule_save())

    async def save_universal(self):
        """将通用表征保存到文件。"""
        async with self.lock:
            try:
                with open(self.universal_file, "w", encoding="utf-8") as f:
                    json.dump(self.universal, f, ensure_ascii=False, indent=4)
                self._dirty_universal = False
            except OSError as e:
                logger.error(f"保存通用表征文件失败: {e}")

    # ==================== 特定表征 ====================

    def load_specific(self):
        """从文件加载特定表征。"""
        if os.path.exists(self.specific_file):
            try:
                with open(self.specific_file, encoding="utf-8") as f:
                    self.specific = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"加载特定表征文件失败: {e}")
                self.specific = {}
        else:
            self.specific = {}

    def get_specific_for_session(self, session_id: str) -> list[dict[str, Any]]:
        """获取指定会话的所有特定表征。"""
        return self.specific.get(session_id, [])

    def add_or_update_specific(
        self, session_id: str, content: str, trigger_regex: str
    ):
        """
        添加或更新一个特定表征。
        - 验证 trigger_regex 合法性
        - 如果 content 已存在，trigger_count +1
        - 否则追加新条目
        """
        try:
            re.compile(trigger_regex)
        except re.error as e:
            logger.error(
                f"特定表征 '{content}' 的正则表达式无效: {trigger_regex}, 错误: {e}"
            )
            return

        current_time = asyncio.get_running_loop().time()
        if session_id not in self.specific:
            self.specific[session_id] = []

        for trait in self.specific[session_id]:
            if trait["content"] == content:
                trait["trigger_count"] = trait.get("trigger_count", 0) + 1
                trait["last_seen"] = current_time
                self._dirty_specific = True
                asyncio.create_task(self._schedule_save())
                return

        self.specific[session_id].append({
            "content": content,
            "trigger_regex": trigger_regex,
            "trigger_count": 1,
            "first_seen": current_time,
            "last_seen": current_time,
        })
        self._dirty_specific = True
        asyncio.create_task(self._schedule_save())

    def get_specific_for_promotion(
        self, session_id: str, threshold: int
    ) -> list[dict[str, Any]]:
        """获取达到升格阈值的特定表征。"""
        return [
            t
            for t in self.specific.get(session_id, [])
            if t.get("trigger_count", 0) >= threshold
        ]

    def remove_lowest_specific(self, session_id: str, count: int):
        """
        按 trigger_count 升序移除最低的 count 条特定表征。
        """
        if session_id not in self.specific or count <= 0:
            return
        traits = sorted(
            self.specific[session_id], key=lambda t: t.get("trigger_count", 0)
        )
        self.specific[session_id] = traits[count:]
        self._dirty_specific = True
        asyncio.create_task(self._schedule_save())

    def merge_similar_specific(self, session_id: str, threshold: float = 0.85):
        """
        合并相似的特定表征（基于 difflib 文本相似度）。
        合并时 trigger_count 相加，trigger_regex 合并。
        """
        if session_id not in self.specific or len(self.specific[session_id]) < 2:
            return

        traits = self.specific[session_id]
        merged = []
        used: set[int] = set()

        for i, a in enumerate(traits):
            if i in used:
                continue
            best = None
            best_score = 0.0
            for j, b in enumerate(traits):
                if i == j or j in used:
                    continue
                score = difflib.SequenceMatcher(
                    None, a["content"], b["content"]
                ).ratio()
                if score > threshold and score > best_score:
                    best = j
                    best_score = score

            if best is not None:
                b = traits[best]
                a["trigger_count"] = (
                    a.get("trigger_count", 0) + b.get("trigger_count", 0)
                )
                a["last_seen"] = max(
                    a.get("last_seen", 0), b.get("last_seen", 0)
                )
                regexes = [
                    a.get("trigger_regex", ""),
                    b.get("trigger_regex", ""),
                ]
                regexes = [r for r in regexes if r]
                a["trigger_regex"] = (
                    "|".join(regexes) if len(regexes) > 1 else regexes[0]
                )
                used.add(best)
                used.add(i)
                merged.append(a)
            else:
                if i not in used:
                    merged.append(a)
                    used.add(i)

        self.specific[session_id] = merged
        self._dirty_specific = True
        asyncio.create_task(self._schedule_save())

    def check_specific_capacity(self, session_id: str):
        """
        检查特定表征容量，超限则淘汰 trigger_count 最低的。
        """
        max_specific = self.config.get("max_specific_per_session", 200)
        if session_id in self.specific and len(self.specific[session_id]) > max_specific:
            excess = len(self.specific[session_id]) - max_specific
            self.remove_lowest_specific(session_id, excess)

    async def save_specific(self):
        """将特定表征保存到文件。"""
        async with self.lock:
            try:
                with open(self.specific_file, "w", encoding="utf-8") as f:
                    json.dump(self.specific, f, ensure_ascii=False, indent=4)
                self._dirty_specific = False
            except OSError as e:
                logger.error(f"保存特定表征文件失败: {e}")

    # ==================== 公共保存逻辑 ====================

    async def _schedule_save(self):
        """安排延迟保存，避免频繁写入。"""
        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = asyncio.create_task(self._delayed_save())

    async def _delayed_save(self):
        """延迟保存脏数据。"""
        await asyncio.sleep(self._save_delay)
        if self._dirty_universal:
            await self.save_universal()
        if self._dirty_specific:
            await self.save_specific()
        if self._dirty_chat_history:
            await self.save_chat_history()
        self._save_timer = None

    async def force_save(self):
        """立即保存所有脏数据。"""
        if self._save_timer is not None:
            self._save_timer.cancel()
            self._save_timer = None
        if self._dirty_universal:
            await self.save_universal()
        if self._dirty_specific:
            await self.save_specific()
        if self._dirty_chat_history:
            await self.save_chat_history()

    # ==================== 聊天记录（不变） ====================

    def load_chat_history(self):
        """从文件加载聊天记录。"""
        if os.path.exists(self.chat_history_file):
            try:
                with open(self.chat_history_file, encoding="utf-8") as f:
                    self.chat_history = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"加载聊天记录文件失败: {e}")
                self.chat_history = {}
        else:
            self.chat_history = {}

    async def save_chat_history(self):
        """将聊天记录保存到文件。"""
        async with self.lock:
            try:
                with open(self.chat_history_file, "w", encoding="utf-8") as f:
                    json.dump(self.chat_history, f, ensure_ascii=False, indent=4)
                self._dirty_chat_history = False
            except OSError as e:
                logger.error(f"保存聊天记录文件失败: {e}")

    async def add_message_to_history(self, session_id: str, message: dict[str, Any]):
        """向指定会话添加一条消息记录。"""
        if session_id not in self.chat_history:
            self.chat_history[session_id] = []
        self.chat_history[session_id].append(message)
        self._dirty_chat_history = True
        await self._schedule_save()

    def get_chat_history(
        self, session_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """获取指定会话的聊天记录。"""
        return self.chat_history.get(session_id, [])[-limit:]

    async def clear_chat_history(self, session_id: str):
        """清空指定会话的聊天记录。"""
        if session_id in self.chat_history:
            self.chat_history[session_id] = []
            self._dirty_chat_history = True
            await self._schedule_save()
