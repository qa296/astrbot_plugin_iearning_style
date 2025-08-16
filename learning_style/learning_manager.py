# -*- coding: utf-8 -*-
import json
from typing import Dict, List, Any
from astrbot.api import logger
from astrbot.api.star import Star
from .data_manager import DataManager

class LearningManager:
    """
    负责调用LLM进行学习和总结。
    """
    def __init__(self, star_instance: Star, data_manager: DataManager, config: dict):
        self.star = star_instance
        self.context = star_instance.context
        self.data_manager = data_manager
        self.config = config

    async def analyze_and_learn(self, session_id: str):
        """
        分析指定会话的聊天记录，并学习其说话风格。

        :param session_id: 会话ID。
        """
        min_history = self.config.get("min_history_for_analysis", 10)
        chat_history = self.data_manager.get_chat_history(session_id, limit=100)
        if len(chat_history) < min_history:  # 聊天记录过少，不进行分析
            return

        # 构建prompt
        prompt = self._build_prompt(chat_history)

        try:
            # 调用LLM
            llm_response = await self.context.get_using_provider().text_chat(
                prompt=prompt,
                contexts=[],
                system_prompt="你是一个语言风格分析大师，请根据以下聊天记录，总结语言风格和语法句式特点。"
            )

            if llm_response.role == "assistant":
                # 解析并存储学习结果
                await self._parse_and_store_results(session_id, llm_response.completion_text)
                # 分析完成后清空当前会话的聊天记录，避免重复分析
                await self.data_manager.clear_chat_history(session_id)
            else:
                logger.warning(f"LLM调用失败或返回非预期的角色: {llm_response.role}")

        except Exception as e:
            logger.error(f"分析学习过程中发生错误: {e}")

    def _build_prompt(self, chat_history: List[Dict[str, Any]]) -> str:
        """
        根据聊天记录构建用于LLM分析的prompt。

        :param chat_history: 聊天记录列表。
        :return: 构建好的prompt字符串。
        """
        history_str = "\n".join([f"{msg['sender']}: {msg['content']}" for msg in chat_history])
        prompt = f"""
        请分析以下聊天记录：
        ---
        {history_str}
        ---
        请总结出其中体现的语言风格和语法句式特点。
        请以JSON格式返回，包含两个键 'language_style' 和 'grammar_feature'，
        每个键对应一个字符串列表，其中包含具体的风格或特点描述。
        例如：
        {{
            "language_style": ["喜欢使用emoji", "经常使用网络流行语"],
            "grammar_feature": ["句子偏短", "偶尔使用倒装句"]
        }}
        """
        return prompt

    async def _parse_and_store_results(self, session_id: str, llm_output: str):
        """
        解析LLM的输出，并存储学习到的风格。

        :param session_id: 会话ID。
        :param llm_output: LLM返回的文本内容。
        """
        try:
            # 尝试从LLM输出中提取JSON
            json_str = llm_output[llm_output.find('{'):llm_output.rfind('}')+1]
            results = json.loads(json_str)
            
            language_styles = results.get("language_style", [])
            grammar_features = results.get("grammar_feature", [])

            for style in language_styles:
                await self.data_manager.add_or_update_style(session_id, style, "language_style")
            
            for feature in grammar_features:
                await self.data_manager.add_or_update_style(session_id, feature, "grammar_feature")

            logger.info(f"为会话 {session_id} 学习到新的风格和特点。")

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"解析LLM输出失败: {e}\n原始输出: {llm_output}")