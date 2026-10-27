# -*- coding: utf-8 -*-
"""
销售人员管理接口（增删改查）
"""
from __future__ import annotations

from flask import Blueprint

from app.services import sales_service as svc
from app.utils import (arg, log_operation, ok, page_args, payload, role_required,
                       login_required, to_int, can_write)

bp = Blueprint("sales", __name__)


@bp.get("")
@login_required
def list_sales():
    page, size = page_args()
    return ok(svc.list_sales({
        "keyword": arg("keyword", ""),
        "dept": arg("dept", ""),
        "status": arg("status", ""),
    }, page, size))


@bp.get("/options")
@login_required
def options():
    return ok({
        "depts": svc.dept_options(),
        "can_write": can_write(),
    })


@bp.get("/<int:sales_id>")
@login_required
def detail(sales_id: int):
    return ok(svc.get_sales(sales_id))


@bp.post("")
@role_required("finance")
def create():
    data = payload()
    row = svc.create_sales(data)
    log_operation("销售人员", "新增", row["name"], f"新增销售人员 {row['name']}（{row['emp_no']}）")
    return ok(row, "销售人员新增成功")


@bp.put("/<int:sales_id>")
@role_required("finance")
def update(sales_id: int):
    row = svc.update_sales(sales_id, payload())
    log_operation("销售人员", "修改", row["name"], f"修改销售人员 {row['name']}（{row['emp_no']}）信息")
    return ok(row, "销售人员信息已更新")


@bp.delete("/<int:sales_id>")
@role_required("finance")
def delete(sales_id: int):
    row = svc.get_sales(sales_id)
    svc.delete_sales(sales_id)
    log_operation("销售人员", "删除", row["name"], f"删除销售人员 {row['name']}（{row['emp_no']}）")
    return ok(None, "销售人员已删除")
