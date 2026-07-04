"""loguru 统一日志配置（v2 优化版）。

新增能力：
- 结构化字段：每条日志带 service / version / env / request_id
- 双格式：text（开发友好） / json（生产 ELK/Loki 友好）
- 多 sink：stdout + 文件（按大小/日期轮转，可选）
- 异常 backtrace=True：错误时打印完整变量上下文
- contextvar 绑定：request_id 自动透传到子任务

配置（环境变量）：
- LOG_LEVEL=INFO
- LOG_FORMAT=text | json
- LOG_FILE_PATH=logs/rag.log   留空则不写文件
- LOG_ROTATION=20 MB
- LOG_RETENTION=14 days
- LOG_BACKTRACE=true
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from loguru import logger as _logger

from app.core.config import settings
from app.core.request_context import current_request_id

_CONFIGURED = False


def _env_tag() -> str:
    import os

    return os.environ.get("RAG_ENV") or os.environ.get("ENV") or "dev"


def _common_extra() -> dict[str, Any]:
    return {
        "service": "quillrag",
        "version": "0.3.0",
        "env": _env_tag(),
        "request_id": current_request_id() or "-",
    }


def _text_formatter(record: Any) -> str:
    rid = current_request_id() or ""
    rid_tag = f"<dim>[{rid[:8]}]</dim> " if rid else ""
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
        "<level>{level: <8}</level> "
        f"{rid_tag}"
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
        + "{exception}"
    )


def _json_formatter(record: Any) -> str:
    payload: dict[str, Any] = {
        "ts": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": record["name"],
        "func": record["function"],
        "line": record["line"],
        "msg": record["message"],
    }
    payload.update(_common_extra())
    if record.get("extra"):
        for k, v in record["extra"].items():
            if k not in payload:
                payload[k] = v
    if record["exception"]:
        payload["exception"] = "".join(
            traceback.format_exception(
                type(record["exception"].value),
                record["exception"].value,
                record["exception"].traceback,
            )
        )
    return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str | None = None):
    global _CONFIGURED
    if _CONFIGURED:
        return _logger
    _CONFIGURED = True
    _logger.remove()

    log_level = (level or getattr(settings, "log_level", "INFO")).upper()
    fmt = getattr(settings, "log_format", "text").lower()
    backtrace = bool(getattr(settings, "log_backtrace", True))

    if fmt == "json":
        sink_format = _json_formatter
    else:
        sink_format = _text_formatter

    _logger.add(
        sys.stdout,
        level=log_level,
        format=sink_format,
        backtrace=backtrace,
        diagnose=False,
        enqueue=False,
        colorize=fmt != "json",
    )

    file_path = getattr(settings, "log_file_path", None)
    if file_path:
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        _logger.add(
            file_path,
            level=log_level,
            format=_json_formatter,
            rotation=getattr(settings, "log_rotation", "20 MB"),
            retention=getattr(settings, "log_retention", "14 days"),
            compression="zip",
            backtrace=backtrace,
            diagnose=False,
            enqueue=True,
            colorize=False,
        )

    _logger.debug(
        f"logging initialized: level={log_level} format={fmt} file={file_path or 'off'}"
    )
    return _logger


logger = configure_logging()


__all__ = ["configure_logging", "logger"]
