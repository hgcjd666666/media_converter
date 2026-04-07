import os
import shutil
import sys
import logging
import time
import hashlib
import tempfile
import subprocess
from pathlib import Path
from typing import Set, Optional, Tuple, List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed


class BaseProcessor:
    def __init__(self, task_name: str, logger_name: str = None):
        self.task_name = task_name
        self.logger = self._setup_logger(logger_name or task_name)
        self._md5_cache: Dict[Tuple[str, int, int], str] = {}

    def _setup_logger(self, name: str) -> logging.Logger:
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def _get_file_md5_with_cache(self, file_path: str) -> Optional[str]:
        try:
            stat = os.stat(file_path)
            key = (file_path, stat.st_mtime_ns, stat.st_size)
            if key in self._md5_cache:
                return self._md5_cache[key]
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hash_md5.update(chunk)
            md5 = hash_md5.hexdigest()
            self._md5_cache[key] = md5
            return md5
        except Exception as e:
            self.logger.error(f"计算 MD5 失败 {file_path}: {e}")
            return None

    def _is_content_identical(self, src: str, dst: str) -> bool:
        if not os.path.exists(dst):
            return False
        try:
            src_stat = os.stat(src)
            dst_stat = os.stat(dst)
            if src_stat.st_size != dst_stat.st_size:
                return False
            src_md5 = self._get_file_md5_with_cache(src)
            dst_md5 = self._get_file_md5_with_cache(dst)
            return src_md5 is not None and dst_md5 is not None and src_md5 == dst_md5
        except Exception:
            return False

    def _safe_move(self, src: str, dst: str):
        Path(os.path.dirname(dst)).mkdir(parents=True, exist_ok=True)
        shutil.move(src, dst)

    def _run_ffmpeg(self, input_file: str, output_file: str, ffmpeg_args: List[str]) -> Tuple[bool, str]:
        """
        执行 ffmpeg 命令，自动处理临时文件扩展名。
        ffmpeg_args 是命令中 -i 之后、输出文件之前的参数列表。
        返回 (成功标志, 错误信息)
        """
        Path(os.path.dirname(output_file)).mkdir(parents=True, exist_ok=True)
        suffix = os.path.splitext(output_file)[1]
        fd, temp_file = tempfile.mkstemp(suffix=suffix, dir=os.path.dirname(output_file))
        os.close(fd)
        try:
            cmd = ['ffmpeg', '-i', input_file] + ffmpeg_args + ['-y', temp_file]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    encoding='utf-8', errors='ignore')
            if result.returncode != 0:
                return False, result.stderr.strip()
            self._safe_move(temp_file, output_file)
            return True, ""
        except Exception as e:
            if os.path.exists(temp_file):
                os.remove(temp_file)
            return False, str(e)

    def process_file(self, source_file: str, target_file: str, **kwargs) -> Tuple[str, str]:
        raise NotImplementedError

    def process_directory(self, source_dir: str, target_dir: str, **kwargs) -> None:
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        tasks = []
        for root, _, files in os.walk(source_dir):
            for file in files:
                source_path = os.path.join(root, file)
                rel_path = os.path.relpath(root, source_dir)
                target_path = os.path.join(target_dir, rel_path, file)
                tasks.append((source_path, target_path))
        self.logger.info(f"找到 {len(tasks)} 个文件需要处理")
        if not tasks:
            return
        def worker(args):
            src, tgt = args
            if self._is_content_identical(src, tgt):
                return f"跳过内容未变: {tgt}", "skipped"
            return self.process_file(src, tgt, **kwargs)
        self._run_parallel(tasks, worker, kwargs.get('max_workers', 8), self.task_name)

    def _run_parallel(self, tasks, worker_func, max_workers, task_desc):
        if not tasks:
            return
        completed = skipped = errors = 0
        total = len(tasks)
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=self.task_name) as executor:
            futures = {executor.submit(worker_func, t): t for t in tasks}
            for future in as_completed(futures):
                try:
                    msg, typ = future.result()
                    if typ in ("converted", "cut", "cleaned"):
                        completed += 1
                    elif typ in ("skipped", "copied"):
                        skipped += 1
                    else:
                        errors += 1
                    self.logger.info(msg)
                    progress = (completed + skipped + errors) / total * 100
                    self.logger.info(f"进度: 成功 {completed}, 跳过 {skipped}, 错误 {errors} ({progress:.1f}%)")
                except Exception as e:
                    errors += 1
                    self.logger.error(f"任务执行异常: {e}")
        self.logger.info(f"{task_desc}完成: 成功 {completed}, 跳过 {skipped}, 错误 {errors}")