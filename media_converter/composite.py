import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import BaseProcessor
from .cut_silence import CutSilenceProcessor
from .convert import ConvertProcessor
from .clean_metadata import CleanMetadataProcessor


class CompositeProcessor(BaseProcessor):
    """复合处理器：按顺序执行多个子任务，文件级流水线"""

    def __init__(self, task_name: str, steps: List[Dict[str, Any]]):
        super().__init__(task_name)
        self.steps = steps
        self._processors = []
        for step in steps:
            step = step.copy()
            step_type = step.pop('type')
            if step_type == 'cut_silence':
                proc = CutSilenceProcessor(f"{task_name}_cut")
            elif step_type == 'convert':
                proc = ConvertProcessor(f"{task_name}_convert")
            elif step_type == 'metadata_clean':
                proc = CleanMetadataProcessor(f"{task_name}_clean")
            else:
                raise ValueError(f"不支持的子任务类型: {step_type}")
            self._processors.append((step_type, proc, step))

    def process_directory(self, source_dir: str, target_dir: str,
                          source_exts: Optional[Set[str]] = None,
                          max_workers: int = 8, temp_dir: str = None,
                          cleanup_ignore_dirs: Optional[Tuple[str, ...]] = None,
                          **kwargs):
        """
        批量处理目录：每个文件独立经过所有步骤，中间结果存放在临时目录，处理完立即清理。
        """
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        # 收集所有需要处理的源文件
        source_files = []
        for root, _, files in os.walk(source_dir):
            for file in files:
                file_ext = os.path.splitext(file)[1].lower()
                if source_exts and file_ext not in source_exts:
                    continue
                source_path = os.path.join(root, file)
                rel_path = os.path.relpath(root, source_dir)
                target_path = os.path.join(target_dir, rel_path, file)
                source_files.append((source_path, target_path))

        self.logger.info(f"找到 {len(source_files)} 个文件需要复合处理")
        if not source_files:
            return

        # 为整个复合任务创建一个临时根目录（可选，用于组织子临时目录）
        if temp_dir:
            root_temp_dir = temp_dir
            Path(root_temp_dir).mkdir(parents=True, exist_ok=True)
        else:
            root_temp_dir = tempfile.mkdtemp()
            self.logger.info(f"创建复合任务临时根目录: {root_temp_dir}")

        def process_one_file(src, final_tgt):
            # 创建该文件专用的临时目录
            file_temp_dir = tempfile.mkdtemp(dir=root_temp_dir)
            try:
                current_file = src
                for i, (step_type, proc, step_config) in enumerate(self._processors):
                    # 生成步骤输出路径
                    base_name = os.path.basename(current_file)
                    step_output = os.path.join(file_temp_dir, f"step_{i}_{base_name}")
                    # 调用子处理器的单文件处理方法
                    if step_type == 'cut_silence':
                        msg, typ = proc.process_file(
                            current_file, step_output,
                            threshold=step_config.get('threshold', '-70dB'),
                            min_duration=step_config.get('min_duration', 0.1)
                        )
                    elif step_type == 'convert':
                        msg, typ = proc.process_file(
                            current_file, step_output,
                            ffmpeg_args=step_config['ffmpeg_args'],
                            target_ext=step_config['target_ext']
                        )
                    elif step_type == 'metadata_clean':
                        msg, typ = proc.process_file(current_file, step_output)
                    else:
                        raise ValueError(f"未知步骤类型: {step_type}")
                    if typ == 'error':
                        return msg, typ
                    # 更新 current_file 为步骤输出，供下一步使用
                    current_file = step_output
                # 最后一步输出移动到最终目标
                if os.path.exists(current_file) and current_file != final_tgt:
                    self._safe_move(current_file, final_tgt)
                return f"复合处理成功: {src} -> {final_tgt}", "converted"
            except Exception as e:
                self.logger.error(f"处理文件失败 {src}: {e}")
                return f"处理失败: {src}, 错误: {e}", "error"
            finally:
                # 清理该文件的临时目录
                shutil.rmtree(file_temp_dir, ignore_errors=True)

        # 并行处理所有文件
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=self.task_name) as executor:
            futures = {executor.submit(process_one_file, src, tgt): (src, tgt) for src, tgt in source_files}
            for future in as_completed(futures):
                try:
                    msg, typ = future.result()
                    self.logger.info(msg)
                except Exception as e:
                    self.logger.error(f"文件处理异常: {e}")

        # 清理整个复合任务的临时根目录（如果是由本方法创建的）
        if temp_dir is None and os.path.exists(root_temp_dir):
            shutil.rmtree(root_temp_dir, ignore_errors=True)
            self.logger.info(f"已清理复合任务临时根目录: {root_temp_dir}")