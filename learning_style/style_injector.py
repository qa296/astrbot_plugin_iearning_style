from typing import Any

from astrbot.api import logger

from .style_selector import StyleSelector


class StyleInjector:
    """
    三层表征注入：
    - 通用：全部注入
    - 情境：全部注入（LLM 自行判断场景匹配）
    - 特定：全部注入（LLM 自行判断使用时机）
    """

    def __init__(self, data_manager, config: dict[str, Any]):
        self.data_manager = data_manager
        self.config = config
        self.style_selector = StyleSelector()

    def should_inject_style(self, session_id: str) -> bool:
        if not self.config.get("enable_style_injection", True):
            return False

        universal = self.data_manager.get_universal_for_session(session_id)
        contextual = self.data_manager.get_contextual_for_session(session_id)
        specific = self.data_manager.get_specific_for_session(session_id)
        return bool(universal) or bool(contextual) or bool(specific)

    def inject_style_to_prompt(
        self, session_id: str, original_system_prompt: str
    ) -> str:
        if not self.should_inject_style(session_id):
            return original_system_prompt

        try:
            style_parts = []

            # 1. 通用表征：全部注入
            universal = self.data_manager.get_universal_for_session(session_id)
            if universal:
                contents = [t["content"] for t in universal]
                style_parts.append(
                    self.style_selector.build_style_text("通用风格", contents)
                )

            # 2. 情境表征：全部注入
            contextual = self.data_manager.get_contextual_for_session(session_id)
            if contextual:
                style_parts.append(
                    self.style_selector.build_contextual_text(contextual)
                )

            # 3. 特定表征：全部注入，LLM 自行判断使用时机
            specific = self.data_manager.get_specific_for_session(session_id)
            if specific:
                contents = [t["content"] for t in specific]
                style_parts.append(
                    self.style_selector.build_style_text("群内流行说法", contents)
                )

            if not style_parts:
                return original_system_prompt

            style_text = "；".join(style_parts)
            full_style_text = f"在回复时，请尽量采用以下风格特点：{style_text}"

            if not original_system_prompt.strip():
                return full_style_text

            new_prompt = f"{original_system_prompt}\n\n{full_style_text}"
            logger.debug(f"为会话 {session_id} 注入风格提示")
            return new_prompt

        except Exception as e:
            logger.error(f"注入风格时发生错误: {e}")
            return original_system_prompt

    def get_style_summary(self, session_id: str) -> dict[str, Any]:
        universal = self.data_manager.get_universal_for_session(session_id)
        contextual = self.data_manager.get_contextual_for_session(session_id)
        specific = self.data_manager.get_specific_for_session(session_id)

        total = len(universal) + len(contextual) + len(specific)

        if total == 0:
            return {
                "has_styles": False,
                "total_styles": 0,
                "universal_count": 0,
                "contextual_count": 0,
                "specific_count": 0,
                "universal_preview": [],
                "contextual_preview": [],
                "specific_preview": [],
            }

        universal_preview = [t["content"] for t in universal[:3]]
        contextual_preview = [
            f"{t['scene']}→{t['behavior']}" for t in contextual[:3]
        ]
        specific_sorted = sorted(
            specific, key=lambda t: t.get("trigger_count", 0), reverse=True
        )
        specific_preview = [t["content"] for t in specific_sorted[:3]]

        return {
            "has_styles": True,
            "total_styles": total,
            "universal_count": len(universal),
            "contextual_count": len(contextual),
            "specific_count": len(specific),
            "universal_preview": universal_preview,
            "contextual_preview": contextual_preview,
            "specific_preview": specific_preview,
        }
