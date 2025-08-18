# -*- coding: utf-8 -*-
import random
from typing import List, Dict, Any, Tuple
from astrbot.api import logger

class StyleSelector:
    """
    负责根据熟练度加权选择最适合当前语境的风格。
    """
    
    def __init__(self, data_manager):
        self.data_manager = data_manager
        
    def select_styles_for_session(self, session_id: str, max_styles: int = 5, min_proficiency: int = 20) -> Dict[str, List[str]]:
        """
        为指定会话选择风格，基于熟练度加权随机选择。
        
        :param session_id: 会话ID
        :param max_styles: 最多选择的风格数量
        :param min_proficiency: 最小熟练度阈值
        :return: 包含语言风格和语法特征的字典
        """
        styles = self.data_manager.get_styles_for_session(session_id)
        
        if not styles:
            return {"language_styles": [], "grammar_features": []}
            
        # 按类型分组
        language_styles = [s for s in styles if s.get("type") == "language_style" and s.get("proficiency", 0) >= min_proficiency]
        grammar_features = [s for s in styles if s.get("type") == "grammar_feature" and s.get("proficiency", 0) >= min_proficiency]
        
        # 按熟练度加权选择
        selected_language = self._weighted_random_selection(language_styles, max_styles)
        selected_grammar = self._weighted_random_selection(grammar_features, max_styles)
        
        return {
            "language_styles": selected_language,
            "grammar_features": selected_grammar
        }
    
    def _weighted_random_selection(self, styles: List[Dict[str, Any]], max_count: int) -> List[str]:
        """
        根据熟练度加权随机选择风格。
        
        :param styles: 风格列表
        :param max_count: 最多选择的数量
        :return: 选中的风格内容列表
        """
        if not styles:
            return []
            
        # 按熟练度排序，优先选择高熟练度的
        styles = sorted(styles, key=lambda x: x.get("proficiency", 0), reverse=True)
        
        # 计算总权重
        total_proficiency = sum(s.get("proficiency", 0) for s in styles)
        if total_proficiency <= 0:
            return [s["content"] for s in styles[:max_count]]
        
        # 加权随机选择
        selected = []
        remaining_styles = styles.copy()
        
        for _ in range(min(max_count, len(styles))):
            if not remaining_styles:
                break
                
            # 计算当前权重
            current_total = sum(s.get("proficiency", 0) for s in remaining_styles)
            if current_total <= 0:
                break
                
            # 加权随机选择
            r = random.uniform(0, current_total)
            cumulative = 0
            
            for style in remaining_styles:
                cumulative += style.get("proficiency", 0)
                if r <= cumulative:
                    selected.append(style["content"])
                    remaining_styles.remove(style)
                    break
        
        return selected
    
    def build_style_prompt(self, styles: Dict[str, List[str]]) -> str:
        """
        将选中的风格构建成适合注入到system prompt的文本。
        
        :param styles: 包含语言风格和语法特征的字典
        :return: 风格提示文本
        """
        if not styles["language_styles"] and not styles["grammar_features"]:
            return ""
            
        prompt_parts = []
        
        if styles["language_styles"]:
            prompt_parts.append(f"语言风格：{', '.join(styles['language_styles'])}")
            
        if styles["grammar_features"]:
            prompt_parts.append(f"语法特征：{', '.join(styles['grammar_features'])}")
            
        style_prompt = "在回复时，请尽量采用以下风格特点：" + "；".join(prompt_parts)
        
        return style_prompt