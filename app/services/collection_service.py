# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 催还业务服务（LLM 核心应用点）
=====================================================================
业务流程：
    1. 扫描借资台账，筛选“借资超过 N 个月（默认 3 个月）未还清”的记录；
    2. 对每笔逾期借资，调用 LLM 分析风险并生成催还短信文案
       （借资人、金额、借资日期、约定还款日、逾期天数、未还金额、还款指引）；
    3. 按逾期账龄自动分级（一级/二级/三级），写入催还记录表；
    4. 通过短信网关下发；未接入短信平台时，在催还记录中置
       send_status='无短信平台'、need_manual_send=1 作为标识，提示人工补发；
    5. LLM 不可用时自动降级为内置规则模板，保证系统始终可用。
"""
from __future__ import annotations

import random
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import config
from app import db
from app.llm import LLMUnavailable, llm_client
from app.services.loan_service import get_loan
from app.services.sms_gateway import sms_gateway
from app.utils import BizError, like, to_int

LEVEL_ORDER = ["一级", "二级", "三级"]


# ---------------------------------------------------------------------------
# 逾期识别
# ---------------------------------------------------------------------------
def level_of(overdue_days: int) -> str:
    """按逾期天数确定催还级别（业务规则确定，保证可解释、可审计）。"""
    if overdue_days > config.COLLECTION_LEVEL3_DAYS:
        return "三级"
    if overdue_days > config.COLLECTION_LEVEL2_DAYS:
        return "二级"
    return "一级"


def level_desc(level: str) -> str:
    return {
        "一级": "逾期提醒（逾期 3 个月以内，短信提醒 + 部门主管知会）",
        "二级": "正式催收（逾期 3-6 个月，短信催收 + 财务约谈）",
        "三级": "重点预警（逾期 6 个月以上，上报财务负责人并暂停新借资）",
    }.get(level, "逾期提醒")


def effective_deadline(loan_date: Any, repay_deadline: Any, months: Optional[int] = None):
    """
    计算催还判定基准日：取“约定还款日”与“借资日 + N 个月”中较早者。
    返回 (基准日 date, 逾期天数 int)。
    """
    months = config.OVERDUE_MONTHS if months is None else months
    loan_d = db.parse_date(loan_date) or db.today()
    rule_deadline = db.add_months(loan_d, months)
    agreed = db.parse_date(repay_deadline) or rule_deadline
    base = min(rule_deadline, agreed)
    return base, (db.today() - base).days


def find_overdue(args: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    查询逾期未还的借资记录。

    逾期口径（与业务制度一致）：约定还款日已过，或借资日至今已超过 N 个月（默认 3 个月）。
    这样既能对“提前到期”的借资及时催还，也能保证“约定被延后”的借资在超过 3 个月时
    仍会进入催还流程。
    """
    args = args or {}
    today_str = db.today().strftime("%Y-%m-%d")
    months = to_int(args.get("months") or config.OVERDUE_MONTHS, config.OVERDUE_MONTHS)
    cut_date = db.add_months(db.today(), -months).strftime("%Y-%m-%d")

    where = [
        "l.is_deleted = 0",
        "l.repaid_amount < l.amount",
        "l.status NOT IN ('已还清', '已核销')",
        "(l.repay_deadline < %s OR l.loan_date <= %s)",
    ]
    params: List[Any] = [today_str, cut_date]

    if args.get("sales_id"):
        where.append("l.sales_id = %s")
        params.append(to_int(args["sales_id"]))
    if args.get("dept"):
        where.append("s.dept = %s")
        params.append(args["dept"])
    keyword = (args.get("keyword") or "").strip()
    if keyword:
        where.append("(s.name LIKE %s OR s.emp_no LIKE %s OR l.loan_no LIKE %s)")
        params.extend([like(keyword)] * 3)

    rows = db.query_all(
        f"""SELECT l.id AS loan_id, l.loan_no, l.sales_id, l.amount, l.loan_date, l.repay_deadline,
                   l.loan_type, l.purpose, l.status, l.repaid_amount,
                   (l.amount - l.repaid_amount) AS unpaid_amount,
                   s.emp_no, s.name AS sales_name, s.phone, s.dept, s.region, s.status AS sales_status
              FROM loan_record l
              JOIN sales_person s ON s.id = l.sales_id
             WHERE {' AND '.join(where)}
             ORDER BY l.repay_deadline ASC, l.id ASC""",
        params,
    )

    result: List[Dict[str, Any]] = []
    for row in rows:
        base_deadline, days = effective_deadline(row["loan_date"], row["repay_deadline"], months)
        if days <= 0:
            continue
        row["overdue_days"] = days
        row["base_deadline"] = base_deadline.strftime("%Y-%m-%d")
        _loan_d = db.parse_date(row["loan_date"]) or db.today()
        _rule_deadline = db.add_months(_loan_d, months)
        _agreed = db.parse_date(row["repay_deadline"]) or _rule_deadline
        row["overdue_rule"] = (f"借资日 + {months} 个月 = {_rule_deadline.strftime('%Y-%m-%d')}，"
                               f"约定还款日 = {_agreed.strftime('%Y-%m-%d')}")
        row["collection_level"] = level_of(days)
        row["level_desc"] = level_desc(row["collection_level"])
        if args.get("level") and row["collection_level"] != args["level"]:
            continue
        row["last_collection"] = db.query_one(
            """SELECT id, collection_level, channel, send_status, created_at, sent_at
                 FROM collection_record WHERE loan_id = %s
                ORDER BY created_at DESC, id DESC LIMIT 1""",
            (row["loan_id"],),
        )
        result.append(row)
    return result


# ---------------------------------------------------------------------------
# 催还文案生成
# ---------------------------------------------------------------------------
def build_fallback_text(loan: Dict[str, Any], level: str) -> Dict[str, str]:
    """内置规则模板（LLM 不可用时的降级方案）。"""
    name = loan.get("sales_name") or "同事"
    amount = float(loan.get("amount") or 0)
    unpaid = float(loan.get("unpaid_amount") or 0)
    days = int(loan.get("overdue_days") or 0)
    deadline = str(loan.get("repay_deadline") or "")[:10]
    loan_date = str(loan.get("loan_date") or "")[:10]

    prefix = {
        "一级": "【还款提醒】",
        "二级": "【催还通知】",
        "三级": "【重点催收】",
    }.get(level, "【还款提醒】")
    tail = {
        "一级": "请及时办理还款，谢谢配合。",
        "二级": "请于 3 个工作日内到财务部办理还款，逾期将影响后续借资额度。",
        "三级": "该笔借资逾期时间较长，请立即联系财务部处理，否则将上报公司并按制度从薪资中扣回。",
    }.get(level, "请及时办理还款。")

    content = (
        f"{prefix}{name}您好，您于{loan_date}借资{amount:.2f}元，"
        f"约定还款日为{deadline}，现已逾期{days}天，尚未归还{unpaid:.2f}元。"
        f"{tail}如有疑问请联系财务部。"
    )
    analysis = (
        f"该笔借资（{loan.get('loan_no')}）已于约定还款日 {deadline} 到期，"
        f"逾期 {days} 天，属{level}逾期，未还金额 {unpaid:.2f} 元。"
    )
    suggestion = {
        "一级": "短信提醒并同步部门主管。",
        "二级": "短信催收 + 财务约谈，暂停新增借资。",
        "三级": "上报财务负责人，按制度停发借资并从薪资分月扣回。",
    }.get(level, "短信提醒。")
    return {"content": content, "analysis": analysis, "suggestion": suggestion,
            "generated_by": "规则模板", "model": ""}


COLLECTION_SYSTEM_PROMPT = """你是企业财务部门的应收账款催收专员，熟悉公司销售人员财务借资（差旅借款、市场推广借款、备用金等）的催还业务。
请针对给定的单笔逾期借资信息，完成两件事：
1) 分析该笔借资的逾期风险；
2) 生成一条可直接下发给借款人手机的中文催还短信。

写作要求：
- 语气专业、礼貌但明确，体现公司制度约束力，不使用侮辱性或威胁性表述；
- 短信必须包含：借款人姓名、借资金额、借资日期、约定还款日、逾期天数、尚未归还金额、还款方式指引与财务部联系方式；
- 短信总字数控制在 160 字以内，以“【财务部】”结尾；
- 催还级别由系统按逾期天数给定，你必须遵循该级别对应的语气强度。

严格按照以下 JSON 格式输出，不要输出任何多余内容：
{"analysis": "风险分析，80字以内", "sms_content": "催还短信内容", "suggestion": "后续处理建议，50字以内"}"""


def generate_collection_content(loan: Dict[str, Any], level: str) -> Dict[str, Any]:
    """调用 LLM 生成催还内容；失败时降级为规则模板。"""
    fallback = build_fallback_text(loan, level)
    if not llm_client.enabled:
        fallback["notice"] = "未配置 LLM_API_KEY，已使用内置规则模板生成催还短信"
        return fallback

    user_prompt = (
        f"借款人：{loan.get('sales_name')}（工号 {loan.get('emp_no')}，{loan.get('dept')}）\n"
        f"借资单号：{loan.get('loan_no')}\n"
        f"借资类型：{loan.get('loan_type')}\n"
        f"借资用途：{loan.get('purpose') or '未填写'}\n"
        f"借资金额：{float(loan.get('amount') or 0):.2f} 元\n"
        f"已还金额：{float(loan.get('repaid_amount') or 0):.2f} 元\n"
        f"未还金额：{float(loan.get('unpaid_amount') or 0):.2f} 元\n"
        f"借资日期：{str(loan.get('loan_date'))[:10]}\n"
        f"约定还款日：{str(loan.get('repay_deadline'))[:10]}\n"
        f"逾期天数：{loan.get('overdue_days')} 天\n"
        f"系统判定的催还级别：{level}（{level_desc(level)}）\n"
        f"借款人电话：{loan.get('phone')}\n"
        f"财务部联系方式：财务部 020-88886666 转 601"
    )

    try:
        data = llm_client.chat_json(
            [
                {"role": "system", "content": COLLECTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
        )
    except LLMUnavailable as exc:
        fallback["notice"] = f"大模型调用失败（{exc}），已降级为内置规则模板"
        return fallback

    content = str(data.get("sms_content") or data.get("content") or "").strip()
    if len(content) < 20:
        fallback["notice"] = "大模型返回内容过短，已降级为内置规则模板"
        return fallback
    if len(content) > 400:
        content = content[:400]
    return {
        "content": content,
        "analysis": str(data.get("analysis") or "").strip() or fallback["analysis"],
        "suggestion": str(data.get("suggestion") or "").strip() or fallback["suggestion"],
        "generated_by": "LLM",
        "model": llm_client.model,
        "notice": "",
    }


# ---------------------------------------------------------------------------
# 催还记录生成与下发
# ---------------------------------------------------------------------------
def gen_batch_no() -> str:
    return f"CH{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(10, 99)}"


def _recent_exists(loan_id: int, level: str) -> bool:
    row = db.query_one(
        """SELECT created_at FROM collection_record
            WHERE loan_id = %s AND collection_level = %s
            ORDER BY created_at DESC, id DESC LIMIT 1""",
        (loan_id, level),
    )
    if not row or not row.get("created_at"):
        return False
    last = db.parse_date(row["created_at"])
    if not last:
        return False
    return (db.today() - last).days < config.COLLECTION_INTERVAL_DAYS


def run_batch(args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    执行一次催还批处理：扫描 → LLM 生成 → 落库 → 短信下发。
    args:
        loan_ids   : 指定借资记录（手工催还时使用）
        months     : 逾期阈值月数
        force      : 忽略重复催还间隔，强制再次生成
        channel    : 短信 / 站内信
    """
    args = args or {}
    channel = args.get("channel") or "短信"
    force = bool(args.get("force"))
    batch_no = gen_batch_no()

    if args.get("loan_ids"):
        targets = []
        for loan_id in args["loan_ids"]:
            loan = get_loan(to_int(loan_id))
            if loan["status"] in ("已还清", "已核销") or float(loan["unpaid_amount"]) <= 0:
                continue
            base_deadline, days = effective_deadline(
                loan["loan_date"], loan["repay_deadline"], args.get("months"))
            loan["loan_id"] = loan["id"]
            loan["overdue_days"] = max(days, 0)
            loan["base_deadline"] = base_deadline.strftime("%Y-%m-%d")
            loan["collection_level"] = level_of(max(days, 0))
            loan["level_desc"] = level_desc(loan["collection_level"])
            targets.append(loan)
        scanned = len(args["loan_ids"])
    else:
        targets = find_overdue(args)
        scanned = len(targets)

    created: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    sent_ok = sent_fail = 0

    for loan in targets:
        level = loan["collection_level"]
        if not force and _recent_exists(loan["loan_id"], level):
            skipped.append({
                "loan_id": loan["loan_id"],
                "loan_no": loan["loan_no"],
                "sales_name": loan.get("sales_name"),
                "reason": f"{config.COLLECTION_INTERVAL_DAYS} 天内已生成过{level}催还记录，自动跳过（可勾选强制催还）",
            })
            continue

        result = generate_collection_content(loan, level)
        send = sms_gateway.send(loan.get("phone") or "", result["content"]) if channel == "短信" \
            else {"success": False, "send_status": "待发送", "detail": "站内信渠道，请人工确认"}

        now = _now()
        record_id = db.execute(
            """INSERT INTO collection_record
               (batch_no, loan_id, sales_id, overdue_days, overdue_amount, collection_level,
                channel, content, llm_model, generated_by, send_status, need_manual_send,
                sent_at, remark, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                batch_no, loan["loan_id"], loan["sales_id"], loan["overdue_days"],
                float(loan["unpaid_amount"]), level, channel, result["content"],
                result.get("model") or "", result["generated_by"], send["send_status"],
                0 if send["success"] else 1,
                now if send["success"] else None,
                f"风险分析：{result['analysis']}｜处理建议：{result['suggestion']}"
                + (f"｜{result['notice']}" if result.get("notice") else ""),
                now,
            ),
        )
        if send["success"]:
            sent_ok += 1
        else:
            sent_fail += 1

        created.append({
            "id": record_id,
            "loan_id": loan["loan_id"],
            "loan_no": loan["loan_no"],
            "sales_name": loan.get("sales_name"),
            "phone": loan.get("phone"),
            "overdue_days": loan["overdue_days"],
            "overdue_amount": float(loan["unpaid_amount"]),
            "collection_level": level,
            "content": result["content"],
            "analysis": result["analysis"],
            "suggestion": result["suggestion"],
            "generated_by": result["generated_by"],
            "llm_model": result.get("model") or "",
            "send_status": send["send_status"],
            "send_detail": send["detail"],
            "need_manual_send": 0 if send["success"] else 1,
        })

    return {
        "batch_no": batch_no,
        "scanned": scanned,
        "created": len(created),
        "skipped": len(skipped),
        "sent_ok": sent_ok,
        "sent_fail": sent_fail,
        "sms_provider": sms_gateway.status(),
        "llm": llm_client.status(),
        "items": created,
        "skipped_items": skipped,
    }


def preview(loan_id: int) -> Dict[str, Any]:
    """试生成催还文案（不落库、不发送），用于人工审核。"""
    loan = get_loan(loan_id)
    base_deadline, days = effective_deadline(loan["loan_date"], loan["repay_deadline"])
    if loan["status"] in ("已还清", "已核销") or float(loan["unpaid_amount"]) <= 0:
        raise BizError("该笔借资已还清或已核销，无需催还")
    loan["loan_id"] = loan["id"]
    loan["overdue_days"] = max(days, 0)
    loan["base_deadline"] = base_deadline.strftime("%Y-%m-%d")
    level = level_of(max(days, 0))
    loan["collection_level"] = level
    loan["level_desc"] = level_desc(level)
    result = generate_collection_content(loan, level)
    return {"loan": loan, "level": level, "level_desc": level_desc(level), **result}


# ---------------------------------------------------------------------------
# 催还记录查询 / 重发
# ---------------------------------------------------------------------------
def list_collections(args: Dict[str, Any], page: int = 1, size: int = 10) -> Dict[str, Any]:
    where: List[str] = ["1 = 1"]
    params: List[Any] = []

    keyword = (args.get("keyword") or "").strip()
    if keyword:
        where.append("(s.name LIKE %s OR s.emp_no LIKE %s OR l.loan_no LIKE %s OR c.batch_no LIKE %s)")
        params.extend([like(keyword)] * 4)
    if args.get("level"):
        where.append("c.collection_level = %s")
        params.append(args["level"])
    if args.get("send_status"):
        where.append("c.send_status = %s")
        params.append(args["send_status"])
    if args.get("batch_no"):
        where.append("c.batch_no = %s")
        params.append(args["batch_no"])
    if args.get("start_date"):
        where.append("c.created_at >= %s")
        params.append(str(args["start_date"]) + " 00:00:00")
    if args.get("end_date"):
        where.append("c.created_at <= %s")
        params.append(str(args["end_date"]) + " 23:59:59")

    where_sql = " WHERE " + " AND ".join(where)
    total = db.query_scalar(
        f"""SELECT COUNT(*) AS c FROM collection_record c
              JOIN loan_record l ON l.id = c.loan_id
              JOIN sales_person s ON s.id = c.sales_id {where_sql}""",
        params, 0)

    rows = db.query_all(
        f"""SELECT c.id, c.batch_no, c.loan_id, c.sales_id, c.overdue_days, c.overdue_amount,
                   c.collection_level, c.channel, c.content, c.llm_model, c.generated_by,
                   c.send_status, c.need_manual_send, c.sent_at, c.remark, c.created_at,
                   l.loan_no, l.amount, l.loan_date, l.repay_deadline,
                   s.emp_no, s.name AS sales_name, s.phone, s.dept
              FROM collection_record c
              JOIN loan_record l ON l.id = c.loan_id
              JOIN sales_person s ON s.id = c.sales_id
              {where_sql}
             ORDER BY c.created_at DESC, c.id DESC
             LIMIT %s OFFSET %s""",
        params + [size, (page - 1) * size],
    )

    stat = db.query_one(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN send_status = '已发送' THEN 1 ELSE 0 END) AS sent,
                  SUM(CASE WHEN send_status <> '已发送' THEN 1 ELSE 0 END) AS unsent,
                  IFNULL(SUM(overdue_amount), 0) AS amount
             FROM collection_record"""
    ) or {}

    return {
        "total": int(total or 0),
        "page": page,
        "size": size,
        "pages": max(1, (int(total or 0) + size - 1) // size),
        "stat": stat,
        "items": rows,
    }


def resend(collection_id: int) -> Dict[str, Any]:
    """对未成功下发的催还记录执行重发。"""
    record = db.query_one(
        """SELECT c.*, s.phone, s.name AS sales_name FROM collection_record c
             JOIN sales_person s ON s.id = c.sales_id WHERE c.id = %s""",
        (collection_id,),
    )
    if not record:
        raise BizError("催还记录不存在")
    if not record.get("phone"):
        raise BizError("该借款人未登记手机号，无法重发")
    send = sms_gateway.send(record["phone"], record.get("content") or "")
    db.affected(
        "UPDATE collection_record SET send_status = %s, need_manual_send = %s, sent_at = %s,"
        " remark = %s WHERE id = %s",
        (send["send_status"], 0 if send["success"] else 1,
         _now() if send["success"] else None,
         f"{record.get('remark') or ''}｜重发：{send['detail']}"[:500], collection_id),
    )
    return {"id": collection_id, "send_status": send["send_status"], "detail": send["detail"]}


def delete_collection(collection_id: int) -> None:
    db.affected("DELETE FROM collection_record WHERE id = %s", (collection_id,))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
