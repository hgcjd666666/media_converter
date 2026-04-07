Media Converter - 媒体文件批量处理工具

基于 FFmpeg 的媒体文件批量处理工具，支持格式转换、静音切除、元数据整理，并提供任务调度与依赖管理。

主要特性

· 三种处理类型：格式转换（convert）、静音切除（cut_silence）、元数据清理（metadata_clean）
· 复合任务：将多个步骤串联为一个任务，中间结果不落盘（文件级流水线）
· 智能跳过：通过 MD5 + 文件大小/修改时间快速判断，避免重复处理
· 并行处理：多线程并行处理文件，可配置并发数
· 周期调度：基于 APScheduler，支持周期执行（秒级）
· 依赖管理：任务间可设置依赖关系，自动触发
· RAM disk 友好：临时文件用完即删，避免占用大量空间
· 配置驱动：所有任务通过 JSON 配置文件定义

系统要求

· Python 3.8+
· FFmpeg（包含 ffmpeg 和 ffprobe），需加入系统 PATH

安装依赖：

```bash
pip install apscheduler
```

项目结构

```
media_converter/
├── __init__.py
├── base.py            # 基类，提供公共方法
├── convert.py         # 格式转换处理器
├── cut_silence.py     # 静音切除处理器
├── clean_metadata.py  # 元数据清理处理器
├── composite.py       # 复合任务处理器
├── manager.py         # 任务管理器（调度、依赖）
├── utils.py           # 工具函数（时长、静音检测、元数据读取）
└── config.json        # 任务配置文件
run.py                 # 启动脚本
```

配置说明

编辑 config.json，示例如下：

```json
{
  "tasks": [
    {
      "name": "yp",
      "config": {
        "type": "composite",
        "source_dir": "1a/音频",
        "target_dir": "R:/Temp/音频_cut",
        "source_exts": [".flac", ".mp3", ".m4a", ".ogg"],
        "max_workers": 16,
        "interval": 30,
        "cleanup_ignore_dirs": [".verysync"],
        "steps": [
          { "type": "metadata_clean" },
          { "type": "cut_silence", "threshold": "-70dB", "min_duration": 1 }
        ]
      }
    },
    {
      "name": "video",
      "config": {
        "type": "convert",
        "source_dir": "1a/荤-视频",
        "target_dir": "荤-视频_h265",
        "ffmpeg_args": ["-c:v", "libx265", "-crf", "35", "-c:a", "copy", "-preset", "veryslow"],
        "target_ext": ".mp4",
        "source_exts": [".mp4"],
        "max_workers": 1,
        "interval": 30
      }
    }
  ]
}
```

参数说明

· name：任务唯一标识
· type：convert / cut_silence / metadata_clean / composite
· source_dir：源目录
· target_dir：目标目录
· source_exts：处理的文件扩展名列表（大小写不敏感）
· max_workers：并发线程数
· interval：周期调度间隔（秒），设为 0 表示仅依赖触发或手动触发
· depends_on：依赖的任务名列表（仅对非复合任务有效）
· cleanup_ignore_dirs：清理多余文件时忽略的目录（相对路径）
· ffmpeg_args：convert 专用，FFmpeg 参数列表
· target_ext：convert 专用，目标文件扩展名（含点）
· threshold / min_duration：cut_silence 专用，静音检测参数
· steps：composite 专用，子任务列表

运行

```bash
python run.py [config.json路径]
```

默认读取 media_converter/config.json。

程序启动后会自动：

· 执行所有无依赖任务的首次运行
· 按 interval 周期调度任务
· 任务完成后自动触发依赖它的任务

按 Ctrl+C 停止。

注意事项

1. 临时目录：每个任务或复合任务会在系统临时目录（或 R:/Temp 等）创建临时子目录，处理完成后自动删除。
2. RAM disk：如果临时目录位于内存盘（如 R:/Temp），请确保内存足够，建议 max_workers 设置合理（如 4~8），避免同时处理过多大文件。
3. 跳过逻辑：工具会比较源文件与目标文件的内容（大小+修改时间+MD5），内容相同则跳过，不会重复处理。
4. 元数据清理：仅保留 artist 标签和图片流（attached picture），删除其他所有元数据。
5. 静音切除：切除开头和结尾的静音段，不重新编码（-c copy），仅修改容器。
6. 复合任务：每个文件独立流水线处理，中间结果不落盘，处理完即删除临时文件，适合内存盘场景。

许可证

MIT