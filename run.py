#!/usr/bin/env python3
import json
import time
from media_converter import ConversionTaskManager


def load_config(json_path: str):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('tasks', [])


def main():
    import sys
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    else:
        config_file = "media_converter/config.json"

    tasks = load_config(config_file)
    if not tasks:
        print("没有找到任务配置")
        return

    manager = ConversionTaskManager()
    for task in tasks:
        manager.add_task(task['name'], task['config'])

    manager.start_all()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n收到中断，正在停止...")
        manager.stop()


if __name__ == "__main__":
    main()