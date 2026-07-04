"""pytest 全局 fixtures。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("METADATA_DB_PATH", ":memory:")
# 测试环境强制关闭鉴权（避免 .env 中 AUTH_ENABLED=true 导致所有 API 401）
os.environ.setdefault("AUTH_ENABLED", "false")


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "meta.db"


@pytest.fixture()
def sample_markdown() -> str:
    return (
        "# 项目说明\n\n"
        "这是一个示例项目。\n\n"
        "## 1 安装\n\n"
        "运行 `pip install -e .`。\n\n"
        "## 2 使用\n\n"
        "直接调用 main.py。\n\n"
        "- 列表项 A\n"
        "- 列表项 B\n"
    )


@pytest.fixture()
def sample_text() -> str:
    return "第一段内容。\n\n第二段内容。\n\n第三段内容。"
