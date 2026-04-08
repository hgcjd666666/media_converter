import os
import sys
import logging
from pathlib import Path
from typing import Tuple, Set, Optional

from .base import BaseProcessor
from .utils import get_audio_duration, detect_silences, get_artist_metadata

# ========== 硬编码调试开关 ==========
DEBUG = False  # 设为 True 输出详细调试信息
# ==================================

# 全局集合：记录已报告的错误消息（避免重复写入日志文件）
_reported_errors = set()
_error_log_file = "silence_errors.log"

def _log_error_once(message: str):
    """将错误消息写入文件，相同消息只写一次"""
    if message in _reported_errors:
        return
    _reported_errors.add(message)
    try:
        with open(_error_log_file, 'a', encoding='utf-8') as f:
            f.write(message + "\n")
    except Exception:
        pass  # 忽略日志写入错误


class CutSilenceProcessor(BaseProcessor):
    def process_file(self, source_file: str, target_file: str,
                     threshold: str = '-70dB', min_duration: float = 0.1, **kwargs) -> Tuple[str, str]:
        try:
            total_duration = get_audio_duration(source_file, self.logger)
            # 静音检测可能失败
            try:
                silences = detect_silences(source_file, threshold, min_duration, self.logger)
            except Exception as e:
                error_msg = f"静音检测异常: {source_file}, 错误: {e}"
                self.logger.error(error_msg)
                _log_error_once(f"静音检测异常（跳过切除）: {e}")
                if DEBUG:
                    import traceback
                    traceback.print_exc()
                # 静音检测失败，降级为仅复制并清理元数据
                return self._copy_with_clean_metadata(source_file, target_file)

            if not silences:
                # 无静音段，直接复制并清理元数据
                return self._copy_with_clean_metadata(source_file, target_file)

            start_time = 0.0
            if silences[0][0] < 0.1:
                start_time = silences[0][1]
            end_time = total_duration
            if total_duration - silences[-1][1] < 0.1:
                end_time = silences[-1][0]

            if start_time >= end_time:
                self.logger.warning(f"文件全为静音，跳过切除: {source_file}")
                return self._copy_with_clean_metadata(source_file, target_file)

            artist = get_artist_metadata(source_file, self.logger)
            ff_args = [
                '-ss', str(start_time),
                '-to', str(end_time),
                '-map', '0:a',
                '-c', 'copy',
                '-map_metadata', '-1',
                '-map_metadata:s:a', '-1'
            ]
            if artist:
                ff_args.extend(['-metadata', f'artist={artist}'])

            success, err = self._run_ffmpeg(source_file, target_file, ff_args)
            if success:
                return f"已切除静音: {source_file}", "cut"
            else:
                # 切除失败，降级为复制并清理元数据
                self.logger.error(f"静音切除执行失败: {source_file}, 错误: {err}")
                _log_error_once(f"静音切除执行失败: {err[:200]}")
                return self._copy_with_clean_metadata(source_file, target_file)

        except Exception as e:
            self.logger.error(f"静音切除过程异常: {source_file}, 错误: {e}")
            _log_error_once(f"静音切除过程异常: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()
            return self._copy_with_clean_metadata(source_file, target_file)

    def _copy_with_clean_metadata(self, source_file: str, target_file: str) -> Tuple[str, str]:
        """仅复制文件并清理元数据（不切除静音）"""
        artist = get_artist_metadata(source_file, self.logger)
        ff_args = [
            '-map', '0:a',
            '-c', 'copy',
            '-map_metadata', '-1',
            '-map_metadata:s:a', '-1'
        ]
        if artist:
            ff_args.extend(['-metadata', f'artist={artist}'])
        success, err = self._run_ffmpeg(source_file, target_file, ff_args)
        if success:
            return f"已复制并清理元数据（静音检测失败/跳过）: {source_file}", "copied"
        else:
            # 如果连复制都失败，记录错误并返回失败
            self.logger.error(f"复制并清理元数据失败: {source_file}, 错误: {err}")
            _log_error_once(f"复制并清理元数据失败: {err[:200]}")
            return f"复制失败: {source_file}, 错误: {err}", "error"