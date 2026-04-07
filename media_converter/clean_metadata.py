import os
from typing import Tuple
from .base import BaseProcessor
from .utils import get_artist_metadata


class CleanMetadataProcessor(BaseProcessor):
    def process_file(self, source_file: str, target_file: str, **kwargs) -> Tuple[str, str]:
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
            return f"已清理元数据: {source_file}", "cleaned"
        else:
            return f"清理失败: {source_file}, 错误: {err}", "error"