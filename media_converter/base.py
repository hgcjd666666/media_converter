import os
import shutil
import sys
import logging
import time
import hashlib
from pathlib import Path
from typing import Set, Optional, Tuple, List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed


class BaseProcessor:
    """处理器基类，提供通用功能：日志、清理多余文件、并行执行、MD5计算及缓存等"""

    def __init__(self, task_name: str, logger_name: str = None):
        self.task_name = task_name
        self.logger = self._setup_logger(logger_name or task_name)
        # MD5 缓存：key = (path, mtime_ns, size) -> md5
        self._md5_cache: Dict[Tuple[str, int, int], str] = {}

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

    def _get_file_md5_with_cache(self, file_path: str) -> Optional[str]:
        """获取文件的 MD5，使用缓存：如果文件的修改时间和大小未变，直接返回缓存的 MD5。否则重新计算并更新缓存。"""
        try:
            stat = os.stat(file_path)
            key = (file_path, stat.st_mtime_ns, stat.st_size)
            if key in self._md5_cache:
                return self._md5_cache[key]
            # 计算 MD5
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
        """
        快速判断两个文件内容是否相同：
        1. 比较大小（快速预判）
        2. 如果大小相同，再比较 MD5（利用缓存）
        """
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

    def _cleanup_extra_files(self, source_dir: str, target_dir: str,
                             target_ext: str, source_exts: Set[str],
                             ignore_dirs: Optional[Tuple[str, ...]] = None) -> Tuple[int, int]:
        """
        删除目标目录中不存在于源目录的文件，并同步文件修改时间
        返回 (删除的文件数, 失败数)
        """
        deleted = 0
        errors = 0

        # 构建忽略目录的绝对路径列表
        ignore_abs_paths = []
        if ignore_dirs:
            for d in ignore_dirs:
                abs_path = os.path.normpath(os.path.join(target_dir, d))
                ignore_abs_paths.append(abs_path)

        def is_ignored(path: str) -> bool:
            path_abs = os.path.normpath(path)
            for ignore_abs in ignore_abs_paths:
                if os.path.commonpath([ignore_abs, path_abs]) == ignore_abs:
                    return True
            return False

        # 构建源文件索引
        source_basenames = set()
        source_mtimes = {}
        self.logger.info("正在扫描源目录以构建文件索引...")
        scan_start = time.time()
        for root, _, files in os.walk(source_dir):
            for file in files:
                file_ext = os.path.splitext(file)[1].lower()
                if file_ext not in source_exts:
                    continue
                rel_dir = os.path.relpath(root, source_dir)
                base = os.path.splitext(file)[0]
                if rel_dir == '.':
                    rel_base = base
                else:
                    rel_base = os.path.join(rel_dir, base)
                source_basenames.add(rel_base)
                file_path = os.path.join(root, file)
                mtime = os.path.getmtime(file_path)
                if rel_base in source_mtimes:
                    if mtime > source_mtimes[rel_base]:
                        source_mtimes[rel_base] = mtime
                else:
                    source_mtimes[rel_base] = mtime
        scan_time = time.time() - scan_start
        self.logger.info(f"源文件索引构建完成，耗时 {scan_time:.2f} 秒，共 {len(source_basenames)} 个唯一基本名")

        # 遍历目标目录清理
        for root, _, files in os.walk(target_dir):
            if is_ignored(root):
                self.logger.debug(f"跳过忽略目录: {root}")
                continue
            for file in files:
                target_path = os.path.join(root, file)
                if is_ignored(target_path):
                    continue
                rel_dir = os.path.relpath(root, target_dir)
                base = os.path.splitext(file)[0]
                if rel_dir == '.':
                    rel_base = base
                else:
                    rel_base = os.path.join(rel_dir, base)
                if rel_base in source_basenames:
                    try:
                        mtime = source_mtimes[rel_base]
                        os.utime(target_path, (time.time(), mtime))
                    except Exception as e:
                        self.logger.error(f"同步文件时间失败: {target_path}, 错误: {e}")
                else:
                    try:
                        os.remove(target_path)
                        self.logger.info(f"删除多余文件: {target_path}")
                        deleted += 1
                    except Exception as e:
                        self.logger.error(f"删除文件失败: {target_path}, 错误: {e}")
                        errors += 1

        # 删除空目录
        for root, dirs, _ in os.walk(target_dir, topdown=False):
            if is_ignored(root):
                continue
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                if is_ignored(dir_path):
                    continue
                if not os.listdir(dir_path):
                    try:
                        os.rmdir(dir_path)
                        self.logger.info(f"删除空目录: {dir_path}")
                    except Exception as e:
                        self.logger.error(f"删除目录失败: {dir_path}, 错误: {e}")

        return deleted, errors

    def _safe_move(self, src: str, dst: str):
        """安全移动文件，确保目标目录存在"""
        Path(os.path.dirname(dst)).mkdir(parents=True, exist_ok=True)
        shutil.move(src, dst)

    def _run_parallel(self, tasks, worker_func, max_workers: int, task_desc: str = "处理"):
        """通用并行执行函数"""
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

    def process_file(self, source_file: str, target_file: str, **kwargs) -> Tuple[str, str]:
        """处理单个文件，子类必须实现，返回 (消息, 类型)"""
        raise NotImplementedError

    def process_directory(self, source_dir: str, target_dir: str,
                          source_exts: Optional[Set[str]] = None,
                          max_workers: int = 8, temp_dir: str = None,
                          cleanup_ignore_dirs: Optional[Tuple[str, ...]] = None,
                          **kwargs) -> None:
        """
        批量处理目录，默认实现：遍历文件，逐个调用 process_file
        """
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        tasks = []
        for root, _, files in os.walk(source_dir):
            for file in files:
                file_ext = os.path.splitext(file)[1].lower()
                if source_exts and file_ext not in source_exts:
                    continue
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

        self._run_parallel(tasks, worker, max_workers, "处理")