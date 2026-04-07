import os
from pathlib import Path
from typing import List, Set, Optional, Tuple
from .base import BaseProcessor


class ConvertProcessor(BaseProcessor):
    def process_file(self, source_file: str, target_file: str,
                     ffmpeg_args: List[str], target_ext: str = None, **kwargs) -> Tuple[str, str]:
        if target_ext:
            target_file = str(Path(target_file).with_suffix(target_ext))
        success, err = self._run_ffmpeg(source_file, target_file, ffmpeg_args)
        if success:
            return f"转换成功: {source_file} -> {target_file}", "converted"
        else:
            return f"转换失败: {source_file}, 错误: {err}", "error"