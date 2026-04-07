import os
from pathlib import Path
from typing import Tuple
from .base import BaseProcessor
from .utils import get_audio_duration, detect_silences, get_artist_metadata


class CutSilenceProcessor(BaseProcessor):
    def process_file(self, source_file: str, target_file: str,
                     threshold: str = '-70dB', min_duration: float = 0.1, **kwargs) -> Tuple[str, str]:
        try:
            total_duration = get_audio_duration(source_file, self.logger)
            silences = detect_silences(source_file, threshold, min_duration, self.logger)
            if not silences:
                return self._copy_with_clean_metadata(source_file, target_file)
            start_time = 0.0
            if silences[0][0] < 0.1:
                start_time = silences[0][1]
            end_time = total_duration
            if total_duration - silences[-1][1] < 0.1:
                end_time = silences[-1][0]
            if start_time >= end_time:
                return f"文件全为静音，跳过: {source_file}", "skipped"
            artist = get_artist_metadata(source_file, self.logger)
            ff_args = [
                '-ss', str(start_time),
                '-to', str(end_time),
                '-map', '0:a',
                '-map', '0:v?',
                '-c', 'copy',
                '-map_metadata', '-1',
                '-map_metadata:s:a', '-1',
                '-map_metadata:s:v', '-1'
            ]
            if artist:
                ff_args.extend(['-metadata', f'artist={artist}'])
            success, err = self._run_ffmpeg(source_file, target_file, ff_args)
            if success:
                return f"已切除静音: {source_file}", "cut"
            else:
                return f"静音切除失败: {source_file}, 错误: {err}", "error"
        except Exception as e:
            self.logger.error(f"静音切除失败: {source_file}, 错误: {e}")
            return f"静音切除失败: {source_file}", "error"

    def _copy_with_clean_metadata(self, source_file: str, target_file: str) -> Tuple[str, str]:
        artist = get_artist_metadata(source_file, self.logger)
        ff_args = [
            '-map', '0:a',
            '-map', '0:v?',
            '-c', 'copy',
            '-map_metadata', '-1',
            '-map_metadata:s:a', '-1',
            '-map_metadata:s:v', '-1'
        ]
        if artist:
            ff_args.extend(['-metadata', f'artist={artist}'])
        success, err = self._run_ffmpeg(source_file, target_file, ff_args)
        if success:
            return f"已复制并清理元数据: {source_file}", "copied"
        else:
            return f"复制失败: {source_file}, 错误: {err}", "error"