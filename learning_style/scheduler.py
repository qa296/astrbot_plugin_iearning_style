# -*- coding: utf-8 -*-
import asyncio
from astrbot.api import logger
from .data_manager import DataManager
from .learning_manager import LearningManager

class Scheduler:
    """
    负责定时任务的调度。
    """
    def __init__(self, data_manager: DataManager, learning_manager: LearningManager, config: dict):
        self.data_manager = data_manager
        self.learning_manager = learning_manager
        self.config = config
        self.analysis_task = None
        self.maintenance_task = None
        self.is_running = False

    def start(self):
        """
        启动所有定时任务。
        """
        if not self.is_running:
            self.is_running = True
            self.analysis_task = asyncio.create_task(self._run_analysis())
            self.maintenance_task = asyncio.create_task(self._run_maintenance())
            logger.info("定时任务已启动。")

    def stop(self):
        """
        停止所有定时任务。
        """
        if self.is_running:
            self.is_running = False
            if self.analysis_task:
                self.analysis_task.cancel()
            if self.maintenance_task:
                self.maintenance_task.cancel()
            logger.info("定时任务已停止。")

    async def _run_analysis(self):
        """
        定期分析聊天记录的任务。
        """
        analysis_interval = self.config.get("analysis_interval_seconds", 3600)
        while self.is_running:
            await asyncio.sleep(analysis_interval)
            logger.info("开始执行周期性聊天记录分析...")
            all_sessions = list(self.data_manager.chat_history.keys())
            for session_id in all_sessions:
                try:
                    await self.learning_manager.analyze_and_learn(session_id)
                except Exception as e:
                    logger.error(f"分析会话 {session_id} 时出错: {e}")

    async def _run_maintenance(self):
        """
        定期维护（衰减、清理）学到的风格。
        """
        maintenance_interval = self.config.get("maintenance_interval_seconds", 86400)
        while self.is_running:
            await asyncio.sleep(maintenance_interval)
            logger.info("开始执行周期性风格维护...")
            await self._perform_decay()
            await self._perform_cleanup()

    async def _perform_decay(self):
        """
        对所有风格的熟练度进行衰减。
        """
        current_time = asyncio.get_event_loop().time()
        decay_rate = self.config.get("proficiency_decay_rate", 1)
        for session_id, styles in self.data_manager.styles.items():
            for style in styles:
                # 简单的线性衰减，可以根据需求调整
                time_since_update = current_time - style.get("last_updated", current_time)
                # 根据维护周期和每日衰减率计算衰减量
                decay_amount = int(time_since_update / 86400) * decay_rate
                if decay_amount > 0:
                    style["proficiency"] = max(0, style.get("proficiency", 0) - decay_amount)
                    style["last_updated"] = current_time
        await self.data_manager.save_styles()
        logger.info("风格熟练度衰减完成。")

    async def _perform_cleanup(self):
        """
        清理熟练度过低或过期的风格，并处理容量限制。
        """
        # 清理熟练度为0的风格
        for session_id, styles in self.data_manager.styles.items():
            self.data_manager.styles[session_id] = [s for s in styles if s.get("proficiency", 0) > 0]

        # 处理容量限制
        max_styles = self.config.get("max_styles_per_session", 100)
        for session_id, styles in self.data_manager.styles.items():
            if len(styles) > max_styles:
                # 按熟练度升序排序，移除最低的
                sorted_styles = sorted(styles, key=lambda s: s.get("proficiency", 0))
                self.data_manager.styles[session_id] = sorted_styles[-max_styles:]

        await self.data_manager.save_styles()
        logger.info("风格清理完成。")