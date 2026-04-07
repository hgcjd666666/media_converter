import os
import subprocess
import shutil
from pathlib import Path
from typing import List, Set, Optional, Tuple

from .base import BaseProcessor


class ConvertProcessor(BaseProcessor):
    """格式转换处理器"""

    def process_file(self, source_file: str, target_file: str,
                     ffmpeg_args: List[str], target_ext: str = None,
                     **kwargs) -> Tuple[str, str]:
        """转换单个文件"""
        # 根据 target_ext 调整目标文件名
        if target_ext:
            target_file = str(Path(target_file).with_suffix(target_ext))
        Path(os.path.dirname(target_file)).mkdir(parents=True, exist_ok=True)
        temp_file = target_file + ".tmp"
        cmd = ['ffmpeg', '-i', source_file] + ffmpeg_args + ['-y', temp_file]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           text=True, encoding='utf-8', errors='ignore')
            self._safe_move(temp_file, target_file)
            return f"转换成功: {source_file} -> {target_file}", "converted"
        except Exception as e:
            if os.path.exists(temp_file):
                os.remove(temp_file)
            return f"转换失败: {source_file}, 错误: {e}", "error"

    def process_directory(self, source_dir: str, target_dir: str,
                          ffmpeg_args: List[str], target_ext: str,
                          source_exts: Optional[Set[str]] = None,
                          max_workers: int = 8, temp_dir: str = None,
                          cleanup_ignore_dirs: Optional[Tuple[str, ...]] = None):
        """批量转换目录"""
        # 复用基类的 process_directory 实现
        super().process_directory(
            source_dir=source_dir,
            target_dir=target_dir,
            source_exts=source_exts,
            max_workers=max_workers,
            temp_dir=temp_dir,
            cleanup_ignore_dirs=cleanup_ignore_dirs,
            ffmpeg_args=ffmpeg_args,
            target_ext=target_ext
        )