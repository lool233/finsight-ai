# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— Flask 应用工厂
=====================================================================
技术栈：HTML + CSS + JavaScript + Flask + MySQL + LLM
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from config import config
from app import db
from app.utils import BizError, current_user

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config.from_object(config)
    app.json.ensure_ascii = False

    # ---------------- 蓝图注册 ----------------
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.pages import bp as pages_bp
    from app.blueprints.sales import bp as sales_bp
    from app.blueprints.loans import bp as loans_bp
    from app.blueprints.collections import bp as collections_bp
    from app.blueprints.stats import bp as stats_bp
    from app.blueprints.assistant import bp as assistant_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(sales_bp, url_prefix="/api/sales")
    app.register_blueprint(loans_bp, url_prefix="/api/loans")
    app.register_blueprint(collections_bp, url_prefix="/api/collections")
    app.register_blueprint(stats_bp, url_prefix="/api/stats")
    app.register_blueprint(assistant_bp, url_prefix="/api/assistant")

    # ---------------- 请求生命周期 ----------------
    @app.teardown_appcontext
    def _close_db(_exc=None):
        db.close_connection()

    @app.context_processor
    def inject_globals():
        return {
            "APP_NAME": config.APP_NAME,
            "APP_SUBTITLE": config.APP_SUBTITLE,
            "APP_VERSION": config.APP_VERSION,
            "user": current_user(),
            "OVERDUE_MONTHS": config.OVERDUE_MONTHS,
            "now": datetime.now(),
        }

    # ---------------- 错误处理 ----------------
    @app.errorhandler(BizError)
    def _handle_biz_error(exc: BizError):
        return jsonify({"code": exc.code, "success": False, "message": exc.message, "data": None}), \
            exc.http_status

    @app.errorhandler(404)
    def _handle_404(_exc):
        if request.path.startswith("/api/"):
            return jsonify({"code": 404, "success": False, "message": "接口不存在", "data": None}), 404
        return render_template("error.html", code=404, message="页面不存在"), 404

    @app.errorhandler(500)
    def _handle_500(exc):
        app.logger.exception("服务器内部错误: %s", exc)
        if request.path.startswith("/api/"):
            return jsonify({"code": 500, "success": False,
                            "message": f"服务器内部错误：{exc}", "data": None}), 500
        return render_template("error.html", code=500, message=f"服务器内部错误：{exc}"), 500

    @app.errorhandler(Exception)
    def _handle_exception(exc):
        from werkzeug.exceptions import HTTPException

        if isinstance(exc, HTTPException):
            return exc
        app.logger.exception("未捕获异常: %s", exc)
        if request.path.startswith("/api/"):
            return jsonify({"code": 500, "success": False,
                            "message": f"系统异常：{exc}", "data": None}), 500
        return render_template("error.html", code=500, message=f"系统异常：{exc}"), 500

    # ---------------- 模板过滤器 ----------------
    @app.template_filter("money")
    def _money(value) -> str:
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return "0.00"

    @app.template_filter("d")
    def _date(value) -> str:
        return str(value)[:10] if value else ""

    return app


__all__ = ["create_app"]
