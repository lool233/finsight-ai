# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 通用工具
=====================================================================
统一 JSON 响应格式、登录与权限校验、分页参数解析、操作日志记录。
"""
from __future__ import annotations

import functools
import hashlib
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Tuple

from flask import jsonify, request, session

from config import config
from app import db


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------
def ok(data: Any = None, message: str = "操作成功") -> Any:
    return jsonify({"code": 0, "success": True, "message": message, "data": data})


def fail(message: str = "操作失败", code: int = 1, http_status: int = 200, data: Any = None) -> Any:
    return jsonify({"code": code, "success": False, "message": message, "data": data}), http_status


class BizError(Exception):
    """业务异常，统一被全局错误处理器转换为 JSON 响应。"""

    def __init__(self, message: str, code: int = 1, http_status: int = 200):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


# ---------------------------------------------------------------------------
# 口令散列
# ---------------------------------------------------------------------------
def hash_password(plain: str) -> str:
    return hashlib.sha256((plain + config.PASSWORD_SALT).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 登录 / 权限
# ---------------------------------------------------------------------------
def current_user() -> Optional[Dict[str, Any]]:
    return session.get("user")


def login_required(view: Callable) -> Callable:
    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        if not current_user():
            if request.path.startswith("/api/"):
                return fail("登录状态已失效，请重新登录", code=401, http_status=401)
            from flask import redirect, url_for
            return redirect(url_for("pages.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapper


def role_required(*roles: str) -> Callable:
    """角色权限校验：admin 拥有全部权限。"""

    def decorator(view: Callable) -> Callable:
        @functools.wraps(view)
        @login_required
        def wrapper(*args: Any, **kwargs: Any):
            user = current_user() or {}
            role = user.get("role")
            if role == "admin" or role in roles:
                return view(*args, **kwargs)
            return fail(f"当前角色（{role}）无权执行该操作", code=403, http_status=403)

        return wrapper

    return decorator


def can_write() -> bool:
    """当前用户是否具备数据维护权限（财务与管理员可维护）。"""
    user = current_user() or {}
    return user.get("role") in ("admin", "finance")


# ---------------------------------------------------------------------------
# 请求参数
# ---------------------------------------------------------------------------
def arg(name: str, default: Any = None) -> Any:
    value = request.args.get(name)
    return default if value is None or value == "" else value


def payload() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {k: v for k, v in request.form.items()}


def page_args(default_size: int = 10) -> Tuple[int, int]:
    try:
        page = max(1, int(arg("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        size = int(arg("size", default_size))
    except (TypeError, ValueError):
        size = default_size
    size = min(max(size, 1), 200)
    return page, size


def like(value: str) -> str:
    """构造 LIKE 参数（避免在 SQL 中拼字符串，兼容多数据库）。"""
    return f"%{value}%"


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def require(data: Dict[str, Any], *fields: str) -> None:
    missing = [f for f in fields if data.get(f) in (None, "", [])]
    if missing:
        raise BizError(f"缺少必填参数：{'、'.join(missing)}")


# ---------------------------------------------------------------------------
# 操作日志
# ---------------------------------------------------------------------------
def log_operation(module: str, action: str, target: str = "", detail: str = "") -> None:
    try:
        user = current_user() or {}
        db.execute(
            "INSERT INTO operation_log (user_id, username, module, action, target, detail, ip, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                user.get("id"),
                user.get("username"),
                module,
                action,
                target[:100],
                detail[:500],
                request.remote_addr,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
    except Exception:  # 日志记录失败不影响主业务流程
        pass
