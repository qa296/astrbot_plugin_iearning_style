# -*- coding: utf-8 -*-
from typing import Dict, List, Any
from astrbot.api import logger
from .style_selector import StyleSelector

class StyleInjector:
    """
    负责将学习到的风格动态注入到LLM的system prompt中。
    """
    
    def __init__(self, data_manager, config: Dict[str, Any]):
        self.data_manager = data_manager
        self.config = config
        self.style_selector = StyleSelector(data_manager)
        
    def should_inject_style(self, session_id: str) -> bool:
        """
        判断是否应该为该会话注入风格。
        
        :param session_id: 会话ID
        :return: 是否应该注入风格
        """
        # 检查是否启用了风格注入
        if not self.config.get("enable_style_injection", True):
            return False
            
        # 检查该会话是否有足够的风格数据
        styles = self.data_manager.get_styles_for_session(session_id)
        if not styles:
            return False
            
        # 检查是否有足够高熟练度的风格
        min_proficiency = self.config.get("min_proficiency_for_injection", 20)
        high_proficiency_styles = [
            s for s in styles 
            if s.get("proficiency", 0) >= min_proficiency
        ]
        
        return len(high_proficiency_styles) > 0
    
    def inject_style_to_prompt(self, session_id: str, original_system_prompt: str) -> str:
        """
        将学习到的风格注入到system prompt中。
        
        :param session_id: 会话ID
        :param original_system_prompt: 原始的system prompt
        :return: 注入风格后的system prompt
        """
        if not self.should_inject_style(session_id):
            return original_system_prompt
            
        try:
            # 选择风格
            max_styles = self.config.get("max_styles_in_prompt", 3)
            selected_styles = self.style_selector.select_styles_for_session(
                session_id, 
                max_styles=max_styles
            )
            
            # 构建风格提示
            style_prompt = self.style_selector.build_style_prompt(selected_styles)
            
            if not style_prompt:
                return original_system_prompt
                
            # 将风格提示注入到system prompt
            # 如果原始prompt为空，直接返回风格提示
            if not original_system_prompt.strip():
                return style_prompt
                
            # 否则将风格提示附加到原始prompt后面
            separator = "\n\n" if original_system_prompt.strip() else ""
            new_prompt = f"{original_system_prompt}{separator}{style_prompt}"
            
            logger.debug(f"为会话 {session_id} 注入风格提示: {style_prompt}")
            return new_prompt
            
        except Exception as e:
            logger.error(f"注入风格时发生错误: {e}")
            return original_system_prompt
    
    def get_style_summary(self, session_id: str) -> Dict[str, Any]:
        """
        获取会话的风格摘要信息。
        
        :param session_id: 会话ID
        :return: 风格摘要信息
        """
        styles = self.data_manager.get_styles_for_session(session_id)
        
        if not styles:
            return {
                "has_styles": False,
                "total_styles": 0,
                "high_proficiency_styles": 0,
                "language_styles": [],
                "grammar_features": []
            }
            
        min_proficiency = self.config.get("min_proficiency_for_injection", 20)
        high_proficiency_styles = [
            s for s in styles 
            if s.get("proficiency", 0) >= min_proficiency
        ]
        
        language_styles = [
            s["content"] for s in high_proficiency_styles 
            if s.get("type") == "language_style"
        ]
        
        grammar_features = [
            s["content"] for s in high_proficiency_styles 
            if s.get("type") == "grammar_feature"
        ]
        
        return {
            "has_styles": len(high_proficiency_styles) > 0,
            "total_styles": len(styles),
            "high_proficiency_styles": len(high_proficiency_styles),
            "language_styles": language_styles,
            "grammar_features": grammar_features
        }