import asyncio

from astrbot.api import logger

from .data_manager import DataManager
from .learning_manager import LearningManager


class Scheduler:
    """
    负责定时任务的调度。
    - analysis_task: 定期分析聊天记录（默认 1h）
    - maintenance_task: 定期合并相似特定表征 + 容量检查（默认 24h）
    """

    def __init__(
        self,
        data_manager: DataManager,
        learning_manager: LearningManager,
        config: dict,
    ):
        self.data_manager = data_manager
        self.learning_manager = learning_manager
        self.config = config
        self.analysis_task: asyncio.Task | None = None
        self.maintenance_task: asyncio.Task | None = None
        self.is_running = False

    def start(self):
        """启动所有定时任务。"""
        if not self.is_running:
            self.is_running = True
            self.analysis_task = asyncio.create_task(self._run_analysis())
            self.maintenance_task = asyncio.create_task(self._run_maintenance())
            logger.info("定时任务已启动。")

    async def stop(self):
        """停止所有定时任务。"""
        if self.is_running:
            self.is_running = False
            tasks = []
            if self.analysis_task:
                self.analysis_task.cancel()
                tasks.append(self.analysis_task)
            if self.maintenance_task:
                self.maintenance_task.cancel()
                tasks.append(self.maintenance_task)

            if tasks:
                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                except asyncio.CancelledError:
                    pass

            logger.info("定时任务已停止。")

    async def _run_analysis(self):
        """定期分析聊天记录。"""
        analysis_interval = self.config.get("analysis_interval_seconds", 3600)
        while self.is_running:
            await asyncio.sleep(analysis_interval)
            logger.info("开始执行周期性聊天记录分析...")
            all_sessions = list(self.data_manager.chat_history.keys())
            for session_id in all_sessions:
                try:
                    await self.learning_manager.analyze_and_learn(session_id)
                    await asyncio.sleep(0)
                except Exception as e:
                    logger.error(f"分析会话 {session_id} 时出错: {e}")
            await self.data_manager.force_save()

    async def _run_maintenance(self):
        """定期维护：合并相似特定表征 + 容量检查。"""
        maintenance_interval = self.config.get("maintenance_interval_seconds", 86400)
        while self.is_running:
            await asyncio.sleep(maintenance_interval)
            logger.info("开始执行周期性风格维护...")
            await self._perform_maintenance()
            await asyncio.sleep(0)

    async def _perform_maintenance(self):
        """执行维护：合并相似特定表征，然后检查各会话容量。"""
        all_sessions = list(self.data_manager.specific.keys())
        for session_id in all_sessions:
            try:
                self.data_manager.merge_similar_specific(session_id)
                self.data_manager.check_specific_capacity(session_id)
            except Exception as e:
                logger.error(f"维护会话 {session_id} 时出错: {e}")

        await self.data_manager.force_save()
        logger.info("风格维护完成（合并相似+容量清理）。")
