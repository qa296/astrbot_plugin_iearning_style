import asyncio
import difflib
import json
import os
import re
from typing import Any

from astrbot.api import logger


# 情境表征缓冲比例（硬编码）
CONTEXTUAL_BUFFER_RATIO = 0.2  # 20% 为缓冲位


class DataManager:
    """
    三层表征管理：
    - 通用（universal）：稳定风格基调，LLM 全量重写
    - 情境（contextual）：场景→行为模式，FIFO 容量管理 + 缓冲合并
    - 特定（specific）：梗+释义，trigger_regex 匹配
    """

    def __init__(self, data_dir: str, config: dict):
        self.data_dir = data_dir
        self.universal_file = os.path.join(data_dir, "universal.json")
        self.contextual_file = os.path.join(data_dir, "contextual.json")
        self.specific_file = os.path.join(data_dir, "specific.json")
        self.chat_history_file = os.path.join(data_dir, "chat_history.json")

        self.universal: dict[str, list[dict[str, Any]]] = {}
        self.contextual: dict[str, list[dict[str, Any]]] = {}
        self.specific: dict[str, list[dict[str, Any]]] = {}
        self.chat_history: dict[str, list[dict[str, Any]]] = {}

        self.config = config

        self._ensure_data_dir()
        self._handle_old_format()
        self.load_universal()
        self.load_contextual()
        self.load_specific()
        self.load_chat_history()
        self.lock = asyncio.Lock()

        self._dirty_universal = False
        self._dirty_contextual = False
        self._dirty_specific = False
        self._dirty_chat_history = False
        self._save_timer = None
        self._save_delay = 5.0

    def _ensure_data_dir(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            logger.info(f"创建数据目录: {self.data_dir}")

    def _handle_old_format(self):
        old_file = os.path.join(self.data_dir, "styles.json")
        if os.path.exists(old_file):
            logger.warning(
                "检测到旧版数据格式 (styles.json)，已重命名为 styles.json.bak，将使用新三层存储结构"
            )
            os.rename(old_file, old_file + ".bak")

    # ==================== 通用表征 ====================

    def load_universal(self):
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
        return self.universal.get(session_id, [])

    def replace_universal(self, session_id: str, contents: list[str]):
        """
        全量替换通用表征。
        - 延续的表征 proficiency +5，confirmed_rounds +1
        - 新增的表征 proficiency=10，confirmed_rounds=1
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
        async with self.lock:
            try:
                with open(self.universal_file, "w", encoding="utf-8") as f:
                    json.dump(self.universal, f, ensure_ascii=False, indent=4)
                self._dirty_universal = False
            except OSError as e:
                logger.error(f"保存通用表征文件失败: {e}")

    # ==================== 情境表征 ====================

    def load_contextual(self):
        if os.path.exists(self.contextual_file):
            try:
                with open(self.contextual_file, encoding="utf-8") as f:
                    self.contextual = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"加载情境表征文件失败: {e}")
                self.contextual = {}
        else:
            self.contextual = {}

    def get_contextual_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return self.contextual.get(session_id, [])

    def get_contextual_buffer(self, session_id: str) -> list[dict[str, Any]]:
        """仅返回缓冲位中的情境表征（供维护合并用）。"""
        return [
            t
            for t in self.contextual.get(session_id, [])
            if t.get("_in_buffer")
        ]

    def add_contextual(self, session_id: str, scene: str, behavior: str):
        """
        添加情境表征。
        - FIFO 添加，标记为缓冲位
        - 超容量 50 时淘汰最早的
        - 自动调整缓冲位标记（最新 20% 为缓冲）
        """
        current_time = asyncio.get_running_loop().time()
        if session_id not in self.contextual:
            self.contextual[session_id] = []

        self.contextual[session_id].append({
            "scene": scene,
            "behavior": behavior,
            "created_at": current_time,
            "_in_buffer": True,
        })

        # FIFO 容量检查
        max_capacity = self.config.get("max_contextual_per_session", 50)
        while len(self.contextual[session_id]) > max_capacity:
            removed = self.contextual[session_id].pop(0)
            logger.debug(
                f"FIFO 淘汰情境表征: {removed.get('scene', '?')}→{removed.get('behavior', '?')}"
            )

        # 重新标记缓冲位（最新 20%）
        self._refresh_buffer_markers(session_id)
        self._dirty_contextual = True
        asyncio.create_task(self._schedule_save())

    def _refresh_buffer_markers(self, session_id: str):
        """重新计算并标记情境表征的缓冲位。"""
        traits = self.contextual.get(session_id, [])
        if not traits:
            return
        buffer_count = max(1, int(len(traits) * CONTEXTUAL_BUFFER_RATIO))
        for i, t in enumerate(traits):
            t["_in_buffer"] = (i >= len(traits) - buffer_count)

    def mark_contextual_merged(self, session_id: str, index: int):
        """从情境列表中移除已合并的条目。"""
        if session_id in self.contextual and 0 <= index < len(self.contextual[session_id]):
            self.contextual[session_id].pop(index)
            self._refresh_buffer_markers(session_id)
            self._dirty_contextual = True
            asyncio.create_task(self._schedule_save())

    def merge_contextual_buffer(self, session_id: str, threshold: float = 0.85):
        """
        将缓冲位的情境表征尝试合并到通用/特定。
        遍历缓冲条目，按 scene→behavior 文本相似度：
        1. 跟通用比对 → 匹配则合并proficiency，从情境移除
        2. 跟特定比对 → 匹配则合并trigger_count，从情境移除
        3. 都不匹配 → 留在缓冲
        """
        if session_id not in self.contextual:
            return

        remaining = []
        for item in self.contextual[session_id]:
            if not item.get("_in_buffer"):
                remaining.append(item)
                continue

            text = f"{item['scene']}→{item['behavior']}"
            merged = False

            # 尝试合并到通用
            if session_id in self.universal:
                for u in self.universal[session_id]:
                    score = difflib.SequenceMatcher(None, text, u["content"]).ratio()
                    if score > threshold:
                        u["proficiency"] = min(100, u.get("proficiency", 0) + 5)
                        merged = True
                        logger.debug(f"情境 '{text}' 合并到通用 '{u['content']}'")
                        break

            if merged:
                continue

            # 尝试合并到特定
            if session_id in self.specific:
                for s in self.specific[session_id]:
                    score = difflib.SequenceMatcher(
                        None, text, s["content"]
                    ).ratio()
                    if score > threshold:
                        s["trigger_count"] = s.get("trigger_count", 0) + 1
                        merged = True
                        logger.debug(f"情境 '{text}' 合并到特定 '{s['content']}'")
                        break

            if not merged:
                remaining.append(item)

        self.contextual[session_id] = remaining
        self._refresh_buffer_markers(session_id)
        self._dirty_contextual = True
        asyncio.create_task(self._schedule_save())

    async def save_contextual(self):
        async with self.lock:
            try:
                with open(self.contextual_file, "w", encoding="utf-8") as f:
                    json.dump(self.contextual, f, ensure_ascii=False, indent=4)
                self._dirty_contextual = False
            except OSError as e:
                logger.error(f"保存情境表征文件失败: {e}")

    # ==================== 特定表征 ====================

    def load_specific(self):
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
        return self.specific.get(session_id, [])

    def add_or_update_specific(
        self, session_id: str, content: str, trigger_regex: str
    ):
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
        return [
            t
            for t in self.specific.get(session_id, [])
            if t.get("trigger_count", 0) >= threshold
        ]

    def remove_lowest_specific(self, session_id: str, count: int):
        if session_id not in self.specific or count <= 0:
            return
        traits = sorted(
            self.specific[session_id], key=lambda t: t.get("trigger_count", 0)
        )
        self.specific[session_id] = traits[count:]
        self._dirty_specific = True
        asyncio.create_task(self._schedule_save())

    def check_specific_capacity(self, session_id: str):
        max_specific = self.config.get("max_specific_per_session", 200)
        if session_id in self.specific and len(self.specific[session_id]) > max_specific:
            excess = len(self.specific[session_id]) - max_specific
            self.remove_lowest_specific(session_id, excess)

    async def save_specific(self):
        async with self.lock:
            try:
                with open(self.specific_file, "w", encoding="utf-8") as f:
                    json.dump(self.specific, f, ensure_ascii=False, indent=4)
                self._dirty_specific = False
            except OSError as e:
                logger.error(f"保存特定表征文件失败: {e}")

    # ==================== 公共保存逻辑 ====================

    async def _schedule_save(self):
        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = asyncio.create_task(self._delayed_save())

    async def _delayed_save(self):
        await asyncio.sleep(self._save_delay)
        if self._dirty_universal:
            await self.save_universal()
        if self._dirty_contextual:
            await self.save_contextual()
        if self._dirty_specific:
            await self.save_specific()
        if self._dirty_chat_history:
            await self.save_chat_history()
        self._save_timer = None

    async def force_save(self):
        if self._save_timer is not None:
            self._save_timer.cancel()
            self._save_timer = None
        if self._dirty_universal:
            await self.save_universal()
        if self._dirty_contextual:
            await self.save_contextual()
        if self._dirty_specific:
            await self.save_specific()
        if self._dirty_chat_history:
            await self.save_chat_history()

    # ==================== 聊天记录 ====================

    def load_chat_history(self):
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
        async with self.lock:
            try:
                with open(self.chat_history_file, "w", encoding="utf-8") as f:
                    json.dump(self.chat_history, f, ensure_ascii=False, indent=4)
                self._dirty_chat_history = False
            except OSError as e:
                logger.error(f"保存聊天记录文件失败: {e}")

    async def add_message_to_history(self, session_id: str, message: dict[str, Any]):
        if session_id not in self.chat_history:
            self.chat_history[session_id] = []
        self.chat_history[session_id].append(message)
        self._dirty_chat_history = True
        await self._schedule_save()

    def get_chat_history(
        self, session_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        return self.chat_history.get(session_id, [])[-limit:]

    async def clear_chat_history(self, session_id: str):
        if session_id in self.chat_history:
            self.chat_history[session_id] = []
            self._dirty_chat_history = True
            await self._schedule_save()
