# -*- coding: utf-8 -*-
"""
统计看板接口：总览、部门、类型、月度趋势、逾期账龄、欠款排名、系统状态。
"""
from __future__ import annotations

from flask import Blueprint

from app import db
from app.services import loan_service as svc
from app.utils import arg, login_required, ok, to_int

bp = Blueprint("stats", __name__)


@bp.get("/overview")
@login_required
def overview():
    return ok(svc.overview())


@bp.get("/dashboard")
@login_required
def dashboard():
    """看板一次性返回全部统计数据，减少前端请求次数。"""
    return ok({
        "overview": svc.overview(),
        "dept": svc.by_dept(),
        "type": svc.by_type(),
        "trend": svc.by_month(to_int(arg("months", 6)) or 6),
        "aging": svc.overdue_aging(),
        "top": svc.top_debtors(8),
        "recent_loans": svc.list_loans({}, 1, 6)["items"],
        "recent_collections": db.query_all(
            """SELECT c.id, c.batch_no, c.collection_level, c.overdue_days, c.overdue_amount,
                      c.send_status, c.generated_by, c.created_at, s.name AS sales_name, l.loan_no
                 FROM collection_record c
                 JOIN sales_person s ON s.id = c.sales_id
                 JOIN loan_record l ON l.id = c.loan_id
                ORDER BY c.id DESC LIMIT 6"""
        ),
    })


@bp.get("/dept")
@login_required
def by_dept():
    return ok(svc.by_dept())


@bp.get("/type")
@login_required
def by_type():
    return ok(svc.by_type())


@bp.get("/trend")
@login_required
def trend():
    return ok(svc.by_month(to_int(arg("months", 6)) or 6))


@bp.get("/aging")
@login_required
def aging():
    return ok(svc.overdue_aging())


@bp.get("/top")
@login_required
def top():
    return ok(svc.top_debtors(to_int(arg("limit", 10)) or 10))


@bp.get("/system")
@login_required
def system_info():
    from app.llm import llm_client
    from app.services.sms_gateway import sms_gateway
    from config import config

    return ok({
        "database": db.ping(),
        "llm": llm_client.status(),
        "sms": sms_gateway.status(),
        "app": {"name": config.APP_NAME, "version": config.APP_VERSION},
        "business": {
            "overdue_months": config.OVERDUE_MONTHS,
            "collection_interval_days": config.COLLECTION_INTERVAL_DAYS,
            "level2_days": config.COLLECTION_LEVEL2_DAYS,
            "level3_days": config.COLLECTION_LEVEL3_DAYS,
        },
        "logs": db.query_all(
            """SELECT username, module, action, target, detail, ip, created_at
                 FROM operation_log ORDER BY id DESC LIMIT 15"""),
    })
