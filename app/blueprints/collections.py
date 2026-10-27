# -*- coding: utf-8 -*-
"""
借资催还接口（LLM 生成催还记录 + 短信下发）
=====================================================================
- GET  /api/collections/overdue      查询逾期未还、需要催还的借资台账
- POST /api/collections/run          执行催还批处理（LLM 分析 → 生成催还记录 → 短信下发）
- POST /api/collections/preview/<id> 试生成催还短信（不落库、不发送）
- GET  /api/collections              查询历史催还记录
- POST /api/collections/<id>/resend  重发催还短信
- GET  /api/collections/status       LLM 与短信平台配置状态
"""
from __future__ import annotations

from flask import Blueprint

from config import config
from app.llm import llm_client
from app.services import collection_service as svc
from app.services.sms_gateway import sms_gateway
from app.utils import (arg, log_operation, login_required, ok, page_args, payload,
                       role_required, to_int)

bp = Blueprint("collections", __name__)


@bp.get("/status")
@login_required
def status():
    return ok({
        "llm": llm_client.status(),
        "sms": sms_gateway.status(),
        "overdue_months": config.OVERDUE_MONTHS,
        "level_rules": {
            "一级": f"逾期 ≤ {config.COLLECTION_LEVEL2_DAYS} 天",
            "二级": f"逾期 {config.COLLECTION_LEVEL2_DAYS} ~ {config.COLLECTION_LEVEL3_DAYS} 天",
            "三级": f"逾期 > {config.COLLECTION_LEVEL3_DAYS} 天",
        },
        "dedupe_days": config.COLLECTION_INTERVAL_DAYS,
    })


@bp.get("/overdue")
@login_required
def overdue():
    rows = svc.find_overdue({
        "keyword": arg("keyword", ""),
        "dept": arg("dept", ""),
        "level": arg("level", ""),
        "months": arg("months", ""),
    })
    amount = sum(float(r["unpaid_amount"]) for r in rows)
    level_stat = {"一级": 0, "二级": 0, "三级": 0}
    for row in rows:
        level_stat[row["collection_level"]] = level_stat.get(row["collection_level"], 0) + 1
    return ok({
        "total": len(rows),
        "amount": round(amount, 2),
        "level_stat": level_stat,
        "items": rows,
    })


@bp.post("/run")
@role_required("finance")
def run():
    data = payload()
    loan_ids = data.get("loan_ids") or []
    if isinstance(loan_ids, str):
        loan_ids = [x for x in loan_ids.split(",") if x.strip()]
    result = svc.run_batch({
        "loan_ids": [to_int(x) for x in loan_ids],
        "months": data.get("months"),
        "force": bool(data.get("force")),
        "channel": data.get("channel") or "短信",
        "dept": data.get("dept"),
        "level": data.get("level"),
    })
    log_operation("催还管理", "执行催还", result["batch_no"],
                  f"扫描 {result['scanned']} 笔，生成催还记录 {result['created']} 条，"
                  f"发送成功 {result['sent_ok']} 条，跳过 {result['skipped']} 条")
    message = (f"催还批处理完成：扫描 {result['scanned']} 笔，生成催还记录 {result['created']} 条，"
               f"短信发送成功 {result['sent_ok']} 条")
    if result["sent_fail"]:
        message += f"，未成功下发 {result['sent_fail']} 条（{result['sms_provider']['description']}）"
    return ok(result, message)


@bp.post("/preview/<int:loan_id>")
@login_required
def preview(loan_id: int):
    return ok(svc.preview(loan_id))


@bp.get("")
@login_required
def list_collections():
    page, size = page_args()
    return ok(svc.list_collections({
        "keyword": arg("keyword", ""),
        "level": arg("level", ""),
        "send_status": arg("send_status", ""),
        "batch_no": arg("batch_no", ""),
        "start_date": arg("start_date", ""),
        "end_date": arg("end_date", ""),
    }, page, size))


@bp.post("/<int:collection_id>/resend")
@role_required("finance")
def resend(collection_id: int):
    result = svc.resend(collection_id)
    log_operation("催还管理", "重发催还短信", str(collection_id),
                  f"发送状态：{result['send_status']}，{result['detail']}")
    return ok(result, f"重发结果：{result['send_status']}")


@bp.delete("/<int:collection_id>")
@role_required("finance")
def delete(collection_id: int):
    svc.delete_collection(collection_id)
    log_operation("催还管理", "删除催还记录", str(collection_id), "删除一条催还记录")
    return ok(None, "催还记录已删除")
