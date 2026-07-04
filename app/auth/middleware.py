"""鉴权中间件 + 密码工具 + session 签名。

设计：
- AUTH_ENABLED=false：全部公开（本地开发）
- AUTH_ENABLED=true：
  - 白名单（公开）：/health, /docs, /openapi.json, /redoc, /ui/login, /api/auth/login, /favicon.ico
  - 其他路径：
    - 优先看 X-API-Key 头（服务间调用）
    - 其次看 session cookie（UI 登录后）
    - 都没有 → 401（API）或重定向 /ui/login（浏览器）
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import bcrypt
from fastapi import Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging import logger

SESSION_COOKIE = "rag_session"
# 公开路径（无需鉴权）：
# - /health 健康检查（监控用）
# - /ui/login /api/auth/login /api/auth/logout 登录链路
# - / 根路径（重定向到 /ui/）
# 注意：/docs /redoc /openapi.json 默认需鉴权（生产环境不暴露 API 结构）
# 如需本地开发时公开 Swagger，设 AUTH_ENABLED=false 即可
PUBLIC_PATHS = {
    "/health",
    "/ui/login",
    "/api/auth/login",
    "/api/auth/logout",
    "/favicon.ico",
    "/",
}


def hash_password(plain: str) -> str:
    """生成 bcrypt 哈希（命令行工具用）。"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _serializer() -> URLSafeTimedSerializer | None:
    secret = settings.auth_session_secret
    if not secret:
        return None
    return URLSafeTimedSerializer(secret, salt="rag-session")


def create_session_cookie(response: Response, username: str) -> None:
    """登录成功后写入签名 cookie。"""
    serializer = _serializer()
    if serializer is None:
        logger.warning("AUTH_SESSION_SECRET not set, cannot create session")
        return
    payload = {"u": username, "t": datetime.now(UTC).isoformat()}
    token = serializer.dumps(payload)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.auth_session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=False,  # Caddy 负责 TLS 终止；内网 HTTP 直连也通
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def verify_session(request: Request) -> str | None:
    """从 cookie 取 username；无效返回 None。"""
    serializer = _serializer()
    if serializer is None:
        return None
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        payload = serializer.loads(token, max_age=settings.auth_session_ttl_hours * 3600)
        return payload.get("u")
    except SignatureExpired:
        return None
    except BadSignature:
        return None


def verify_api_key(request: Request) -> bool:
    """检查 X-API-Key 头。"""
    if not settings.auth_api_key:
        return False
    provided = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not provided:
        return False
    return hmac.compare_digest(provided, settings.auth_api_key)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not settings.auth_enabled:
            return await call_next(request)

        path = request.url.path
        # 白名单（精确匹配 + 登录链路子路径）
        if path in PUBLIC_PATHS or path.startswith("/api/auth/"):
            return await call_next(request)

        # 优先 X-API-Key（服务间）
        if verify_api_key(request):
            request.state.auth_method = "api_key"
            return await call_next(request)

        # 其次 session cookie（UI）
        username = verify_session(request)
        if username:
            request.state.auth_method = "session"
            request.state.username = username
            return await call_next(request)

        # 未鉴权：API 返回 401，浏览器跳转登录
        accept = request.headers.get("accept", "")
        is_browser = "text/html" in accept
        wants_json = "application/json" in accept or path.startswith("/api/") or path.startswith("/collections") or path.startswith("/parse") or path.startswith("/ingest") or path.startswith("/retrieve") or path.startswith("/rerank")
        if is_browser and not wants_json:
            return RedirectResponse(url=f"/ui/login?next={path}", status_code=303)
        return JSONResponse(
            status_code=401,
            content={
                "code": "FAILED",
                "message": "authentication required",
                "error_code": "UNAUTHORIZED",
                "data": None,
            },
            headers={"WWW-Authenticate": 'Bearer realm="rag-service", error="missing_token"'},
        )


__all__ = [
    "AuthMiddleware",
    "SESSION_COOKIE",
    "clear_session_cookie",
    "create_session_cookie",
    "hash_password",
    "verify_api_key",
    "verify_password",
    "verify_session",
]
