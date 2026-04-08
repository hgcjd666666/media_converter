import os
import shutil
import tempfile
import hashlib
import json
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from .base import BaseProcessor
from .cut_silence import CutSilenceProcessor
from .convert import ConvertProcessor
from .clean_metadata import CleanMetadataProcessor


class CompositeProcessor(BaseProcessor):
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
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        if temp_dir:
            cache_root = Path(temp_dir) / ".cache"
            cache_root.mkdir(parents=True, exist_ok=True)
            mapping_file = cache_root / "source_target_md5.json"
            if mapping_file.exists():
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    md5_map = json.load(f)
            else:
                md5_map = {}
        else:
            cache_root = Path(tempfile.mkdtemp())
            mapping_file = cache_root / "source_target_md5.json"
            md5_map = {}

        # 线程锁，保护映射文件的并发写入
        map_lock = threading.Lock()

        # 收集源文件
        source_files = []
        for root, _, files in os.walk(source_dir):
            for file in files:
                file_ext = os.path.splitext(file)[1].lower()
                if source_exts and file_ext not in source_exts:
                    continue
                src = os.path.join(root, file)
                rel_path = os.path.relpath(root, source_dir)
                tgt = os.path.join(target_dir, rel_path, file)
                source_files.append((src, tgt, rel_path))

        self.logger.info(f"找到 {len(source_files)} 个文件需要复合处理")
        if not source_files:
            return

        def get_file_md5(file_path: str) -> str:
            if not os.path.exists(file_path):
                return ""
            return self._get_file_md5_with_cache(file_path) or ""

        # 确定最终扩展名（根据最后一步的配置）
        final_ext = None
        last_step_type, last_step_config = self._processors[-1][0], self._processors[-1][2]
        if last_step_type == 'convert' and 'target_ext' in last_step_config:
            final_ext = last_step_config['target_ext']

        def process_one_file(src, orig_tgt, rel_path):
            # 根据最终扩展名修正目标路径
            if final_ext:
                final_tgt = str(Path(orig_tgt).with_suffix(final_ext))
            else:
                final_tgt = orig_tgt

            src_md5 = get_file_md5(src)
            cache_key = src

            # 检查缓存（需要加锁读？但 map 可能在写入时被修改，但我们这里只读，且 map 是函数开始时快照，不一致风险小）
            # 但为了准确，可以加锁读最新值，但为了性能，暂且使用快照，因为写入频率低。
            if cache_key in md5_map:
                cached_src_md5 = md5_map[cache_key].get('src_md5')
                cached_tgt_md5 = md5_map[cache_key].get('tgt_md5')
                if cached_src_md5 == src_md5 and os.path.exists(final_tgt):
                    try:
                        tgt_md5 = get_file_md5(final_tgt)
                        if tgt_md5 == cached_tgt_md5:
                            return f"源文件未修改，跳过: {src}", "skipped"
                    except Exception:
                        pass

            file_temp_dir = tempfile.mkdtemp(dir=temp_dir) if temp_dir else tempfile.mkdtemp()
            try:
                current_file = src
                for i, (step_type, proc, step_config) in enumerate(self._processors):
                    ext = os.path.splitext(current_file)[1]
                    step_output = os.path.join(file_temp_dir, f"s{i}_{Path(current_file).name}")
                    if not step_output.endswith(ext):
                        step_output += ext

                    if step_type == 'convert':
                        target_ext = step_config.get('target_ext', '')
                        if target_ext:
                            step_output = str(Path(step_output).with_suffix(target_ext))

                    if step_type == 'cut_silence':
                        msg, typ = proc.process_file(current_file, step_output,
                                                     threshold=step_config.get('threshold', '-70dB'),
                                                     min_duration=step_config.get('min_duration', 0.1))
                    elif step_type == 'convert':
                        msg, typ = proc.process_file(current_file, step_output,
                                                     ffmpeg_args=step_config['ffmpeg_args'],
                                                     target_ext=step_config.get('target_ext', ''))
                    elif step_type == 'metadata_clean':
                        msg, typ = proc.process_file(current_file, step_output)
                    else:
                        raise ValueError(f"未知步骤类型: {step_type}")

                    if typ == 'error':
                        return msg, typ
                    current_file = step_output

                if os.path.exists(current_file) and current_file != final_tgt:
                    self._safe_move(current_file, final_tgt)

                tgt_md5 = get_file_md5(final_tgt)
                # 更新缓存，需要加锁
                with map_lock:
                    # 重新读取最新映射（因为其他线程可能已更新）
                    try:
                        with open(mapping_file, 'r', encoding='utf-8') as f:
                            current_map = json.load(f)
                    except (FileNotFoundError, json.JSONDecodeError):
                        current_map = {}
                    current_map[cache_key] = {'src_md5': src_md5, 'tgt_md5': tgt_md5}
                    with open(mapping_file, 'w', encoding='utf-8') as f:
                        json.dump(current_map, f, indent=2)
                    # 更新本地快照（可选）
                    md5_map[cache_key] = current_map[cache_key]

                return f"复合处理成功: {src} -> {final_tgt}", "converted"
            except Exception as e:
                self.logger.error(f"处理文件失败 {src}: {e}")
                return f"处理失败: {src}, 错误: {e}", "error"
            finally:
                shutil.rmtree(file_temp_dir, ignore_errors=True)

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=self.task_name) as executor:
            futures = {executor.submit(process_one_file, src, tgt, rel): (src, tgt) for src, tgt, rel in source_files}
            for future in as_completed(futures):
                try:
                    msg, typ = future.result()
                    self.logger.info(msg)
                except Exception as e:
                    self.logger.error(f"文件处理异常: {e}")