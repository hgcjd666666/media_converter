import os
import sys
import threading
import time
import tempfile
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.job import Job

from .convert import ConvertProcessor
from .cut_silence import CutSilenceProcessor
from .clean_metadata import CleanMetadataProcessor
from .composite import CompositeProcessor


class ConversionTaskManager:
    """任务管理器，支持依赖和周期调度"""

    def __init__(self):
        self.logger = self._setup_logger("ConversionTaskManager")
        self.base_temp_dir = tempfile.mkdtemp()
        self.logger.info(f"创建根临时目录: {self.base_temp_dir}")

        self.tasks: Dict[str, Dict] = {}
        self.dependencies: Dict[str, List[str]] = {}
        self.dependents: Dict[str, List[str]] = {}

        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        self.jobs: Dict[str, Job] = {}

    def _setup_logger(self, name: str) -> logging.Logger:
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def add_task(self, task_name: str, config: dict):
        """
        统一添加任务接口
        config 必须包含 'type' 字段，以及对应处理器所需的参数
        """
        if task_name in self.tasks:
            self.logger.warning(f"任务 '{task_name}' 已存在，跳过添加")
            return

        task_type = config.get('type')
        if not task_type:
            raise ValueError("config 必须包含 'type' 字段")

        # 每个任务独立临时目录
        task_temp_dir = os.path.join(self.base_temp_dir, task_name)
        Path(task_temp_dir).mkdir(parents=True, exist_ok=True)

        # 根据类型实例化处理器，传入 cache_dir
        if task_type == 'convert':
            processor = ConvertProcessor(task_name, cache_dir=task_temp_dir)
        elif task_type == 'cut_silence':
            processor = CutSilenceProcessor(task_name, cache_dir=task_temp_dir)
        elif task_type == 'metadata_clean':
            processor = CleanMetadataProcessor(task_name, cache_dir=task_temp_dir)
        elif task_type == 'composite':
            # 复合任务不需要 cache_dir（它自己管理缓存）
            processor = CompositeProcessor(task_name, config.get('steps', []))
        else:
            raise ValueError(f"不支持的任务类型: {task_type}")

        # 存储任务信息（不修改原 config，避免丢失 steps 等字段）
        task_info = {
            'processor': processor,
            'type': task_type,
            'source_dir': config['source_dir'],
            'target_dir': config['target_dir'],
            'source_exts': config.get('source_exts'),
            'max_workers': config.get('max_workers', 8),
            'cleanup_ignore_dirs': config.get('cleanup_ignore_dirs'),
            'temp_dir': task_temp_dir,
            'interval': config.get('interval', 30),
            'running': False,
            'config': config.copy(),   # 保留原始配置
        }
        self.tasks[task_name] = task_info

        # 处理依赖
        depends_on = config.get('depends_on', [])
        self.dependencies[task_name] = depends_on
        for dep in depends_on:
            self.dependents.setdefault(dep, []).append(task_name)

        self.logger.info(f"添加任务 [{task_type}]: {task_name} 依赖: {depends_on}")

    def _can_run(self, task_name: str) -> bool:
        """检查任务是否可以运行（无依赖运行中且自身未运行）"""
        task = self.tasks[task_name]
        if task['running']:
            return False
        for dep in self.dependencies[task_name]:
            if self.tasks[dep]['running']:
                return False
        return True

    def _execute_task(self, task_name: str):
        """实际执行任务"""
        if not self._can_run(task_name):
            return
        task = self.tasks[task_name]
        task['running'] = True
        self.logger.info(f"开始执行任务: {task_name}")

        try:
            processor = task['processor']
            cfg = task['config']

            # 根据类型调用不同的处理方法
            if task['type'] == 'convert':
                processor.process_directory(
                    source_dir=task['source_dir'],
                    target_dir=task['target_dir'],
                    ffmpeg_args=cfg['ffmpeg_args'],
                    target_ext=cfg['target_ext'],
                    source_exts=task['source_exts'],
                    max_workers=task['max_workers'],
                    temp_dir=task['temp_dir'],
                    cleanup_ignore_dirs=task['cleanup_ignore_dirs']
                )
            elif task['type'] == 'cut_silence':
                processor.process_directory(
                    source_dir=task['source_dir'],
                    target_dir=task['target_dir'],
                    threshold=cfg.get('threshold', '-70dB'),
                    min_duration=cfg.get('min_duration', 0.1),
                    source_exts=task['source_exts'],
                    max_workers=task['max_workers'],
                    temp_dir=task['temp_dir'],
                    cleanup_ignore_dirs=task['cleanup_ignore_dirs']
                )
            elif task['type'] == 'metadata_clean':
                processor.process_directory(
                    source_dir=task['source_dir'],
                    target_dir=task['target_dir'],
                    source_exts=task['source_exts'],
                    max_workers=task['max_workers'],
                    temp_dir=task['temp_dir'],
                    cleanup_ignore_dirs=task['cleanup_ignore_dirs']
                )
            elif task['type'] == 'composite':
                processor.process_directory(
                    source_dir=task['source_dir'],
                    target_dir=task['target_dir'],
                    source_exts=task['source_exts'],
                    max_workers=task['max_workers'],
                    temp_dir=task['temp_dir'],
                    cleanup_ignore_dirs=task['cleanup_ignore_dirs']
                )
            else:
                raise ValueError(f"未知的任务类型: {task['type']}")

            # 统一清理多余文件（仅当提供了 source_exts 且不是复合任务时）
            if task['source_exts'] and task['type'] != 'composite':
                target_ext = cfg.get('target_ext', '')
                processor._cleanup_extra_files(
                    source_dir=task['source_dir'],
                    target_dir=task['target_dir'],
                    target_ext=target_ext,
                    source_exts=task['source_exts'],
                    ignore_dirs=task['cleanup_ignore_dirs']
                )
            self.logger.info(f"任务 {task_name} 执行完成")
        except Exception as e:
            self.logger.error(f"任务 {task_name} 执行失败: {e}")
        finally:
            task['running'] = False
            # 清理任务专用临时目录（复合任务已在内部清理）
            if task['type'] != 'composite' and os.path.exists(task['temp_dir']):
                shutil.rmtree(task['temp_dir'], ignore_errors=True)
                self.logger.info(f"已清理临时目录: {task['temp_dir']}")
            self._trigger_dependents(task_name)

    def _trigger_dependents(self, task_name: str):
        """触发所有依赖此任务的任务"""
        for dep_name in self.dependents.get(task_name, []):
            if self._can_run(dep_name):
                threading.Thread(target=self._execute_task, args=(dep_name,), daemon=True).start()
                self.logger.info(f"任务 {dep_name} 被依赖触发")

    def _scheduled_execute(self, task_name: str):
        """调度器入口，检查依赖后执行"""
        if self._can_run(task_name):
            self._execute_task(task_name)

    def start_all(self):
        """启动所有无依赖任务的首次执行，并为需要周期的任务添加调度"""
        for task_name, task in self.tasks.items():
            # 首次执行（无依赖）
            if not self.dependencies[task_name]:
                self.logger.info(f"立即执行任务: {task_name}")
                threading.Thread(target=self._execute_task, args=(task_name,), daemon=True).start()
            # 添加周期调度（interval > 0）
            if task['interval'] > 0:
                job = self.scheduler.add_job(
                    self._scheduled_execute,
                    IntervalTrigger(seconds=task['interval']),
                    args=(task_name,),
                    id=task_name,
                    replace_existing=True,
                    max_instances=1
                )
                self.jobs[task_name] = job
                self.logger.info(f"添加周期调度: {task_name} 每 {task['interval']} 秒")

    def stop(self):
        """停止调度器"""
        self.scheduler.shutdown()
        self.logger.info("调度器已停止")