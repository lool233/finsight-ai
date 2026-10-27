# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 销售人员服务
=====================================================================
销售人员是借资主体，其手机号是催还短信的接收号码。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from app import db
from app.utils import BizError, like, require

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def build_filters(args: Dict[str, Any]):
    where: List[str] = ["1 = 1"]
    params: List[Any] = []

    keyword = (args.get("keyword") or "").strip()
    if keyword:
        where.append("(name LIKE %s OR emp_no LIKE %s OR phone LIKE %s OR region LIKE %s)")
        params.extend([like(keyword)] * 4)
    if args.get("dept"):
        where.append("dept = %s")
        params.append(args["dept"])
    if args.get("status"):
        where.append("status = %s")
        params.append(args["status"])
    return " WHERE " + " AND ".join(where), params


def list_sales(args: Dict[str, Any], page: int = 1, size: int = 10) -> Dict[str, Any]:
    where_sql, params = build_filters(args)
    total = db.query_scalar(f"SELECT COUNT(*) AS c FROM sales_person {where_sql}", params, 0)

    rows = db.query_all(
        f"""SELECT sp.id, sp.emp_no, sp.name, sp.gender, sp.phone, sp.dept, sp.region,
                   sp.job_title, sp.entry_date, sp.status, sp.remark, sp.created_at, sp.updated_at,
                   (SELECT COUNT(*) FROM loan_record l
                     WHERE l.sales_id = sp.id AND l.is_deleted = 0) AS loan_count,
                   (SELECT IFNULL(SUM(l.amount - l.repaid_amount), 0) FROM loan_record l
                     WHERE l.sales_id = sp.id AND l.is_deleted = 0) AS unpaid_amount,
                   (SELECT COUNT(*) FROM loan_record l
                     WHERE l.sales_id = sp.id AND l.is_deleted = 0 AND l.repaid_amount < l.amount
                       AND l.status NOT IN ('已还清','已核销') AND l.repay_deadline < %s) AS overdue_count
              FROM sales_person sp {where_sql}
             ORDER BY unpaid_amount DESC, sp.id ASC
             LIMIT %s OFFSET %s""",
        [db.today().strftime("%Y-%m-%d")] + params + [size, (page - 1) * size],
    )
    return {
        "total": int(total or 0),
        "page": page,
        "size": size,
        "pages": max(1, (int(total or 0) + size - 1) // size),
        "items": rows,
    }


def get_sales(sales_id: int) -> Dict[str, Any]:
    row = db.query_one("SELECT * FROM sales_person WHERE id = %s", (sales_id,))
    if not row:
        raise BizError("销售人员不存在")
    return row


def _validate(data: Dict[str, Any], sales_id: Optional[int] = None) -> Dict[str, Any]:
    require(data, "emp_no", "name", "phone", "dept")
    data = dict(data)
    data["emp_no"] = str(data["emp_no"]).strip()
    data["name"] = str(data["name"]).strip()
    data["phone"] = str(data["phone"]).strip()
    data["dept"] = str(data["dept"]).strip()

    if not PHONE_RE.match(data["phone"]):
        raise BizError("手机号格式不正确（应为 11 位中国大陆手机号），该号码用于接收催还短信")

    if sales_id:
        exists = db.query_scalar(
            "SELECT COUNT(*) AS c FROM sales_person WHERE emp_no = %s AND id <> %s",
            (data["emp_no"], sales_id), 0)
    else:
        exists = db.query_scalar(
            "SELECT COUNT(*) AS c FROM sales_person WHERE emp_no = %s", (data["emp_no"],), 0)
    if int(exists or 0) > 0:
        raise BizError(f"工号 {data['emp_no']} 已存在")
    return data


def _fields(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "emp_no": data["emp_no"],
        "name": data["name"],
        "gender": data.get("gender") or "男",
        "phone": data["phone"],
        "dept": data["dept"],
        "region": (data.get("region") or "").strip(),
        "job_title": data.get("job_title") or "销售代表",
        "entry_date": db.fmt_date(data.get("entry_date")),
        "status": data.get("status") or "在职",
        "remark": (data.get("remark") or "").strip(),
    }


def create_sales(data: Dict[str, Any]) -> Dict[str, Any]:
    data = _validate(data)
    f = _fields(data)
    now = _now()
    sales_id = db.execute(
        """INSERT INTO sales_person
           (emp_no, name, gender, phone, dept, region, job_title, entry_date, status, remark,
            created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (f["emp_no"], f["name"], f["gender"], f["phone"], f["dept"], f["region"], f["job_title"],
         f["entry_date"], f["status"], f["remark"], now, now),
    )
    return get_sales(sales_id)


def update_sales(sales_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    current = get_sales(sales_id)
    merged = {**{k: current.get(k) for k in
                 ("emp_no", "name", "gender", "phone", "dept", "region", "job_title", "status", "remark")},
              **{k: v for k, v in data.items() if v is not None}}
    merged["entry_date"] = data.get("entry_date", current.get("entry_date"))
    merged = _validate(merged, sales_id)
    f = _fields(merged)
    db.affected(
        """UPDATE sales_person
              SET emp_no = %s, name = %s, gender = %s, phone = %s, dept = %s, region = %s,
                  job_title = %s, entry_date = %s, status = %s, remark = %s, updated_at = %s
            WHERE id = %s""",
        (f["emp_no"], f["name"], f["gender"], f["phone"], f["dept"], f["region"], f["job_title"],
         f["entry_date"], f["status"], f["remark"], _now(), sales_id),
    )
    return get_sales(sales_id)


def delete_sales(sales_id: int) -> None:
    get_sales(sales_id)
    # 注意：被逻辑删除的借资记录仍然引用该销售人员，因此按销售人员全量统计
    count = db.query_scalar(
        "SELECT COUNT(*) AS c FROM loan_record WHERE sales_id = %s",
        (sales_id,), 0)
    if int(count or 0) > 0:
        raise BizError(
            f"该销售人员存在 {count} 条借资记录（含已逻辑删除记录），不允许删除；"
            f"请将状态改为“离职”以保留历史台账与催还记录")
    db.affected("DELETE FROM sales_person WHERE id = %s", (sales_id,))


def dept_options() -> List[str]:
    rows = db.query_all("SELECT DISTINCT dept FROM sales_person ORDER BY dept")
    return [r["dept"] for r in rows if r.get("dept")]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
