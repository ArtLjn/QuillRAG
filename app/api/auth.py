"""鉴权 API：登录 / 登出 / 当前用户。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.middleware import (
    clear_session_cookie,
    create_session_cookie,
    verify_password,
    verify_session,
)
from app.core.config import settings
from app.core.response import ApiResponse

router = APIRouter(tags=["auth"])

_TEMPLATES_DIR = Path(__file__).parent.parent / "ui" / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/ui/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = "/ui/") -> HTMLResponse:
    """登录页（公开）。"""
    if not settings.auth_enabled:
        return RedirectResponse(url=next, status_code=303)
    # 已登录直接跳走
    username = verify_session(request)
    if username:
        return RedirectResponse(url=next, status_code=303)
    return _templates.TemplateResponse(
        request,
        "login.html",
        {"title": "登录 · quillrag", "next": next, "error": None},
    )


@router.post("/ui/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/ui/"),
):
    """表单登录（浏览器友好，登录后回跳 next）。"""
    if not settings.auth_enabled:
        return RedirectResponse(url=next or "/ui/", status_code=303)
    if not _check_credentials(username, password):
        return _templates.TemplateResponse(
            request,
            "login.html",
            {"title": "登录 · quillrag", "next": next, "error": "用户名或密码错误"},
            status_code=401,
        )
    response = RedirectResponse(url=next or "/ui/", status_code=303)
    create_session_cookie(response, username)
    return response


@router.post("/api/auth/login")
async def api_login(username: str = Form(...), password: str = Form(...)):
    """API 登录（curl/服务调用用，返回 session cookie）。"""
    if not settings.auth_enabled:
        return ApiResponse.ok({"enabled": False})
    if not _check_credentials(username, password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    from fastapi.responses import JSONResponse

    resp = JSONResponse(content=ApiResponse.ok({"username": username}).model_dump())
    create_session_cookie(resp, username)
    return resp


@router.post("/api/auth/logout")
async def api_logout(request: Request):
    """登出，清 cookie。"""
    from fastapi.responses import JSONResponse

    resp = JSONResponse(content=ApiResponse.ok({"logged_out": True}).model_dump())
    clear_session_cookie(resp)
    return resp


@router.get("/ui/logout")
async def logout_redirect() -> RedirectResponse:
    """UI 登出，回登录页。"""
    response = RedirectResponse(url="/ui/login", status_code=303)
    clear_session_cookie(response)
    return response


def _check_credentials(username: str, password: str) -> bool:
    if not settings.auth_password_hash:
        return False
    if username != settings.auth_username:
        return False
    return verify_password(password, settings.auth_password_hash)


__all__ = ["router"]
