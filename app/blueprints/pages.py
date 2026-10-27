# -*- coding: utf-8 -*-
"""
页面路由：负责渲染 HTML 骨架，具体数据由前端通过 /api/* 接口获取。
"""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from app.utils import current_user, login_required

bp = Blueprint("pages", __name__)


@bp.route("/")
def index():
    if not current_user():
        return redirect(url_for("pages.login"))
    return redirect(url_for("pages.dashboard"))


@bp.route("/login")
def login():
    if current_user():
        return redirect(url_for("pages.dashboard"))
    return render_template("login.html", next=request.args.get("next", ""))


@bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", active="dashboard")


@bp.route("/sales")
@login_required
def sales():
    return render_template("sales.html", active="sales")


@bp.route("/loans")
@login_required
def loans():
    return render_template("loans.html", active="loans")


@bp.route("/collections")
@login_required
def collections():
    return render_template("collections.html", active="collections")


@bp.route("/assistant")
@login_required
def assistant():
    return render_template("assistant.html", active="assistant")


@bp.route("/stats")
@login_required
def stats():
    return render_template("stats.html", active="stats")


@bp.route("/system")
@login_required
def system():
    return render_template("system.html", active="system")
