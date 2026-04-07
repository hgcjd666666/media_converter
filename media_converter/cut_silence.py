import os
import subprocess
import shutil
from pathlib import Path
from typing import Set, Optional, Tuple

from .base import BaseProcessor
from .utils import get_audio_duration, detect_silences, get_artist_metadata


class CutSilenceProcessor(BaseProcessor):
    """静音切除处理器（切除开头/结尾静音，保留作者和图片）"""

    def process_file(self, source_file: str, target_file: str,
                     threshold: str = '-70dB', min_duration: float = 0.1,
                     **kwargs) -> Tuple[str, str]:
        """切除单个文件的静音"""
        Path(os.path.dirname(target_file)).mkdir(parents=True, exist_ok=True)
        temp_file = target_file + ".tmp"
        try:
            total_duration = get_audio_duration(source_file, self.logger)
            silences = detect_silences(source_file, threshold, min_duration, self.logger)
            if not silences:
                return self._copy_with_clean_metadata(source_file, target_file)

            start_time = 0.0
            first_start = silences[0][0]
            if first_start < 0.1:
                start_time = silences[0][1]

            end_time = total_duration
            last_end = silences[-1][1]
            if total_duration - last_end < 0.1:
                end_time = silences[-1][0]

            if start_time >= end_time:
                return f"文件全为静音，跳过: {source_file}", "skipped"

            artist = get_artist_metadata(source_file, self.logger)
            cmd = [
                'ffmpeg',
                '-ss', str(start_time),
                '-i', source_file,
                '-to', str(end_time),
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

            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           text=True, encoding='utf-8', errors='ignore')
            self._safe_move(temp_file, target_file)
            return f"已切除静音并清理元数据: {source_file}", "cut"
        except Exception as e:
            if os.path.exists(temp_file):
                os.remove(temp_file)
            self.logger.error(f"静音切除失败: {source_file}, 错误: {e}")
            return f"静音切除失败: {source_file}", "error"

    def _copy_with_clean_metadata(self, source_file: str, target_file: str) -> Tuple[str, str]:
        """无静音时，复制文件并清理元数据"""
        try:
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
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           text=True, encoding='utf-8', errors='ignore')
            self._safe_move(temp_file, target_file)
            return f"已复制并清理元数据: {source_file}", "copied"
        except Exception as e:
            self.logger.error(f"复制并清理元数据失败: {source_file}, 错误: {e}")
            return f"复制失败: {source_file}", "error"

    def process_directory(self, source_dir: str, target_dir: str,
                          threshold: str = '-70dB', min_duration: float = 0.1,
                          source_exts: Optional[Set[str]] = None,
                          max_workers: int = 8, temp_dir: str = None,
                          cleanup_ignore_dirs: Optional[Tuple[str, ...]] = None):
        """批量切除静音"""
        super().process_directory(
            source_dir=source_dir,
            target_dir=target_dir,
            source_exts=source_exts,
            max_workers=max_workers,
            temp_dir=temp_dir,
            cleanup_ignore_dirs=cleanup_ignore_dirs,
            threshold=threshold,
            min_duration=min_duration
        )