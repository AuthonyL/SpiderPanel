"""配置查找、路径解析与命令行覆盖。"""

import json
import os
from pathlib import Path

from . import rules
from .thresholds import load_thresholds


CONFIG_ENV = "SPIDERPANEL_CONFIG"


class ConfigError(ValueError):
    pass


def spider_root():
    return Path(os.environ.get(rules.SPIDER_DIR_ENV, "~/.wq_spider")).expanduser()


def _read(path, missing_ok=False):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("顶层必须是 JSON 对象")
        return value
    except FileNotFoundError as error:
        if missing_ok:
            return {}
        raise ConfigError(f"配置文件不存在：{path}") from error
    except (OSError, ValueError, RecursionError) as error:
        raise ConfigError(f"配置文件无法读取或格式无效：{path}") from error


def _path(value, base):
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("配置路径必须是非空字符串")
    try:
        path = Path(value).expanduser()
        return (base / path).resolve()
    except (OSError, ValueError, RuntimeError) as error:
        raise ConfigError("配置路径无效") from error


def load_config(path=None):
    selected = path if path is not None else os.environ.get(CONFIG_ENV)
    explicit = selected is not None
    path = _path(str(selected), Path.cwd()) if explicit else (spider_root() / "config.json").resolve()
    value = _read(path, missing_ok=not explicit)
    goal = value.get("daily_goal", rules.DAILY_CANDIDATE_GOAL)
    if type(goal) is not int or goal <= 0:
        raise ConfigError("配置 daily_goal 必须是正整数")
    progress = _path(value["progress_file"], path.parent) if "progress_file" in value else None
    candidates = value.get("candidate_files", [])
    if not isinstance(candidates, list):
        raise ConfigError("配置 candidate_files 必须是路径字符串列表")
    return {"progress_file": progress,
            "candidate_files": [_path(item, path.parent) for item in candidates],
            "thresholds": load_thresholds(value.get("thresholds")), "daily_goal": goal}


def configure(options):
    result = load_config(options.config)
    if options.progress_file is not None:
        result["progress_file"] = _path(options.progress_file, Path.cwd())
    if options.candidates_file is not None:
        result["candidate_files"] = [_path(item, Path.cwd()) for item in options.candidates_file]
    if options.thresholds is not None:
        result["thresholds"] = load_thresholds(_read(_path(options.thresholds, Path.cwd())))
    return result
