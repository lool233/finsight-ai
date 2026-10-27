# -*- coding: utf-8 -*-
"""
借资信息管理接口（增删改查 + 还款登记）
"""
from __future__ import annotations

from flask import Blueprint

from config import config
from app.services import loan_service as svc
from app.services import sales_service
from app.utils import (arg, can_write, current_user, log_operation, login_required, ok,
                       page_args, payload, role_required)

bp = Blueprint("loans", __name__)


@bp.get("")
@login_required
def list_loans():
    page, size = page_args()
    args = {
        "keyword": arg("keyword", ""),
        "dept": arg("dept", ""),
        "sales_id": arg("sales_id", ""),
        "loan_type": arg("loan_type", ""),
        "status": arg("status", ""),
        "start_date": arg("start_date", ""),
        "end_date": arg("end_date", ""),
        "min_amount": arg("min_amount", ""),
        "max_amount": arg("max_amount", ""),
        "overdue_only": arg("overdue_only", ""),
    }
    data = svc.list_loans(args, page, size)
    data["can_write"] = can_write()
    return ok(data)


@bp.get("/meta")
@login_required
def meta():
    return ok({
        "loan_types": svc.LOAN_TYPES,
        "status_list": svc.LOAN_STATUS,
        "depts": sales_service.dept_options(),
        "overdue_months": config.OVERDUE_MONTHS,
        "can_write": can_write(),
    })


@bp.get("/<int:loan_id>")
@login_required
def detail(loan_id: int):
    loan = svc.get_loan(loan_id)
    return ok({
        "loan": loan,
        "repayments": svc.get_repayments(loan_id),
        "collections": _collections_of(loan_id),
        "can_write": can_write(),
    })


@bp.post("")
@role_required("finance")
def create():
    user = current_user() or {}
    row = svc.create_loan(payload(), operator=user.get("real_name") or user.get("username", ""))
    log_operation("借资管理", "新增", row["loan_no"],
                  f"为 {row['sales_name']} 新增借资 {row['amount']} 元，借资日期 {row['loan_date']}")
    return ok(row, "借资信息登记成功")


@bp.put("/<int:loan_id>")
@role_required("finance")
def update(loan_id: int):
    row = svc.update_loan(loan_id, payload())
    log_operation("借资管理", "修改", row["loan_no"], f"修改借资记录，金额 {row['amount']} 元")
    return ok(row, "借资信息已更新")


@bp.delete("/<int:loan_id>")
@role_required("finance")
def delete(loan_id: int):
    row = svc.get_loan(loan_id)
    svc.delete_loan(loan_id)
    log_operation("借资管理", "删除", row["loan_no"], f"删除借资记录（逻辑删除），金额 {row['amount']} 元")
    return ok(None, "借资记录已删除")


# ---------------------------------------------------------------------------
# 还款登记
# ---------------------------------------------------------------------------
@bp.post("/<int:loan_id>/repayments")
@role_required("finance")
def add_repayment(loan_id: int):
    user = current_user() or {}
    row = svc.add_repayment(loan_id, payload(),
                            operator=user.get("real_name") or user.get("username", ""))
    log_operation("还款管理", "登记还款", row["loan_no"],
                  f"登记还款，已还 {row['repaid_amount']} 元，状态 {row['status']}")
    return ok(row, "还款登记成功")


@bp.delete("/repayments/<int:repayment_id>")
@role_required("finance")
def delete_repayment(repayment_id: int):
    row = svc.delete_repayment(repayment_id)
    log_operation("还款管理", "删除还款记录", row["loan_no"], "删除一条还款流水并重算借资状态")
    return ok(row, "还款记录已删除")


def _collections_of(loan_id: int):
    from app import db

    return db.query_all(
        """SELECT id, batch_no, overdue_days, overdue_amount, collection_level, channel, content,
                  generated_by, llm_model, send_status, sent_at, remark, created_at
             FROM collection_record WHERE loan_id = %s ORDER BY id DESC""",
        (loan_id,),
    )
