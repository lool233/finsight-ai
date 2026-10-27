# -*- coding: utf-8 -*-
"""
认证接口：登录、退出、当前用户信息。
"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, session

from app import db
from app.utils import BizError, current_user, log_operation, ok, payload, require

bp = Blueprint("auth", __name__)


@bp.post("/login")
def login():
    data = payload()
    require(data, "username", "password")
    from app.utils import hash_password

    user = db.query_one(
        # 注意：role 在 MySQL 8.0 中是保留字，必须使用反引号引用（SQLite 亦兼容）
        "SELECT id, username, password_hash, real_name, `role` AS role, dept, phone, status"
        " FROM sys_user WHERE username = %s",
        (str(data["username"]).strip(),),
    )
    if not user or user["password_hash"] != hash_password(str(data["password"])):
        raise BizError("账号或密码错误")
    if int(user.get("status") or 0) != 1:
        raise BizError("该账号已被停用，请联系系统管理员")

    session.permanent = True
    session["user"] = {
        "id": user["id"],
        "username": user["username"],
        "real_name": user["real_name"],
        "role": user["role"],
        "dept": user["dept"],
        "phone": user["phone"],
    }
    db.affected("UPDATE sys_user SET last_login_at = %s WHERE id = %s",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user["id"]))
    log_operation("认证", "登录", user["username"], f"{user['real_name']} 登录系统")
    return ok(session["user"], "登录成功")


@bp.post("/logout")
def logout():
    user = current_user()
    if user:
        log_operation("认证", "退出", user.get("username", ""), "退出系统")
    session.clear()
    return ok(None, "已安全退出")


@bp.get("/profile")
def profile():
    user = current_user()
    if not user:
        raise BizError("未登录", code=401, http_status=401)
    return ok(user)


@bp.post("/change-password")
def change_password():
    from app.utils import hash_password

    user = current_user()
    if not user:
        raise BizError("未登录", code=401, http_status=401)
    data = payload()
    require(data, "old_password", "new_password")
    row = db.query_one("SELECT password_hash FROM sys_user WHERE id = %s", (user["id"],))
    if not row or row["password_hash"] != hash_password(str(data["old_password"])):
        raise BizError("原密码不正确")
    if len(str(data["new_password"])) < 6:
        raise BizError("新密码长度不能少于 6 位")
    db.affected("UPDATE sys_user SET password_hash = %s WHERE id = %s",
                (hash_password(str(data["new_password"])), user["id"]))
    log_operation("认证", "修改密码", user["username"], "用户修改登录密码")
    return ok(None, "密码修改成功，请重新登录")
