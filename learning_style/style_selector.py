from typing import Any


class StyleSelector:
    """将各类表征列表构建成人类可读的提示文本。"""

    @staticmethod
    def build_style_text(label: str, contents: list[str]) -> str:
        if not contents:
            return ""
        return f"{label}：{'、'.join(contents)}"

    @staticmethod
    def build_contextual_text(contextuals: list[dict[str, Any]]) -> str:
        """
        将情境表征列表构建为提示文本。

        :param contextuals: [{scene, behavior}, ...]
        :return: "情境提示：场景1→行为1；场景2→行为2"
        """
        if not contextuals:
            return ""
        parts = [
            f"{t['scene']}→{t['behavior']}"
            for t in contextuals
            if t.get("scene") and t.get("behavior")
        ]
        if not parts:
            return ""
        return f"情境提示：{'；'.join(parts)}"
