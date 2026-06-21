from typing import Any


class StyleSelector:
    """
    负责将表征列表构建成人类可读的提示文本。
    不再需要加权随机选择——通用全部注入，特定按 regex 匹配。
    """

    @staticmethod
    def build_style_text(label: str, contents: list[str]) -> str:
        """
        将表征列表构建成文本。

        :param label: 分类标签（如"通用风格"、"当前话题相关说法"）
        :param contents: 表征内容列表
        :return: 格式化文本
        """
        if not contents:
            return ""
        return f"{label}：{'、'.join(contents)}"
