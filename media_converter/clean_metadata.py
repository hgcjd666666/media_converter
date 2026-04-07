import os
import subprocess
import shutil
from pathlib import Path
from typing import Set, Optional, Tuple

from .base import BaseProcessor
from .utils import get_artist_metadata


class CleanMetadataProcessor(BaseProcessor):
    """元数据整理处理器：只保留 artist 和图片流"""

    def process_file(self, source_file: str, target_file: str, **kwargs) -> Tuple[str, str]:
        """清理单个文件的元数据"""
        Path(os.path.dirname(target_file)).mkdir(parents=True, exist_ok=True)
        temp_file = target_file + ".tmp"
        artist = get_artist_metadata(source_file, self.logger)
        cmd = [
            'ffmpeg',
            '-i', source_file,
            '-map', '0:a',
            '-map', '0:v?',
            '-c', 'copy',
            '-map_metadata', '-1',
            '-map_metadata:s:a', '-1',
            '-map_metadata:s:v', '-1',
            '-y',
            temp_file
        ]
        if artist:
            cmd.insert(-2, '-metadata')
            cmd.insert(-2, f'artist={artist}')
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           text=True, encoding='utf-8', errors='ignore')
            self._safe_move(temp_file, target_file)
            return f"已清理元数据: {source_file}", "cleaned"
        except Exception as e:
            if os.path.exists(temp_file):
                os.remove(temp_file)
            self.logger.error(f"清理元数据失败: {source_file}, 错误: {e}")
            return f"清理失败: {source_file}", "error"

    def process_directory(self, source_dir: str, target_dir: str,
                          source_exts: Optional[Set[str]] = None,
                          max_workers: int = 8, temp_dir: str = None,
                          cleanup_ignore_dirs: Optional[Tuple[str, ...]] = None):
        """批量清理元数据"""
        super().process_directory(
            source_dir=source_dir,
            target_dir=target_dir,
            source_exts=source_exts,
            max_workers=max_workers,
            temp_dir=temp_dir,
            cleanup_ignore_dirs=cleanup_ignore_dirs
        )