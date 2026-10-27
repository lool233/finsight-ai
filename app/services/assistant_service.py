# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— AI 智能助手（自然语言查询统计）
=====================================================================
处理流程（NL2SQL 的“意图 + 白名单模板”安全实现）：
    1. 意图识别：先用规则引擎做关键词/实体快速判定，再由 LLM 输出
       JSON（intent + slots）进行校正；LLM 不可用时完全依赖规则引擎。
    2. 数据检索：按意图映射到**预定义的白名单查询模板**，参数化执行 SQL。
       不直接执行大模型生成的 SQL，从根本上杜绝 SQL 注入与越权访问。
    3. 结果解释：把查询结果交给 LLM，生成面向业务人员的中文答复；
       LLM 不可用时使用内置模板生成确定性答复。
    4. 全程记录到 ai_chat_log 表，便于审计与效果分析。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import config
from app import db
from app.llm import LLMUnavailable, llm_client
from app.services import collection_service as coll
from app.services import loan_service as loans
from app.utils import to_int

# ---------------------------------------------------------------------------
# 意图定义
# ---------------------------------------------------------------------------
INTENT_LABELS = {
    "stat_overview": "借资总体情况统计",
    "stat_dept": "按部门统计借资",
    "stat_type": "按借资类型统计",
    "stat_month": "借资月度趋势统计",
    "stat_overdue": "逾期未还与催还情况统计",
    "stat_aging": "逾期账龄分布统计",
    "stat_ranking": "未还金额排名（欠款排行）",
    "stat_person": "指定销售人员借资明细",
    "stat_list": "按条件查询借资明细",
    "other": "非查询统计类问题",
}

QUERY_INTENTS = [k for k in INTENT_LABELS if k != "other"]

RULE_KEYWORDS: Dict[str, List[Tuple[str, int]]] = {
    "stat_aging": [("账龄", 5), ("分档", 3), ("逾期多久", 3), ("逾期时间分布", 4), ("账期", 3)],
    "stat_ranking": [("排名", 5), ("排行", 5), ("最多", 3), ("最高", 3), ("top", 5), ("欠款最多", 5),
                     ("未还最多", 5), ("欠得最多", 5)],
    "stat_dept": [("部门", 4), ("大区", 3), ("各个部", 3), ("区域统计", 3), ("分区", 2)],
    "stat_type": [("借资类型", 5), ("借款类型", 5), ("类型", 3), ("借款用途", 3),
                  ("差旅借款", 3), ("备用金", 3), ("市场推广", 3), ("项目周转", 3)],
    "stat_month": [("趋势", 5), ("每月", 4), ("按月", 4), ("月度", 4), ("近几个月", 4), ("走势", 4)],
    "stat_overdue": [("逾期", 5), ("超期", 4), ("催还", 5), ("催收", 5), ("催款", 4),
                     ("超过3个月", 4), ("超过三个月", 4), ("没有还", 4), ("还没还", 4),
                     ("没归还", 4), ("尚未还", 4), ("未归还", 4), ("未还", 2), ("欠款", 2)],
    "stat_person": [("个人", 3), ("谁的", 3), ("该员工", 3), ("明细", 2), ("台账", 3),
                    ("借了多少", 4), ("还了多少", 4)],
    "stat_overview": [("总览", 5), ("总体", 4), ("一共", 3), ("总共", 3), ("合计", 3),
                      ("总额", 3), ("借资情况", 3), ("整体", 3), ("统计", 2), ("情况", 1), ("多少", 1)],
}

# 同分时的优先级（越靠前越优先）
INTENT_PRIORITY = ["stat_aging", "stat_ranking", "stat_person", "stat_dept", "stat_type",
                   "stat_month", "stat_overdue", "stat_overview", "stat_list"]

# 借资业务领域词汇：用于判断问题是否与“财务借资”相关（用于兜底分类）
DOMAIN_WORDS = ["借资", "借款", "借出", "预支", "垫资", "备用金", "还款", "还清", "归还",
                "欠款", "未还", "台账", "报销", "资金", "财务", "销售", "员工", "业务员",
                "部门", "大区", "公司", "金额", "催", "账单"]


def rule_classify(question: str) -> Dict[str, Any]:
    """基于加权关键词与实体抽取的规则意图识别（无外部依赖、结果可解释）。"""
    text = question.strip()
    slots = extract_slots(question)

    if not text:
        return {"intent": "other", "slots": slots, "confidence": 0.9, "method": "规则引擎"}

    scores: Dict[str, float] = {k: 0.0 for k in INTENT_PRIORITY}
    hits: Dict[str, List[str]] = {}
    lowered = text.lower()
    for intent, keywords in RULE_KEYWORDS.items():
        for word, weight in keywords:
            if word.lower() in lowered:
                scores[intent] += weight
                hits.setdefault(intent, []).append(word)

    # 实体加权：出现具体人名/部门名/类型时，指向更精确的意图
    if slots.get("sales_name"):
        scores["stat_person"] += 4
        hits.setdefault("stat_person", []).append("人名")
    if slots.get("dept"):
        scores["stat_dept"] += 3
        hits.setdefault("stat_dept", []).append("部门名")
    if slots.get("loan_type"):
        scores["stat_type"] += 4
        hits.setdefault("stat_type", []).append("借资类型")
    if slots.get("top") and any(k in text for k in ("最多", "最高", "前", "排行", "排名", "top", "TOP")):
        scores["stat_ranking"] += 4
        hits.setdefault("stat_ranking", []).append("TOP-N")

    # 无任何统计关键词时：属于借资业务领域则按总体情况处理，否则判为非查询统计类问题
    if max(scores.values()) <= 0:
        if any(slots.get(k) for k in ("sales_name", "dept", "status", "loan_type", "min_amount")):
            scores["stat_list"] = 1.0
            hits["stat_list"] = ["条件筛选"]
        elif any(w in text for w in DOMAIN_WORDS):
            return {"intent": "stat_overview", "slots": slots, "confidence": 0.4,
                    "method": "规则引擎", "reason": "命中借资领域词但无明确统计词，按总体情况处理"}
        else:
            return {"intent": "other", "slots": slots, "confidence": 0.75, "method": "规则引擎",
                    "reason": "问题未涉及财务借资业务领域"}

    best = max(scores.values())
    candidates = [k for k in INTENT_PRIORITY if scores[k] == best]
    intent = candidates[0]
    total = sum(scores.values()) or 1
    confidence = round(min(0.95, 0.5 + best / total * 0.45), 2)
    return {
        "intent": intent,
        "slots": slots,
        "confidence": confidence,
        "method": "规则引擎",
        "reason": "命中关键词：" + "、".join(hits.get(intent, [])[:5]),
    }


def _all_names() -> List[str]:
    return [r["name"] for r in db.query_all("SELECT name FROM sales_person")]


def _all_depts() -> List[str]:
    return [r["dept"] for r in db.query_all("SELECT DISTINCT dept FROM sales_person")]


# ---------------------------------------------------------------------------
# 规则引擎：实体抽取
# ---------------------------------------------------------------------------
def extract_slots(question: str) -> Dict[str, Any]:
    slots: Dict[str, Any] = {}
    text = question.strip()

    for name in _all_names():
        if name and name in text:
            slots["sales_name"] = name
            break

    for dept in _all_depts():
        if dept and dept in text:
            slots["dept"] = dept
            break
    if "dept" not in slots:
        m = re.search(r"([\u4e00-\u9fa5]{2,8}(?:部|大区|中心|区域))", text)
        if m and m.group(1) not in ("部门", "全部"):
            slots["dept"] = m.group(1)

    for loan_type in loans.LOAN_TYPES:
        if loan_type in text:
            slots["loan_type"] = loan_type
            break
    if "loan_type" not in slots and "备用金" in text:
        slots["loan_type"] = "备用金"

    for status in loans.LOAN_STATUS:
        if status in text:
            slots["status"] = status
            break
    if "status" not in slots:
        if re.search(r"没还|未还|没归还|未归还|还欠", text):
            slots["status"] = "未结清"

    m = re.search(r"(?:最近|近)\s*([一二三四五六七八九十\d]+)\s*个?月", text)
    if m:
        slots["months"] = _cn_num(m.group(1))
    elif "本月" in text or "这个月" in text:
        slots["months"] = 1
    elif "今年" in text or "本年度" in text:
        slots["months"] = 12
    elif re.search(r"上半年", text):
        slots["months"] = 6

    m = re.search(r"(?:前|top|TOP)\s*([一二三四五六七八九十\d]+)", text)
    if m:
        slots["top"] = _cn_num(m.group(1))
    else:
        m = re.search(r"([一二三四五六七八九十\d]+)\s*(?:名|个|位|人)", text)
        if m:
            slots["top"] = _cn_num(m.group(1))

    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:万|万元)", text)
    if m:
        slots["min_amount"] = float(m.group(1)) * 10000
    else:
        m = re.search(r"超过\s*(\d+(?:\.\d+)?)\s*元", text)
        if m:
            slots["min_amount"] = float(m.group(1))

    return slots


def _cn_num(value: str) -> int:
    value = value.strip()
    if value.isdigit():
        return max(1, min(int(value), 100))
    table = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + table.get(value[1:], 0)
    if value.endswith("十"):
        return table.get(value[:-1], 1) * 10
    if "十" in value:
        head, _, tail = value.partition("十")
        return table.get(head, 1) * 10 + table.get(tail, 0)
    return table.get(value, 3)


# ---------------------------------------------------------------------------
# LLM 意图识别
# ---------------------------------------------------------------------------
CLASSIFY_SYSTEM_PROMPT = """你是企业财务系统的意图识别模块，负责判断用户问题是否属于“查询统计财务借资情况”。

可选的意图（intent）取值及含义：
- stat_overview：借资总体情况统计（总额、未还、逾期总额、人数等）
- stat_dept：按部门/大区统计借资
- stat_type：按借资类型（差旅借款、备用金、市场推广借款等）统计
- stat_month：借资的月度/趋势统计
- stat_overdue：逾期未还、需催还的情况统计
- stat_aging：逾期账龄分布统计
- stat_ranking：未还金额排名、欠款最多的人员排行
- stat_person：查询某个具体销售人员的借资明细
- stat_list：按条件（部门、状态、类型、时间）查询借资明细列表
- other：与借资查询统计无关的问题（问候、闲聊、系统使用咨询等）

请从问题中抽取条件（slots），可为空：sales_name、dept、loan_type、status、months、top、min_amount。

只输出 JSON，格式：
{"intent": "上述取值之一", "slots": {"sales_name": "", "dept": "", "loan_type": "", "status": "", "months": 0, "top": 0}, "confidence": 0.0-1.0, "reason": "简要理由"}"""


def llm_classify(question: str, rule_result: Dict[str, Any]) -> Dict[str, Any]:
    if not llm_client.enabled:
        return rule_result
    try:
        data = llm_client.chat_json(
            [
                {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                {"role": "user", "content": f"用户问题：{question}"},
            ],
            temperature=0.0,
        )
    except LLMUnavailable:
        return rule_result

    intent = str(data.get("intent") or "").strip()
    if intent not in INTENT_LABELS:
        return rule_result

    slots = dict(rule_result.get("slots") or {})
    for key, value in (data.get("slots") or {}).items():
        if value in (None, "", 0, "0", []):
            continue
        if key in ("months", "top", "min_amount"):
            slots[key] = to_int(value) if key != "min_amount" else float(value)
        else:
            slots[key] = str(value).strip()
    confidence = float(data.get("confidence") or 0.0)
    return {
        "intent": intent,
        "slots": slots,
        "confidence": confidence,
        "reason": str(data.get("reason") or ""),
        "method": "LLM",
    }


# ---------------------------------------------------------------------------
# 查询模板（白名单）
# ---------------------------------------------------------------------------
def _table(columns: List[Tuple[str, str]], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"columns": [{"key": k, "label": v} for k, v in columns],
            "rows": rows}


def q_overview(slots: Dict[str, Any]) -> Dict[str, Any]:
    data = loans.overview()
    rows = [{
        "借资笔数": data["loan_count"],
        "借资总额": f"{data['total_amount']:,.2f}",
        "已还金额": f"{data['repaid_amount']:,.2f}",
        "未还金额": f"{data['unpaid_amount']:,.2f}",
        "逾期笔数": data["overdue_count"],
        "逾期未还金额": f"{data['overdue_amount']:,.2f}",
        "逾期人数": data["overdue_person"],
        "回款率": f"{data['collection_rate']}%",
    }]
    return {
        "title": "借资总体情况",
        "sql": "SELECT COUNT(*), SUM(amount), SUM(repaid_amount), SUM(amount - repaid_amount) "
               "FROM loan_record WHERE is_deleted = 0;   -- 逾期口径另按 repay_deadline 与借资日+3个月取较早者统计",
        "data": _table([(k, k) for k in rows[0]], rows),
        "summary": (
            f"当前共 {data['loan_count']} 笔借资，借资总额 {data['total_amount']:,.2f} 元，"
            f"已还 {data['repaid_amount']:,.2f} 元，未还 {data['unpaid_amount']:,.2f} 元，回款率 {data['collection_rate']}%；"
            f"其中逾期 {data['overdue_count']} 笔、涉及 {data['overdue_person']} 人，"
            f"逾期未还金额 {data['overdue_amount']:,.2f} 元。"
        ),
        "raw": data,
    }


def q_dept(slots: Dict[str, Any]) -> Dict[str, Any]:
    rows = loans.by_dept()
    table_rows = [{
        "部门": r["name"],
        "借资笔数": r["loan_count"],
        "借资总额": f"{float(r['total_amount']):,.2f}",
        "已还金额": f"{float(r['repaid_amount']):,.2f}",
        "未还金额": f"{float(r['unpaid_amount']):,.2f}",
    } for r in rows]
    total = sum(float(r["total_amount"]) for r in rows)
    top = rows[0] if rows else None
    summary = f"共 {len(rows)} 个部门存在借资，借资总额 {total:,.2f} 元。"
    if top:
        summary += (f"其中 {top['name']} 借资最多，{top['loan_count']} 笔共 "
                    f"{float(top['total_amount']):,.2f} 元，未还 {float(top['unpaid_amount']):,.2f} 元。")
    return {
        "title": "各部门借资统计",
        "sql": "SELECT s.dept, COUNT(l.id), SUM(l.amount), SUM(l.repaid_amount), "
               "SUM(l.amount - l.repaid_amount) FROM loan_record l JOIN sales_person s "
               "ON s.id = l.sales_id WHERE l.is_deleted = 0 GROUP BY s.dept ORDER BY 3 DESC;",
        "data": _table([(k, k) for k in table_rows[0]] if table_rows else [], table_rows),
        "summary": summary,
        "raw": rows,
    }


def q_type(slots: Dict[str, Any]) -> Dict[str, Any]:
    rows = loans.by_type()
    table_rows = [{
        "借资类型": r["name"],
        "笔数": r["loan_count"],
        "金额合计": f"{float(r['total_amount']):,.2f}",
        "未还金额": f"{float(r['unpaid_amount']):,.2f}",
    } for r in rows]
    top = rows[0] if rows else None
    summary = f"按借资类型共 {len(rows)} 类。"
    if top:
        summary += (f"{top['name']} 金额最高，{top['loan_count']} 笔共 "
                    f"{float(top['total_amount']):,.2f} 元，其中未还 {float(top['unpaid_amount']):,.2f} 元。")
    return {
        "title": "借资类型统计",
        "sql": "SELECT loan_type, COUNT(*), SUM(amount), SUM(amount - repaid_amount) "
               "FROM loan_record WHERE is_deleted = 0 GROUP BY loan_type ORDER BY 3 DESC;",
        "data": _table([(k, k) for k in table_rows[0]] if table_rows else [], table_rows),
        "summary": summary,
        "raw": rows,
    }


def q_month(slots: Dict[str, Any]) -> Dict[str, Any]:
    months = to_int(slots.get("months") or 6) or 6
    months = max(1, min(months, 36))
    rows = loans.by_month(months)
    table_rows = [{
        "月份": r["name"],
        "借资笔数": r["loan_count"],
        "借资金额": f"{float(r['total_amount']):,.2f}",
        "未还金额": f"{float(r['unpaid_amount']):,.2f}",
    } for r in rows]
    total = sum(float(r["total_amount"]) for r in rows)
    peak = max(rows, key=lambda r: float(r["total_amount"])) if rows else None
    summary = f"近 {months} 个月共发生借资 {sum(r['loan_count'] for r in rows)} 笔，合计 {total:,.2f} 元。"
    if peak:
        summary += f"其中 {peak['name']} 金额最高，为 {float(peak['total_amount']):,.2f} 元。"
    return {
        "title": f"近 {months} 个月借资趋势",
        "sql": "SELECT loan_date, amount, repaid_amount FROM loan_record "
               "WHERE is_deleted = 0 AND loan_date >= <起始日期>;  -- 按自然月聚合",
        "data": _table([(k, k) for k in table_rows[0]] if table_rows else [], table_rows),
        "summary": summary,
        "raw": rows,
    }


def q_overdue(slots: Dict[str, Any]) -> Dict[str, Any]:
    rows = coll.find_overdue({
        "dept": slots.get("dept"),
        "sales_id": None,
        "keyword": slots.get("sales_name") or "",
        "months": slots.get("months"),
        "level": slots.get("level"),
    })
    top = to_int(slots.get("top") or 20) or 20
    table_rows = [{
        "借资单号": r["loan_no"],
        "借款人": r["sales_name"],
        "部门": r["dept"],
        "手机号": r["phone"],
        "借资金额": f"{float(r['amount']):,.2f}",
        "未还金额": f"{float(r['unpaid_amount']):,.2f}",
        "借资日期": str(r["loan_date"])[:10],
        "约定还款日": str(r["repay_deadline"])[:10],
        "逾期天数": r["overdue_days"],
        "催还级别": r["collection_level"],
    } for r in rows[:top]]

    amount = sum(float(r["unpaid_amount"]) for r in rows)
    level_count: Dict[str, int] = {}
    for r in rows:
        level_count[r["collection_level"]] = level_count.get(r["collection_level"], 0) + 1
    level_text = "、".join(f"{k} {v} 笔" for k, v in sorted(level_count.items())) or "无"
    summary = (f"当前共有 {len(rows)} 笔借资逾期（超过 {config.OVERDUE_MONTHS} 个月未还或约定还款日已过），"
               f"涉及未还金额 {amount:,.2f} 元；按逾期天数分级：{level_text}。"
               f"系统已可将这些记录生成催还记录并下发催还短信。")
    return {
        "title": "逾期未还借资明细（催还对象）",
        "sql": "SELECT l.loan_no, s.name, s.phone, l.amount, l.amount - l.repaid_amount AS unpaid, "
               "l.loan_date, l.repay_deadline FROM loan_record l JOIN sales_person s ON s.id = l.sales_id "
               "WHERE l.is_deleted = 0 AND l.repaid_amount < l.amount "
               "AND l.status NOT IN ('已还清','已核销') "
               "AND (l.repay_deadline < CURDATE() OR l.loan_date <= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)) "
               "ORDER BY l.repay_deadline;",
        "data": _table([(k, k) for k in table_rows[0]] if table_rows else [], table_rows),
        "summary": summary,
        "raw": rows,
    }


def q_aging(slots: Dict[str, Any]) -> Dict[str, Any]:
    rows = loans.overdue_aging()
    table_rows = [{
        "账龄区间": r["name"],
        "笔数": r["loan_count"],
        "未还金额": f"{float(r['unpaid_amount']):,.2f}",
    } for r in rows]
    overdue_rows = [r for r in rows if r["name"] != "未逾期"]
    total_count = sum(r["loan_count"] for r in overdue_rows)
    total_amount = sum(float(r["unpaid_amount"]) for r in overdue_rows)
    summary = (f"按约定还款日分档，当前逾期 {total_count} 笔，未还金额合计 {total_amount:,.2f} 元。"
               + "；".join(f"{r['name']} {r['loan_count']} 笔（{float(r['unpaid_amount']):,.2f} 元）"
                           for r in overdue_rows if r["loan_count"]))
    return {
        "title": "逾期账龄分布",
        "sql": "SELECT CASE WHEN repay_deadline >= CURDATE() THEN '未逾期' ... END AS 账龄区间, "
               "COUNT(*), SUM(amount - repaid_amount) FROM loan_record WHERE is_deleted = 0 "
               "AND amount > repaid_amount GROUP BY 账龄区间;",
        "data": _table([(k, k) for k in table_rows[0]] if table_rows else [], table_rows),
        "summary": summary,
        "raw": rows,
    }


def q_ranking(slots: Dict[str, Any]) -> Dict[str, Any]:
    top = to_int(slots.get("top") or 10) or 10
    top = max(1, min(top, 50))
    rows = loans.top_debtors(top)
    table_rows = [{
        "工号": r["emp_no"],
        "姓名": r["name"],
        "部门": r["dept"],
        "手机号": r["phone"],
        "借资笔数": r["loan_count"],
        "借资总额": f"{float(r['total_amount']):,.2f}",
        "未还金额": f"{float(r['unpaid_amount']):,.2f}",
    } for r in rows]
    summary = f"未还金额排名前 {len(rows)} 位的销售人员如下。"
    if rows:
        first = rows[0]
        summary += (f"其中 {first['name']}（{first['dept']}）未还金额最高，为 "
                    f"{float(first['unpaid_amount']):,.2f} 元。")
    return {
        "title": "销售人员未还金额排名",
        "sql": "SELECT s.emp_no, s.name, s.dept, COUNT(l.id), SUM(l.amount), "
               "SUM(l.amount - l.repaid_amount) AS unpaid FROM loan_record l "
               "JOIN sales_person s ON s.id = l.sales_id WHERE l.is_deleted = 0 "
               "AND l.amount > l.repaid_amount GROUP BY s.id ORDER BY unpaid DESC LIMIT %s;",
        "data": _table([(k, k) for k in table_rows[0]] if table_rows else [], table_rows),
        "summary": summary,
        "raw": rows,
    }


def q_person(slots: Dict[str, Any]) -> Dict[str, Any]:
    name = (slots.get("sales_name") or "").strip()
    if not name:
        return q_list(slots)
    person = db.query_one("SELECT * FROM sales_person WHERE name = %s", (name,))
    if not person:
        return {
            "title": "未找到该销售人员",
            "sql": "SELECT * FROM sales_person WHERE name = %s;",
            "data": _table([], []),
            "summary": f"系统中没有找到姓名为“{name}”的销售人员，请确认姓名是否正确。",
            "raw": [],
        }

    result = loans.list_loans({"sales_id": person["id"]}, page=1, size=100)
    items = result["items"]
    table_rows = [{
        "借资单号": r["loan_no"],
        "借资日期": str(r["loan_date"])[:10],
        "借资金额": f"{float(r['amount']):,.2f}",
        "已还金额": f"{float(r['repaid_amount']):,.2f}",
        "未还金额": f"{float(r['unpaid_amount']):,.2f}",
        "类型": r["loan_type"],
        "状态": r["status"],
        "逾期天数": r["overdue_days"],
    } for r in items]
    total = float(result["summary"]["total_amount"] or 0)
    unpaid = float(result["summary"]["unpaid_amount"] or 0)
    overdue = [r for r in items if r["is_overdue"]]
    summary = (f"{person['name']}（工号 {person['emp_no']}，{person['dept']}，{person['status']}）"
               f"共有 {len(items)} 笔借资，累计 {total:,.2f} 元，已还 "
               f"{float(result['summary']['repaid_amount'] or 0):,.2f} 元，未还 {unpaid:,.2f} 元。")
    if overdue:
        summary += (f"其中 {len(overdue)} 笔已逾期，逾期金额 "
                    f"{sum(float(r['unpaid_amount']) for r in overdue):,.2f} 元，建议尽快催还。")
    else:
        summary += "目前没有逾期记录。"
    return {
        "title": f"{person['name']} 的借资明细",
        "sql": "SELECT * FROM loan_record l JOIN sales_person s ON s.id = l.sales_id "
               "WHERE l.sales_id = %s AND l.is_deleted = 0 ORDER BY l.loan_date DESC;",
        "data": _table([(k, k) for k in table_rows[0]] if table_rows else [], table_rows),
        "summary": summary,
        "raw": {"person": person, "items": items, "summary": result["summary"]},
    }


def q_list(slots: Dict[str, Any]) -> Dict[str, Any]:
    args: Dict[str, Any] = {}
    if slots.get("dept"):
        args["dept"] = slots["dept"]
    if slots.get("loan_type"):
        args["loan_type"] = slots["loan_type"]
    if slots.get("status") == "未结清":
        args["unsettled"] = 1
    elif slots.get("status"):
        args["status"] = slots["status"]
    if slots.get("sales_name"):
        args["keyword"] = slots["sales_name"]
    if slots.get("min_amount"):
        args["min_amount"] = slots["min_amount"]
    if slots.get("months"):
        start = db.add_months(db.today().replace(day=1), -(to_int(slots["months"]) - 1))
        args["start_date"] = start.strftime("%Y-%m-%d")

    result = loans.list_loans(args, page=1, size=config.ASSISTANT_MAX_ROWS)
    items = result["items"]
    table_rows = [{
        "借资单号": r["loan_no"],
        "借款人": r["sales_name"],
        "部门": r["dept"],
        "借资金额": f"{float(r['amount']):,.2f}",
        "未还金额": f"{float(r['unpaid_amount']):,.2f}",
        "借资日期": str(r["loan_date"])[:10],
        "状态": r["status"],
        "逾期天数": r["overdue_days"],
    } for r in items]

    condition_desc = []
    if args.get("dept"):
        condition_desc.append(f"部门={args['dept']}")
    if args.get("loan_type"):
        condition_desc.append(f"类型={args['loan_type']}")
    if args.get("status"):
        condition_desc.append(f"状态={args['status']}")
    if args.get("unsettled"):
        condition_desc.append("状态=未结清")
    if args.get("keyword"):
        condition_desc.append(f"关键字={args['keyword']}")
    if args.get("start_date"):
        condition_desc.append(f"借资日期≥{args['start_date']}")
    if args.get("min_amount"):
        condition_desc.append(f"金额≥{args['min_amount']:,.2f}")
    condition_text = "、".join(condition_desc) or "全部借资记录"

    summary = (f"按条件（{condition_text}）共查询到 {result['total']} 笔借资，"
               f"金额合计 {float(result['summary']['total_amount'] or 0):,.2f} 元，"
               f"其中未还 {float(result['summary']['unpaid_amount'] or 0):,.2f} 元。")
    return {
        "title": f"借资明细查询（{condition_text}）",
        "sql": "SELECT l.loan_no, s.name, l.amount, l.amount - l.repaid_amount AS unpaid, "
               "l.loan_date, l.status FROM loan_record l JOIN sales_person s ON s.id = l.sales_id "
               "WHERE l.is_deleted = 0 <动态条件：部门/类型/状态/关键字/日期/金额> "
               "ORDER BY l.loan_date DESC LIMIT %s;",
        "data": _table([(k, k) for k in table_rows[0]] if table_rows else [], table_rows),
        "summary": summary,
        "raw": {"total": result["total"], "summary": result["summary"], "items": items[:50]},
    }


QUERY_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "stat_overview": q_overview,
    "stat_dept": q_dept,
    "stat_type": q_type,
    "stat_month": q_month,
    "stat_overdue": q_overdue,
    "stat_aging": q_aging,
    "stat_ranking": q_ranking,
    "stat_person": q_person,
    "stat_list": q_list,
}


# ---------------------------------------------------------------------------
# 答复组织
# ---------------------------------------------------------------------------
ANSWER_SYSTEM_PROMPT = """你是企业“智析 FinSight AI”的AI智能助手，面向公司财务人员和销售管理者。
用户的问题已经被识别为“查询统计财务借资情况”，系统已经查询数据库并把结果以 JSON 传给你。
请基于给定数据，用简体中文输出一段专业、简洁的业务答复。

要求：
1. 必须包含关键数字（总额、笔数、人数等），金额保留 2 位小数并注明单位“元”；
2. 可以分点陈述，突出异常情况（如逾期金额大、逾期时间长的人员）；
3. 严禁编造数据，只能引用给定 JSON 中的内容；数据为空时如实说明“暂无数据”；
4. 不要输出 SQL、不要重复大段表格（表格由系统单独展示）；
5. 篇幅控制在 250 字以内。"""


def llm_answer(question: str, intent: str, plan: Dict[str, Any]) -> Optional[str]:
    if not llm_client.enabled:
        return None
    payload = {
        "当前日期": db.today().strftime("%Y-%m-%d"),
        "识别意图": intent,
        "意图说明": INTENT_LABELS.get(intent),
        "查询结论草稿": plan.get("summary"),
        "查询结果": plan.get("raw"),
    }
    try:
        text = llm_client.chat_text(
            [
                {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content":
                    f"用户问题：{question}\n\n数据库查询结果（JSON）：\n"
                    f"{json.dumps(payload, ensure_ascii=False, default=str)[:6000]}"},
            ],
            temperature=0.3,
        )
    except LLMUnavailable:
        return None
    return text.strip() or None


def fallback_answer(question: str, intent: str, plan: Dict[str, Any],
                    slots: Dict[str, Any]) -> str:
    """LLM 不可用时的确定性答复（模板生成）。"""
    if intent == "other":
        return ("您好，我是智析 FinSight AI 的智能助手，可以帮您：\n"
                "一、查询借资统计：\n"
                "1. 目前公司借资总体情况如何？\n"
                "2. 各部门借资和未还金额是多少？\n"
                "3. 有哪些人借资超过 3 个月还没还？\n"
                "4. 未还金额最多的前 5 名销售人员是谁？\n"
                "5. 陈志强的借资明细和还款情况？\n"
                "6. 最近 6 个月借资趋势如何？\n"
                "二、查询公司财务制度：\n"
                "7. 借资逾期多久算三级催收？\n"
                "8. 核销需要哪些票据？\n"
                "9. 许曼逾期229天，按制度该怎么处理？\n"
                "请换一种说法再问一次。")
    return plan.get("summary") or "已完成查询，详情见下方结果表格。"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def classify_and_query(question: str) -> Dict[str, Any]:
    """
    「意图识别 + 数据检索」——供 Agent 作为 query_statistics 工具调用。
    只做分类与查询，不生成自然语言答复、不写会话日志。
    """
    rule_result = rule_classify(question)
    classify_result = llm_classify(question, rule_result)
    intent = classify_result["intent"]
    slots = classify_result.get("slots") or {}

    plan: Dict[str, Any] = {"title": "", "sql": "", "data": {"columns": [], "rows": []},
                            "summary": "", "raw": None}
    if intent in QUERY_HANDLERS:
        try:
            plan = QUERY_HANDLERS[intent](slots)
        except Exception as exc:  # 查询失败也要给用户可读反馈
            plan = {"title": "查询失败", "sql": "", "data": {"columns": [], "rows": []},
                    "summary": f"数据查询出现异常：{exc}", "raw": None}

    return {
        "intent": intent,
        "intent_name": INTENT_LABELS.get(intent, intent),
        "is_statistics_query": intent != "other",
        "slots": slots,
        "method": classify_result.get("method"),
        "confidence": classify_result.get("confidence"),
        "reason": classify_result.get("reason"),
        "plan": plan,
    }


def ask(question: str, session_id: str = "", user_id: Optional[int] = None) -> Dict[str, Any]:
    started = time.time()
    question = (question or "").strip()
    if not question:
        return {"answer": "请输入您想咨询的借资统计问题。", "intent": "other",
                "intent_name": INTENT_LABELS["other"], "data": {"columns": [], "rows": []},
                "method": "规则引擎", "elapsed_ms": 0}

    queried = classify_and_query(question)
    intent = queried["intent"]
    slots = queried["slots"]
    plan = queried["plan"]

    answer = llm_answer(question, intent, plan)
    answer_source = "LLM"
    if not answer:
        answer = fallback_answer(question, intent, plan, slots)
        answer_source = "规则模板"

    elapsed = int((time.time() - started) * 1000)
    result = {
        "answer": answer,
        "answer_source": answer_source,
        "intent": intent,
        "intent_name": queried["intent_name"],
        "is_statistics_query": queried["is_statistics_query"],
        "slots": slots,
        "method": queried.get("method"),
        "confidence": queried.get("confidence"),
        "reason": queried.get("reason"),
        "title": plan.get("title"),
        "sql": plan.get("sql"),
        "data": plan.get("data"),
        "summary": plan.get("summary"),
        "llm": llm_client.status(),
        "elapsed_ms": elapsed,
    }
    log_chat(session_id, user_id, question, result)
    return result


def log_chat(session_id: str, user_id: Optional[int], question: str,
             result: Dict[str, Any]) -> None:
    try:
        db.execute(
            """INSERT INTO ai_chat_log
               (session_id, user_id, question, intent, slots, sql_text, answer,
                data_snapshot, llm_model, elapsed_ms, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                session_id or "", user_id, question[:500], result.get("intent"),
                json.dumps(result.get("slots") or {}, ensure_ascii=False)[:500],
                (result.get("sql") or "")[:2000], result.get("answer") or "",
                json.dumps(result.get("data") or {}, ensure_ascii=False, default=str)[:2000],
                llm_client.model if result.get("answer_source") == "LLM" else "内置规则模板",
                int(result.get("elapsed_ms") or 0),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
    except Exception:
        pass


def history(session_id: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    if session_id:
        return db.query_all(
            """SELECT id, question, intent, answer, llm_model, elapsed_ms, created_at
                 FROM ai_chat_log WHERE session_id = %s ORDER BY id DESC LIMIT %s""",
            (session_id, limit))
    return db.query_all(
        """SELECT id, question, intent, answer, llm_model, elapsed_ms, created_at
             FROM ai_chat_log ORDER BY id DESC LIMIT %s""", (limit,))


SAMPLES = [
    "目前公司借资总体情况怎么样？",
    "各部门的借资和未还金额分别是多少？",
    "有哪些人借资超过3个月还没有还？",
    "未还金额最多的前5名销售人员是谁？",
    "陈志强的借资明细和还款情况如何？",
    "最近6个月的借资趋势如何？",
    "逾期账龄分布情况怎样？",
    "华东销售部有哪些借资记录？",
]
