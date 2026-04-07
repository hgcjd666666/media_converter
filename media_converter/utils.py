import re
import subprocess
from typing import List, Tuple, Optional
import logging


def get_audio_duration(file_path: str, logger: logging.Logger = None) -> float:
    """获取音频时长（秒）"""
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', check=True)
        output = result.stdout.strip()
        if output:
            return float(output)
        else:
            raise RuntimeError(f"无法获取音频时长，输出为空: {file_path}")
    except Exception as e:
        if logger:
            logger.error(f"获取音频时长失败: {file_path}, 错误: {e}")
        raise


def detect_silences(file_path: str, threshold: str, min_duration: float,
                    logger: logging.Logger = None) -> List[Tuple[float, float]]:
    """检测所有静音段，返回 [(start, end), ...]"""
    cmd = [
        'ffmpeg',
        '-i', file_path,
        '-af', f'silencedetect=noise={threshold}:d={min_duration}',
        '-f', 'null',
        '-'
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', check=False)
        output = result.stderr
        if not output:
            if logger:
                logger.warning(f"静音检测无输出: {file_path}")
            return []
    except Exception as e:
        if logger:
            logger.error(f"静音检测执行失败: {file_path}, 错误: {e}")
        return []

    start_pattern = r'silence_start:\s+([0-9.]+)'
    end_pattern = r'silence_end:\s+([0-9.]+)'
    starts = [float(m) for m in re.findall(start_pattern, output)]
    ends = [float(m) for m in re.findall(end_pattern, output)]
    if len(starts) != len(ends):
        if logger:
            logger.warning(f"静音段检测结果异常: starts={len(starts)}, ends={len(ends)}")
        min_len = min(len(starts), len(ends))
        return list(zip(starts[:min_len], ends[:min_len]))
    return list(zip(starts, ends))


def get_artist_metadata(file_path: str, logger: logging.Logger = None) -> Optional[str]:
    """提取 artist 元数据"""
    # 优先从音频流获取
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'a:0',
        '-show_entries', 'stream_tags=artist',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', check=False)
        artist = result.stdout.strip()
        if artist:
            return artist
    except Exception:
        pass
    # 降级：从全局格式获取
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format_tags=artist',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', check=False)
        artist = result.stdout.strip()
        return artist if artist else None
    except Exception:
        return None