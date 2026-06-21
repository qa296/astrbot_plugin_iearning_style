import re
from typing import Any

from astrbot.api import logger

from .style_selector import StyleSelector


class StyleInjector:
    """
    负责将学习到的表征注入到 LLM 的 system prompt 中。
    - 通用表征：全部注入
    - 特定表征：用 trigger_regex 匹配当前用户消息，命中的注入
    """

    def __init__(self, data_manager, config: dict[str, Any]):
        self.data_manager = data_manager
        self.config = config
        self.style_selector = StyleSelector()

    def should_inject_style(self, session_id: str) -> bool:
        """判断是否应该为该会话注入风格。"""
        if not self.config.get("enable_style_injection", True):
            return False

        universal = self.data_manager.get_universal_for_session(session_id)
        specific = self.data_manager.get_specific_for_session(session_id)
        return bool(universal) or bool(specific)

    def inject_style_to_prompt(
        self, session_id: str, original_system_prompt: str, user_message: str = ""
    ) -> str:
        """
        将表征注入到 system prompt 中。

        :param session_id: 会话 ID
        :param original_system_prompt: 原始的 system prompt
        :param user_message: 当前用户消息，用于匹配特定表征的 trigger_regex
        :return: 注入后的 system prompt
        """
        if not self.should_inject_style(session_id):
            return original_system_prompt

        try:
            style_parts = []

            # 通用表征：全部注入
            universal = self.data_manager.get_universal_for_session(session_id)
            if universal:
                universal_contents = [t["content"] for t in universal]
                style_parts.append(
                    self.style_selector.build_style_text(
                        "通用风格", universal_contents
                    )
                )

            # 特定表征：按 trigger_regex 匹配当前消息
            specific = self.data_manager.get_specific_for_session(session_id)
            matched_specific = []
            for trait in specific:
                regex = trait.get("trigger_regex", "")
                content = trait.get("content", "")
                if regex and content and user_message:
                    try:
                        if re.search(regex, user_message):
                            matched_specific.append(content)
                    except re.error:
                        continue

            if matched_specific and user_message:
                style_parts.append(
                    self.style_selector.build_style_text(
                        "当前话题相关说法", matched_specific
                    )
                )

            if not style_parts:
                return original_system_prompt

            style_text = "；".join(style_parts)
            full_style_text = f"在回复时，请尽量采用以下风格特点：{style_text}"

            if not original_system_prompt.strip():
                return full_style_text

            separator = "\n\n"
            new_prompt = f"{original_system_prompt}{separator}{full_style_text}"
            logger.debug(f"为会话 {session_id} 注入风格提示")
            return new_prompt

        except Exception as e:
            logger.error(f"注入风格时发生错误: {e}")
            return original_system_prompt

    def get_style_summary(self, session_id: str) -> dict[str, Any]:
        """获取会话的风格摘要信息（方案 A：合并显示）。"""
        universal = self.data_manager.get_universal_for_session(session_id)
        specific = self.data_manager.get_specific_for_session(session_id)

        total = len(universal) + len(specific)

        if total == 0:
            return {
                "has_styles": False,
                "total_styles": 0,
                "universal_count": 0,
                "specific_count": 0,
                "universal_preview": [],
                "specific_preview": [],
            }

        # 通用取 Top-3，特定取 Top-3
        universal_preview = [t["content"] for t in universal[:3]]
        specific_sorted = sorted(
            specific, key=lambda t: t.get("trigger_count", 0), reverse=True
        )
        specific_preview = [
            t["content"] for t in specific_sorted[:3]
        ]

        return {
            "has_styles": True,
            "total_styles": total,
            "universal_count": len(universal),
            "specific_count": len(specific),
            "universal_preview": universal_preview,
            "specific_preview": specific_preview,
        }
