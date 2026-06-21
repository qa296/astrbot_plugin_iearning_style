import json
import re
from typing import Any

from astrbot.api import logger
from astrbot.api.star import Star

from .data_manager import DataManager


class LearningManager:
    """
    负责调用 LLM 进行学习和总结。
    输入：[本轮对话] + [上轮通用表征] + [待升格特定表征提示]
    输出：{universal: [...], specific: [{content, trigger_regex}, ...]}
    """

    def __init__(self, star_instance: Star, data_manager: DataManager, config: dict):
        self.star = star_instance
        self.context = star_instance.context
        self.data_manager = data_manager
        self.config = config

    async def analyze_and_learn(self, session_id: str):
        """
        分析指定会话的聊天记录，提取通用和特定表征。
        """
        min_history = self.config.get("min_history_for_analysis", 10)
        chat_history = self.data_manager.get_chat_history(session_id, limit=100)
        if len(chat_history) < min_history:
            return

        # 构建 prompt
        prompt = self._build_prompt(session_id, chat_history)

        try:
            llm_response = await self.context.get_using_provider().text_chat(
                prompt=prompt,
                contexts=[],
                system_prompt="你是一个语言风格分析大师，请根据以下聊天记录，提取通用风格和特定说法。",
            )

            if llm_response.role == "assistant":
                await self._parse_and_store_results(
                    session_id, llm_response.completion_text
                )
                await self.data_manager.clear_chat_history(session_id)
            else:
                logger.warning(f"LLM 调用失败或返回非预期的角色: {llm_response.role}")

        except Exception as e:
            logger.error(f"分析学习过程中发生错误: {e}")

    def _build_prompt(
        self, session_id: str, chat_history: list[dict[str, Any]]
    ) -> str:
        """
        构建 LLM 分析 prompt。
        - 包含本轮聊天记录
        - 如果已有通用表征，附加上一轮结果供 LLM 重写
        - 如果有待升格的特定表征，附加提示
        """
        history_str = "\n".join(
            [f"{msg['sender']}: {msg['content']}" for msg in chat_history]
        )

        # 获取上一轮通用表征
        universal = self.data_manager.get_universal_for_session(session_id)
        universal_str = ""
        if universal:
            contents = [t["content"] for t in universal]
            universal_str = "\n".join([f"- {c}" for c in contents])
        else:
            universal_str = "(无)"

        # 获取待升格的特定表征
        threshold = self.config.get("specific_promotion_threshold", 5)
        promotion_candidates = self.data_manager.get_specific_for_promotion(
            session_id, threshold
        )
        promotion_str = ""
        if promotion_candidates:
            lines = [
                f"- {t['content']} (触发 {t['trigger_count']} 次)"
                for t in promotion_candidates
            ]
            promotion_str = "\n".join(lines)

        first_round = not bool(universal)

        if first_round:
            # 第一轮：无历史通用，全产出通用
            prompt = f"""
请分析以下聊天记录，提取语言特征。

聊天记录：
```
{history_str}
```

要求：
1. 只返回有效的 JSON，不要包含任何解释性文字
2. 格式：
{{
  "universal": ["特征1", "特征2"],
  "specific": []
}}
3. universal 是从聊天中观察到的稳定语言风格特征（用词习惯、语气、句式等）
4. 每条特征描述简洁明了，不超过 20 个字
5. universal 至少包含 1 条，最多 10 条
6. specific 在第一轮固定为空数组

示例输出：
{{"universal": ["语气活泼", "爱用短句", "喜欢加表情"], "specific": []}}
"""
        else:
            # 后续轮次：带上轮通用 + 待升格提示
            promotion_section = ""
            if promotion_str:
                promotion_section = f"""
以下特征频繁出现（触发次数≥{threshold}），请考虑是否应纳入通用：
{promotion_str}
"""

            prompt = f"""
请分析以下聊天记录，提取两类特征。

聊天记录：
```
{history_str}
```

上一轮已确认的通用风格：
{universal_str}

{promotion_section}
要求：
1. 只返回有效的 JSON，不要包含任何解释性文字
2. 格式：
{{
  "universal": ["特征1", "特征2"],
  "specific": [
    {{"content": "特征描述", "trigger_regex": "触发正则"}},
    ...
  ]
}}
3. universal 是稳定风格特征，应从"上一轮通用"中保留合适的并可以加入新的
4. specific 是仅本轮出现的具体说法/梗/流行语
5. trigger_regex 是能匹配用户相关表达的正则表达式（如 "awsl" 对应 "awsl|啊我死了"）
6. trigger_regex 必须是合法正则
7. 每条特征描述不超过 20 个字

示例输出：
{{"universal": ["语气活泼", "喜欢玩梗"], "specific": [{{"content": "awsl", "trigger_regex": "awsl|啊我死了"}}]}}
"""
        return prompt

    async def _parse_and_store_results(self, session_id: str, llm_output: str):
        """
        解析 LLM 输出，存储通用和特定表征。
        """
        try:
            json_pattern = r"```json\s*(\{.*?\})\s*```|(\{.*?\})"
            match = re.search(json_pattern, llm_output, re.DOTALL)

            if match:
                json_str = match.group(1) if match.group(1) else match.group(2)
            else:
                json_str = llm_output[llm_output.find("{") : llm_output.rfind("}") + 1]

            results = json.loads(json_str)

            # 通用表征：全量替换
            universal = results.get("universal", [])
            if universal:
                self.data_manager.replace_universal(session_id, universal)
                logger.info(
                    f"为会话 {session_id} 更新通用表征: {universal}"
                )

            # 特定表征：逐条添加
            specific = results.get("specific", [])
            for item in specific:
                content = item.get("content", "")
                trigger_regex = item.get("trigger_regex", "")
                if content and trigger_regex:
                    self.data_manager.add_or_update_specific(
                        session_id, content, trigger_regex
                    )

            if specific:
                logger.info(
                    f"为会话 {session_id} 添加特定表征: {[s['content'] for s in specific]}"
                )

            # 检查特定表征容量
            self.data_manager.check_specific_capacity(session_id)

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"解析 LLM 输出失败: {e}\n原始输出: {llm_output}")
