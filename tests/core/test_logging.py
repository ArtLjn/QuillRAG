"""日志优化模块单测。"""

from __future__ import annotations

import pytest

from app.core import redact
from app.core.request_context import (
    current_request_id,
    gen_request_id,
    reset_request_context,
    set_request_id,
)


def test_secret_redact_keeps_prefix_and_suffix() -> None:
    assert redact.secret("sk-abcdef1234567890") == "sk-a...7890"
    assert redact.secret("short") == "***"
    assert redact.secret("") == "(empty)"
    assert redact.secret(None) == "(empty)"


def test_url_redact_strips_credentials() -> None:
    assert redact.url("https://user:pass@example.com/path") == "https://example.com/path"
    assert redact.url("https://example.com:6333") == "https://example.com:6333"
    assert redact.url("http://localhost:9000/v1") == "http://localhost:9000/v1"


def test_dict_keys_redact_secrets() -> None:
    payload = {
        "api_key": "sk-abcdef1234567890",
        "name": "demo",
        "embedding": {"api_key": "AIzaXYZabcdefghij", "model": "gemini"},
        "metadata": {"source": "test"},
    }
    redacted = redact.dict_keys(payload)
    assert redacted["api_key"] == "sk-a...7890"
    assert redacted["name"] == "demo"
    assert redacted["embedding"]["api_key"] == "AIza...ghij"
    assert redacted["metadata"]["source"] == "test"


def test_request_id_generate_is_unique_and_short() -> None:
    a = gen_request_id()
    b = gen_request_id()
    assert a != b
    assert len(a) == 12


def test_request_id_set_and_get() -> None:
    reset_request_context()
    assert current_request_id() is None
    set_request_id("abc123def456")
    assert current_request_id() == "abc123def456"
    reset_request_context()
    assert current_request_id() is None


def test_request_logging_middleware_injects_request_id() -> None:
    """端到端：HTTP 请求带 X-Request-ID 时透传，不带时自动生成。"""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        # 不带 X-Request-ID
        response = client.get("/health")
        assert response.status_code == 200
        assert response.headers.get("X-Request-ID"), "response 应带回 X-Request-ID"

        # 带 X-Request-ID
        response = client.get("/health", headers={"X-Request-ID": "test-req-12345"})
        assert response.headers.get("X-Request-ID") == "test-req-12345"


def test_text_formatter_includes_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """text 格式日志带 request_id 前 8 位。"""
    set_request_id("abcdef1234567890")
    try:
        from app.core.logging import _text_formatter

        # loguru record 是 dict-like
        fake_record = {
            "time": None,
            "level": type("L", (), {"name": "INFO"})(),
            "name": "app.test",
            "function": "fn",
            "line": 42,
            "message": "hello",
            "exception": None,
        }
        formatter = _text_formatter(fake_record)
        # text_formatter 返回 loguru 模板（含 {message}），request_id 被直接嵌入
        assert "abcdef12" in formatter
        assert "{message}" in formatter
    finally:
        reset_request_context()


def test_json_formatter_outputs_valid_json() -> None:
    """JSON 格式日志可被 json 解析。"""
    import json as json_mod
    from datetime import datetime

    from app.core.logging import _json_formatter

    class FakeExc:
        value = ValueError("boom")
        traceback = None

    fake_record = {
        "time": datetime(2026, 7, 3, 10, 0, 0),
        "level": type("L", (), {"name": "ERROR"})(),
        "name": "app.test",
        "function": "fn",
        "line": 42,
        "message": "error happened",
        "exception": FakeExc(),
        "extra": {},
    }

    output = _json_formatter(fake_record)
    payload = json_mod.loads(output)
    assert payload["level"] == "ERROR"
    assert payload["msg"] == "error happened"
    assert payload["service"] == "quillrag"
