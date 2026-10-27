# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 借资业务服务
=====================================================================
负责：借资信息增删改查、还款登记、借资统计（总览/部门/类型/趋势/账龄/排名）。
所有 SQL 均为参数化查询，日期运算统一在 Python 侧完成以保证跨库兼容。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from config import config
from app import db
from app.utils import BizError, like, require, to_float, to_int

# ---------------------------------------------------------------------------
# 借资单据基础查询
# ---------------------------------------------------------------------------
LOAN_FIELDS = """
       l.id, l.loan_no, l.sales_id, l.amount, l.loan_date, l.repay_deadline,
       l.loan_type, l.purpose, l.status, l.repaid_amount,
       (l.amount - l.repaid_amount) AS unpaid_amount,
       l.remark, l.created_by, l.created_at, l.updated_at,
       s.emp_no, s.name AS sales_name, s.phone, s.dept, s.region, s.status AS sales_status
"""

LOAN_FROM = """
    FROM loan_record l
    JOIN sales_person s ON s.id = l.sales_id
"""

LOAN_TYPES = ["差旅借款", "市场推广借款", "备用金", "项目周转借款", "客户招待借款", "其他"]
LOAN_STATUS = ["待还款", "部分还款", "已还清", "已核销"]


def build_filters(args: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """根据查询条件拼装 WHERE 子句（全部使用参数占位）。"""
    where: List[str] = ["l.is_deleted = 0"]
    params: List[Any] = []

    keyword = (args.get("keyword") or "").strip()
    if keyword:
        where.append("(l.loan_no LIKE %s OR s.name LIKE %s OR s.emp_no LIKE %s OR l.purpose LIKE %s)")
        params.extend([like(keyword)] * 4)

    if args.get("dept"):
        where.append("s.dept = %s")
        params.append(args["dept"])

    if args.get("sales_id"):
        where.append("l.sales_id = %s")
        params.append(to_int(args["sales_id"]))

    if args.get("loan_type"):
        where.append("l.loan_type = %s")
        params.append(args["loan_type"])

    if args.get("status"):
        where.append("l.status = %s")
        params.append(args["status"])

    # 未结清（尚未还完，含正常未到期与已逾期）
    if str(args.get("unsettled", "")).lower() in ("1", "true", "yes"):
        where.append("l.repaid_amount < l.amount AND l.status NOT IN ('已还清', '已核销')")

    if args.get("start_date"):
        where.append("l.loan_date >= %s")
        params.append(str(args["start_date"]))

    if args.get("end_date"):
        where.append("l.loan_date <= %s")
        params.append(str(args["end_date"]))

    if args.get("min_amount") not in (None, ""):
        where.append("l.amount >= %s")
        params.append(to_float(args["min_amount"]))

    if args.get("max_amount") not in (None, ""):
        where.append("l.amount <= %s")
        params.append(to_float(args["max_amount"]))

    # 逾期筛选：约定还款日已过，或借资日至今已超过 N 个月（默认 3 个月），且尚未还清
    if str(args.get("overdue_only", "")).lower() in ("1", "true", "yes"):
        where.append("(l.repay_deadline < %s OR l.loan_date <= %s) AND l.repaid_amount < l.amount"
                     " AND l.status NOT IN ('已还清', '已核销')")
        params.append(db.today().strftime("%Y-%m-%d"))
        params.append(db.add_months(db.today(), -config.OVERDUE_MONTHS).strftime("%Y-%m-%d"))

    return " WHERE " + " AND ".join(where), params


def decorate(row: Dict[str, Any]) -> Dict[str, Any]:
    """补充逾期天数、逾期标识等派生字段（逾期口径：约定还款日与借资日+3个月取较早者）。"""
    if not row:
        return row
    loan_d = db.parse_date(row.get("loan_date")) or db.today()
    rule_deadline = db.add_months(loan_d, config.OVERDUE_MONTHS)
    agreed = db.parse_date(row.get("repay_deadline")) or rule_deadline
    base_deadline = min(rule_deadline, agreed)
    days = (db.today() - base_deadline).days
    unpaid = float(row.get("unpaid_amount") or 0)
    finished = row.get("status") in ("已还清", "已核销")
    row["base_deadline"] = base_deadline.strftime("%Y-%m-%d")
    row["overdue_days"] = days if days > 0 else 0
    row["is_overdue"] = bool(days > 0 and unpaid > 0 and not finished)
    row["progress"] = round(float(row.get("repaid_amount") or 0) / float(row["amount"]) * 100, 1) \
        if float(row.get("amount") or 0) else 0.0
    return row


# ---------------------------------------------------------------------------
# 借资信息查询
# ---------------------------------------------------------------------------
def list_loans(args: Dict[str, Any], page: int = 1, size: int = 10) -> Dict[str, Any]:
    where_sql, params = build_filters(args)

    total = db.query_scalar(f"SELECT COUNT(*) AS c {LOAN_FROM} {where_sql}", params, 0)

    summary = db.query_one(
        f"""SELECT IFNULL(SUM(l.amount), 0)          AS total_amount,
                   IFNULL(SUM(l.repaid_amount), 0)   AS repaid_amount,
                   IFNULL(SUM(l.amount - l.repaid_amount), 0) AS unpaid_amount
            {LOAN_FROM} {where_sql}""",
        params,
    ) or {"total_amount": 0, "repaid_amount": 0, "unpaid_amount": 0}

    rows = db.query_all(
        f"""SELECT {LOAN_FIELDS} {LOAN_FROM} {where_sql}
            ORDER BY l.loan_date DESC, l.id DESC
            LIMIT %s OFFSET %s""",
        params + [size, (page - 1) * size],
    )
    items = [decorate(r) for r in rows]
    return {
        "total": int(total or 0),
        "page": page,
        "size": size,
        "pages": max(1, (int(total or 0) + size - 1) // size),
        "summary": summary,
        "items": items,
    }


def get_loan(loan_id: int) -> Dict[str, Any]:
    row = db.query_one(f"SELECT {LOAN_FIELDS} {LOAN_FROM} WHERE l.id = %s", (loan_id,))
    if not row:
        raise BizError("借资记录不存在或已被删除")
    return decorate(row)


def get_repayments(loan_id: int) -> List[Dict[str, Any]]:
    return db.query_all(
        "SELECT id, loan_id, repay_amount, repay_date, repay_method, operator, remark, created_at"
        " FROM repayment_record WHERE loan_id = %s ORDER BY repay_date DESC, id DESC",
        (loan_id,),
    )


# ---------------------------------------------------------------------------
# 借资信息维护
# ---------------------------------------------------------------------------
def generate_loan_no(prefix: str = "JZ") -> str:
    today_str = db.today().strftime("%Y%m%d")
    count = db.query_scalar(
        "SELECT COUNT(*) AS c FROM loan_record WHERE loan_no LIKE %s",
        (f"{prefix}{today_str}%",),
        0,
    )
    return f"{prefix}{today_str}{int(count or 0) + 1:04d}"


def create_loan(data: Dict[str, Any], operator: str = "") -> Dict[str, Any]:
    require(data, "sales_id", "amount", "loan_date")

    sales = db.query_one("SELECT id, name, dept FROM sales_person WHERE id = %s",
                         (to_int(data["sales_id"]),))
    if not sales:
        raise BizError("所选销售人员不存在")

    amount = to_float(data["amount"])
    if amount <= 0:
        raise BizError("借资金额必须大于 0")

    loan_date = db.parse_date(data["loan_date"])
    if not loan_date:
        raise BizError("借资日期格式不正确，应为 YYYY-MM-DD")
    if loan_date > db.today():
        raise BizError("借资日期不能晚于今天")

    deadline = db.parse_date(data.get("repay_deadline")) or db.add_months(loan_date, 3)
    if deadline < loan_date:
        raise BizError("约定还款日不能早于借资日期")

    loan_type = data.get("loan_type") or "差旅借款"
    if loan_type not in LOAN_TYPES:
        loan_type = "其他"

    loan_no = (data.get("loan_no") or "").strip() or generate_loan_no()
    exists = db.query_scalar("SELECT COUNT(*) AS c FROM loan_record WHERE loan_no = %s", (loan_no,), 0)
    if int(exists or 0) > 0:
        raise BizError(f"借资单号 {loan_no} 已存在")

    loan_id = db.execute(
        """INSERT INTO loan_record
           (loan_no, sales_id, amount, loan_date, repay_deadline, loan_type, purpose,
            status, repaid_amount, remark, created_by, is_deleted, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, '待还款', 0, %s, %s, 0, %s, %s)""",
        (
            loan_no, sales["id"], amount, loan_date.strftime("%Y-%m-%d"),
            deadline.strftime("%Y-%m-%d"), loan_type, (data.get("purpose") or "").strip(),
            (data.get("remark") or "").strip(), operator or "system",
            _now(), _now(),
        ),
    )
    return get_loan(loan_id)


def update_loan(loan_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    loan = get_loan(loan_id)

    sales_id = to_int(data.get("sales_id") or loan["sales_id"])
    amount = to_float(data.get("amount", loan["amount"]))
    if amount <= 0:
        raise BizError("借资金额必须大于 0")

    loan_date = db.parse_date(data.get("loan_date")) or db.parse_date(loan["loan_date"])
    deadline = db.parse_date(data.get("repay_deadline")) or db.parse_date(loan["repay_deadline"])
    if not loan_date or not deadline:
        raise BizError("日期格式不正确，应为 YYYY-MM-DD")
    if deadline < loan_date:
        raise BizError("约定还款日不能早于借资日期")
    if amount < float(loan["repaid_amount"] or 0):
        raise BizError(f"借资金额不能小于已还金额 {loan['repaid_amount']} 元")

    status = data.get("status") or loan["status"]
    if status == "已核销":
        # 核销需将剩余金额一次性核销
        db.execute("UPDATE loan_record SET repaid_amount = %s WHERE id = %s", (amount, loan_id))
    elif status in ("待还款", "部分还款", "已还清"):
        repaid = float(loan["repaid_amount"] or 0)
        if repaid <= 0:
            status = "待还款"
        elif repaid < amount:
            status = "部分还款"
        else:
            status = "已还清"

    db.execute(
        """UPDATE loan_record
              SET sales_id = %s, amount = %s, loan_date = %s, repay_deadline = %s,
                  loan_type = %s, purpose = %s, status = %s, remark = %s, updated_at = %s
            WHERE id = %s""",
        (
            sales_id, amount, loan_date.strftime("%Y-%m-%d"), deadline.strftime("%Y-%m-%d"),
            data.get("loan_type") or loan["loan_type"], data.get("purpose", loan.get("purpose") or ""),
            status, data.get("remark", loan.get("remark") or ""), _now(), loan_id,
        ),
    )
    return get_loan(loan_id)


def delete_loan(loan_id: int) -> None:
    get_loan(loan_id)
    db.affected("UPDATE loan_record SET is_deleted = 1, updated_at = %s WHERE id = %s",
                (_now(), loan_id))


# ---------------------------------------------------------------------------
# 还款登记
# ---------------------------------------------------------------------------
def sync_loan_status(loan_id: int) -> None:
    """依据还款流水重算已还金额与状态（幂等，与数据库触发器结果一致）。"""
    loan = db.query_one("SELECT id, amount, status FROM loan_record WHERE id = %s", (loan_id,))
    if not loan:
        return
    repaid = float(db.query_scalar(
        "SELECT IFNULL(SUM(repay_amount), 0) AS s FROM repayment_record WHERE loan_id = %s",
        (loan_id,), 0) or 0)
    amount = float(loan["amount"])
    if loan["status"] == "已核销":
        status = "已核销"
        repaid = amount
    elif repaid <= 0:
        status = "待还款"
    elif repaid < amount:
        status = "部分还款"
    else:
        status = "已还清"
    db.affected(
        "UPDATE loan_record SET repaid_amount = %s, status = %s, updated_at = %s WHERE id = %s",
        (repaid, status, _now(), loan_id),
    )


def add_repayment(loan_id: int, data: Dict[str, Any], operator: str = "") -> Dict[str, Any]:
    loan = get_loan(loan_id)
    if loan["status"] == "已核销":
        raise BizError("该笔借资已核销，不能再登记还款")

    amount = to_float(data.get("repay_amount"))
    if amount <= 0:
        raise BizError("还款金额必须大于 0")

    unpaid = float(loan["unpaid_amount"] or 0)
    if unpaid <= 0:
        raise BizError("该笔借资已还清，无需再登记还款")
    if amount > unpaid + 0.001:
        raise BizError(f"还款金额超过未还余额（{unpaid:.2f} 元），请重新填写")

    repay_date = db.parse_date(data.get("repay_date")) or db.today()

    db.execute(
        """INSERT INTO repayment_record
           (loan_id, repay_amount, repay_date, repay_method, operator, remark, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (
            loan_id, amount, repay_date.strftime("%Y-%m-%d"),
            data.get("repay_method") or "银行转账", operator or "system",
            (data.get("remark") or "").strip(), _now(),
        ),
    )
    sync_loan_status(loan_id)
    return get_loan(loan_id)


def delete_repayment(repayment_id: int) -> Dict[str, Any]:
    row = db.query_one("SELECT id, loan_id FROM repayment_record WHERE id = %s", (repayment_id,))
    if not row:
        raise BizError("还款记录不存在")
    db.affected("DELETE FROM repayment_record WHERE id = %s", (repayment_id,))
    sync_loan_status(row["loan_id"])
    return get_loan(row["loan_id"])


# ---------------------------------------------------------------------------
# 统计口径
# ---------------------------------------------------------------------------
def overview() -> Dict[str, Any]:
    """借资总览：金额、笔数、人数、逾期情况。"""
    today_str = db.today().strftime("%Y-%m-%d")
    base = db.query_one(
        """SELECT COUNT(*) AS loan_count,
                  IFNULL(SUM(amount), 0)          AS total_amount,
                  IFNULL(SUM(repaid_amount), 0)   AS repaid_amount,
                  IFNULL(SUM(amount - repaid_amount), 0) AS unpaid_amount
             FROM loan_record WHERE is_deleted = 0"""
    ) or {}

    overdue = db.query_one(
        """SELECT COUNT(*) AS overdue_count,
                  IFNULL(SUM(amount - repaid_amount), 0) AS overdue_amount,
                  COUNT(DISTINCT sales_id) AS overdue_person
             FROM loan_record
            WHERE is_deleted = 0
              AND repaid_amount < amount
              AND status NOT IN ('已还清', '已核销')
              AND repay_deadline < %s""",
        (today_str,),
    ) or {}

    counts = db.query_one(
        """SELECT (SELECT COUNT(*) FROM sales_person WHERE status = '在职') AS sales_active,
                  (SELECT COUNT(*) FROM sales_person) AS sales_total,
                  (SELECT COUNT(*) FROM collection_record) AS collection_total,
                  (SELECT COUNT(DISTINCT sales_id) FROM loan_record
                    WHERE is_deleted = 0 AND repaid_amount < amount) AS debtor_count"""
    ) or {}

    return {
        "loan_count": int(base.get("loan_count") or 0),
        "total_amount": round(float(base.get("total_amount") or 0), 2),
        "repaid_amount": round(float(base.get("repaid_amount") or 0), 2),
        "unpaid_amount": round(float(base.get("unpaid_amount") or 0), 2),
        "overdue_count": int(overdue.get("overdue_count") or 0),
        "overdue_amount": round(float(overdue.get("overdue_amount") or 0), 2),
        "overdue_person": int(overdue.get("overdue_person") or 0),
        "debtor_count": int(counts.get("debtor_count") or 0),
        "sales_active": int(counts.get("sales_active") or 0),
        "sales_total": int(counts.get("sales_total") or 0),
        "collection_total": int(counts.get("collection_total") or 0),
        "collection_rate": round(float(base.get("repaid_amount") or 0) /
                                 float(base.get("total_amount") or 1) * 100, 1),
    }


def by_dept() -> List[Dict[str, Any]]:
    return db.query_all(
        """SELECT s.dept AS name,
                  COUNT(l.id) AS loan_count,
                  IFNULL(SUM(l.amount), 0) AS total_amount,
                  IFNULL(SUM(l.repaid_amount), 0) AS repaid_amount,
                  IFNULL(SUM(l.amount - l.repaid_amount), 0) AS unpaid_amount
             FROM loan_record l JOIN sales_person s ON s.id = l.sales_id
            WHERE l.is_deleted = 0
            GROUP BY s.dept
            ORDER BY total_amount DESC"""
    )


def by_type() -> List[Dict[str, Any]]:
    return db.query_all(
        """SELECT loan_type AS name,
                  COUNT(*) AS loan_count,
                  IFNULL(SUM(amount), 0) AS total_amount,
                  IFNULL(SUM(amount - repaid_amount), 0) AS unpaid_amount
             FROM loan_record WHERE is_deleted = 0
            GROUP BY loan_type ORDER BY total_amount DESC"""
    )


def by_month(months: int = 6) -> List[Dict[str, Any]]:
    """近 N 个月借资金额趋势（按自然月聚合，Python 侧完成分组）。"""
    start = db.add_months(db.today().replace(day=1), -(months - 1))
    rows = db.query_all(
        """SELECT loan_date, amount, repaid_amount FROM loan_record
            WHERE is_deleted = 0 AND loan_date >= %s""",
        (start.strftime("%Y-%m-%d"),),
    )
    buckets: Dict[str, Dict[str, Any]] = {}
    cursor = start
    for _ in range(months):
        key = cursor.strftime("%Y-%m")
        buckets[key] = {"name": key, "loan_count": 0, "total_amount": 0.0, "unpaid_amount": 0.0}
        cursor = db.add_months(cursor, 1)

    for row in rows:
        key = str(row["loan_date"])[:7]
        if key in buckets:
            buckets[key]["loan_count"] += 1
            buckets[key]["total_amount"] += float(row["amount"] or 0)
            buckets[key]["unpaid_amount"] += float(row["amount"] or 0) - float(row["repaid_amount"] or 0)
    return list(buckets.values())


def overdue_aging() -> List[Dict[str, Any]]:
    """逾期账龄分布（按约定还款日区间聚合）。"""
    today = db.today()
    points = {
        "未逾期": (db.add_months(today, 0).strftime("%Y-%m-%d"), None),
        "逾期1个月内": (db.add_months(today, -1).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")),
        "逾期1-3个月": (db.add_months(today, -3).strftime("%Y-%m-%d"), db.add_months(today, -1).strftime("%Y-%m-%d")),
        "逾期3-6个月": (db.add_months(today, -6).strftime("%Y-%m-%d"), db.add_months(today, -3).strftime("%Y-%m-%d")),
        "逾期6个月以上": (None, db.add_months(today, -6).strftime("%Y-%m-%d")),
    }
    result: List[Dict[str, Any]] = []
    for label, (start, end) in points.items():
        conditions = ["is_deleted = 0", "amount > repaid_amount"]
        params: List[Any] = []
        if start:
            conditions.append("repay_deadline >= %s")
            params.append(start)
        if end:
            conditions.append("repay_deadline < %s")
            params.append(end)
        row = db.query_one(
            f"""SELECT COUNT(*) AS loan_count, IFNULL(SUM(amount - repaid_amount), 0) AS unpaid_amount
                  FROM loan_record WHERE {' AND '.join(conditions)}""",
            params or None,
        ) or {}
        result.append({
            "name": label,
            "loan_count": int(row.get("loan_count") or 0),
            "unpaid_amount": round(float(row.get("unpaid_amount") or 0), 2),
        })
    return result


def top_debtors(limit: int = 10) -> List[Dict[str, Any]]:
    return db.query_all(
        """SELECT s.id, s.emp_no, s.name, s.dept, s.phone,
                  COUNT(l.id) AS loan_count,
                  IFNULL(SUM(l.amount), 0) AS total_amount,
                  IFNULL(SUM(l.amount - l.repaid_amount), 0) AS unpaid_amount
             FROM loan_record l JOIN sales_person s ON s.id = l.sales_id
            WHERE l.is_deleted = 0 AND l.amount > l.repaid_amount
            GROUP BY s.id, s.emp_no, s.name, s.dept, s.phone
            ORDER BY unpaid_amount DESC
            LIMIT %s""",
        (limit,),
    )


def search_sales(keyword: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    if keyword:
        return db.query_all(
            """SELECT id, emp_no, name, phone, dept, region, status FROM sales_person
                WHERE name LIKE %s OR emp_no LIKE %s OR phone LIKE %s
                ORDER BY name LIMIT %s""",
            (like(keyword), like(keyword), like(keyword), limit),
        )
    return db.query_all(
        "SELECT id, emp_no, name, phone, dept, region, status FROM sales_person"
        " ORDER BY id LIMIT %s", (limit,))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
