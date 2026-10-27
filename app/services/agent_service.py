# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 多工具 Agent 编排服务
=====================================================================
把 AI 助手从「单步 NL2SQL」升级为「多工具 Agent」：

    规划    由 LLM 输出 JSON 计划（工具 + 参数，最多 AGENT_MAX_STEPS 步）；
            LLM 不可用时退化为确定性的规则规划，行为可预期、可解释。
    执行    逐个工具调用，记录每步的入参、结果摘要与耗时（执行轨迹）。
    合成    把「数据统计结果 + 制度条款依据」合并为一段结论，制度部分标注出处。

三类工具：
    1. query_statistics  —— 聚合统计（9 类白名单查询模板，内部含 LLM 意图识别）
    2. get_loan_detail    —— 指定人员的借资台账明细（含还款流水、催还次数）
    3. search_policy      —— 制度知识库 RAG 检索（BM25 + TF-IDF + LLM 重排）

典型价值场景：『许曼逾期 229 天，按制度该怎么处理？』
    第 1 步 search_policy 取到《逾期催收管理规范》三级催收措施；
    第 2 步 get_loan_detail 取到她的实际台账与历史催还次数；
    第 3 步合成结论 —— 纯 NL2SQL 无法完成。
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from config import config
from app import db
from app.llm import LLMUnavailable, llm_client
from app.services import assistant_service as assistant
from app.services import loan_service as loans
from app.services import rag_service

ROUTE_LABELS = {
    "statistics": "数据统计问答",
    "policy": "制度条款问答",
    "mixed": "统计 + 制度综合问答",
    "other": "非业务问题",
}

TOOLS: Dict[str, Dict[str, str]] = {
    "query_statistics": {
        "desc": "查询借资统计数据：总额、未还、逾期、部门/类型/月度统计、欠款排名、条件列表等聚合类问题",
        "args": '{"question": "用户原问题"}',
    },
    "get_loan_detail": {
        "desc": "查询某位销售人员的借资台账明细，含每笔的金额、已还、未还、状态、逾期天数、还款流水与催还次数",
        "args": '{"name": "销售人员姓名"}',
    },
    "search_policy": {
        "desc": "检索公司财务制度条款（销售借支管理办法、逾期催收管理规范、还款与核销流程、常见问题），用于回答规定、流程、标准、额度、期限、材料、三级分级等问题",
        "args": '{"query": "检索用的关键词或原问题"}',
    },
}

PLAN_PROMPT = """你是企业财务系统的任务规划器。请根据用户问题，规划需要调用哪些工具、按什么顺序调用。

可用工具：
{tools}

规则：
1. 最多 {max_steps} 步；同一工具不要重复调用；
2. 纯统计类问题只调 query_statistics；纯制度规定类问题只调 search_policy；
3. 既涉及「某人的具体情况」又涉及「制度怎么规定/如何处理」时，先 search_policy 再 get_loan_detail；
4. 问题与公司借资、催收、还款业务完全无关时，返回空 steps；
5. 只输出 JSON：{{"steps": [{{"action": "工具名", "args": {{...}}}}], "reason": "简要理由"}}"""

COMPOSE_PROMPT = """你是企业「借资管理与智能催收」系统的 AI 助手，现在要把工具执行结果整理成给用户的中文答复。

要求：
1. 先给结论，再给依据；有数据时列出关键数字（金额保留两位小数并加"元"）；
2. 涉及制度规定的，必须标注出处，格式「依据：《文档名称》- 章节」；
3. 只能引用工具结果中的内容，禁止编造数字或条款；
4. 工具结果为空时如实说明，并给出可行的下一步建议；
5. 控制在 300 字以内，不要输出 SQL、JSON 或工具名。"""

POLICY_KEYWORDS_STRONG = ("制度", "规定", "办法", "规范", "条例", "条款", "依据", "如何规定", "第几条")
POLICY_KEYWORDS_SOFT = ("怎么办", "怎么处理", "如何处理", "多久", "标准", "条件", "额度", "上限", "材料",
                        "票据", "核销", "审批", "级别", "分级", "能不能", "可不可以", "是否", "要求",
                        "范围", "流程", "规定是")
DATA_HINTS = ("总额", "总金额", "多少笔", "几笔", "排名", "排行", "前五", "前三", "统计", "部门",
              "趋势", "占比", "平均")


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------
def _tool_query_statistics(question: str) -> Dict[str, Any]:
    queried = assistant.classify_and_query(question)
    plan = queried.get("plan") or {}
    return {
        "ok": True,
        "summary": plan.get("summary") or "未获得统计结果",
        "data": plan.get("data") or {"columns": [], "rows": []},
        "sql": plan.get("sql") or "",
        "title": plan.get("title") or "",
        "intent": queried.get("intent"),
        "intent_name": queried.get("intent_name"),
        "method": queried.get("method"),
        "confidence": queried.get("confidence"),
        "slots": queried.get("slots") or {},
        "is_statistics_query": queried.get("is_statistics_query"),
    }


def _tool_get_loan_detail(name: str) -> Dict[str, Any]:
    person = db.query_one("SELECT * FROM sales_person WHERE name = %s", (name,))
    if not person:
        return {"ok": False, "summary": f"系统中没有找到姓名为“{name}”的销售人员", "data": None}

    result = loans.list_loans({"sales_id": person["id"]}, page=1, size=20)
    items = result["items"]
    rows = []
    for item in items:
        collection_count = int(db.query_scalar(
            "SELECT COUNT(*) AS c FROM collection_record WHERE loan_id = %s",
            (item["id"],), 0) or 0)
        repay_count = int(db.query_scalar(
            "SELECT COUNT(*) AS c FROM repayment_record WHERE loan_id = %s",
            (item["id"],), 0) or 0)
        rows.append({
            "借资单号": item["loan_no"],
            "借资日期": str(item["loan_date"])[:10],
            "约定还款日": str(item["repay_deadline"])[:10],
            "借资金额": round(float(item["amount"]), 2),
            "已还金额": round(float(item["repaid_amount"]), 2),
            "未还金额": round(float(item["unpaid_amount"]), 2),
            "状态": item["status"],
            "逾期天数": item["overdue_days"],
            "还款笔数": repay_count,
            "催还次数": collection_count,
        })

    unpaid = float(result["summary"].get("unpaid_amount") or 0)
    overdue_items = [r for r in rows if r["逾期天数"] > 0 and r["未还金额"] > 0]
    summary = (
        f"{person['name']}（工号 {person['emp_no']}，{person['dept']}，{person['status']}，"
        f"电话 {person['phone']}）共有 {len(items)} 笔借资，累计 "
        f"{float(result['summary'].get('total_amount') or 0):,.2f} 元，未还 {unpaid:,.2f} 元；"
        f"其中逾期 {len(overdue_items)} 笔"
        + ("：" + "；".join(
            f"{r['借资单号']} 逾期 {r['逾期天数']} 天、未还 {r['未还金额']:,.2f} 元、已催还 {r['催还次数']} 次"
            for r in overdue_items) if overdue_items else "。")
    )
    return {
        "ok": True,
        "summary": summary,
        "data": {"columns": [{"key": k, "label": k} for k in rows[0]] if rows else [],
                 "rows": rows},
        "person": person["name"],
        "unpaid": unpaid,
        "overdue_count": len(overdue_items),
    }


def _tool_search_policy(query: str) -> Dict[str, Any]:
    result = rag_service.answer(query)
    return {
        "ok": bool(result.get("evidence")),
        "summary": result.get("answer") or "",
        "evidence": result.get("evidence") or [],
        "answer_source": result.get("answer_source"),
        "retrieval": result.get("retrieval") or {},
    }


EXECUTORS = {
    "query_statistics": lambda args, q: _tool_query_statistics(args.get("question") or q),
    "get_loan_detail": lambda args, q: _tool_get_loan_detail(str(args.get("name") or "").strip()),
    "search_policy": lambda args, q: _tool_search_policy(args.get("query") or q),
}


# ---------------------------------------------------------------------------
# 规划
# ---------------------------------------------------------------------------
def _person_in(question: str) -> Optional[str]:
    for row in db.query_all("SELECT name FROM sales_person ORDER BY LENGTH(name) DESC"):
        name = row.get("name") or ""
        if name and name in question:
            return name
    return None


def rule_plan(question: str) -> List[Dict[str, Any]]:
    """LLM 不可用时的确定性规划：按关键词与实体决定工具与顺序。"""
    name = _person_in(question)
    stats_likely = assistant.rule_classify(question)["intent"] != "other"
    strong = any(word in question for word in POLICY_KEYWORDS_STRONG)
    soft = any(word in question for word in POLICY_KEYWORDS_SOFT)
    data_hint = any(word in question for word in DATA_HINTS) or bool(name)

    steps: List[Dict[str, Any]] = []
    if strong:
        steps.append({"action": "search_policy", "args": {"query": question}})
    elif soft and not data_hint and not name:
        steps.append({"action": "search_policy", "args": {"query": question}})

    if name and (strong or soft):
        steps.append({"action": "get_loan_detail", "args": {"name": name}})
    elif stats_likely and (not steps or data_hint):
        steps.append({"action": "query_statistics", "args": {"question": question}})

    if not steps:
        if stats_likely:
            steps.append({"action": "query_statistics", "args": {"question": question}})
        elif name:
            steps.append({"action": "get_loan_detail", "args": {"name": name}})
    return steps[:config.AGENT_MAX_STEPS]


def llm_plan(question: str) -> Optional[List[Dict[str, Any]]]:
    if not llm_client.enabled:
        return None
    tools_desc = "\n".join(
        f"- {key}：{value['desc']}；参数示例 {value['args']}" for key, value in TOOLS.items()
    )
    try:
        data = llm_client.chat_json([
            {"role": "system", "content": PLAN_PROMPT.format(
                tools=tools_desc, max_steps=config.AGENT_MAX_STEPS)},
            {"role": "user", "content": f"用户问题：{question}"},
        ], temperature=0.0)
    except LLMUnavailable:
        return None

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        return None
    steps: List[Dict[str, Any]] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip()
        if action not in TOOLS:
            continue
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        steps.append({"action": action, "args": args})
    return steps[:config.AGENT_MAX_STEPS]


# ---------------------------------------------------------------------------
# 合成
# ---------------------------------------------------------------------------
def compose(question: str, observations: List[Dict[str, Any]]) -> Dict[str, str]:
    if not observations:
        return {"answer": assistant.fallback_answer(question, "other", {}, {}), "answer_source": "规则模板"}

    if llm_client.enabled:
        payload = [
            {"tool": obs["action"], "ok": obs["ok"], "result": obs["observation"]}
            for obs in observations
        ]
        try:
            text = llm_client.chat_text([
                {"role": "system", "content": COMPOSE_PROMPT},
                {"role": "user", "content":
                    f"用户问题：{question}\n\n工具执行结果（JSON）：\n"
                    f"{json.dumps(payload, ensure_ascii=False, default=str)[:6000]}"},
            ], temperature=0.3)
            return {"answer": text.strip(), "answer_source": "LLM"}
        except LLMUnavailable:
            pass

    parts: List[str] = []
    for obs in observations:
        result = obs["observation"]
        if obs["action"] == "search_policy" and result.get("summary"):
            parts.append("【制度依据】\n" + result["summary"])
        elif obs["action"] == "get_loan_detail" and result.get("summary"):
            parts.append("【台账明细】\n" + result["summary"])
        elif obs["action"] == "query_statistics" and result.get("summary"):
            parts.append("【统计结果】\n" + result["summary"])
    return {"answer": "\n\n".join(parts) or "未能获得有效结果，请换一种问法。", "answer_source": "规则模板"}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def run(question: str, session_id: str = "", user_id: Optional[int] = None) -> Dict[str, Any]:
    started = time.time()
    question = (question or "").strip()
    if not question:
        return {"answer": "请输入您想咨询的问题。", "intent": "other",
                "intent_name": ROUTE_LABELS["other"], "route": "other",
                "data": {"columns": [], "rows": []}, "evidence": [], "trace": [],
                "method": "规则规划", "elapsed_ms": 0}

    steps = llm_plan(question)
    plan_source = "LLM 规划"
    if steps is None:
        steps = rule_plan(question)
        plan_source = "规则规划"

    trace: List[Dict[str, Any]] = []
    observations: List[Dict[str, Any]] = []
    for number, step in enumerate(steps, start=1):
        action = step["action"]
        args = step.get("args") or {}
        step_started = time.time()
        try:
            observation = EXECUTORS[action](args, question)
        except Exception as exc:  # 单个工具失败不影响后续步骤
            observation = {"ok": False, "summary": f"工具执行异常：{exc}"}
        elapsed = int((time.time() - step_started) * 1000)
        observations.append({"action": action, "ok": observation.get("ok", False),
                             "observation": observation})
        trace.append({
            "step": number,
            "action": action,
            "action_label": {
                "query_statistics": "查询统计数据",
                "get_loan_detail": "查询人员台账",
                "search_policy": "检索制度条款",
            }.get(action, action),
            "args": args,
            "ok": observation.get("ok", False),
            "brief": (observation.get("summary") or "")[:160],
            "elapsed_ms": elapsed,
        })

    if not steps:
        composed = {"answer": assistant.fallback_answer(question, "other", {}, {}),
                    "answer_source": "规则模板"}
    else:
        composed = compose(question, observations)

    # 汇总结果
    stats_obs = next((o["observation"] for o in observations if o["action"] == "query_statistics"), None)
    policy_obs = next((o["observation"] for o in observations if o["action"] == "search_policy"), None)
    detail_obs = next((o["observation"] for o in observations if o["action"] == "get_loan_detail"), None)

    if not steps:
        route = "other"
    elif policy_obs and (stats_obs or detail_obs):
        route = "mixed"
    elif policy_obs:
        route = "policy"
    else:
        route = "statistics"

    intent = "other"
    intent_name = ROUTE_LABELS["other"]
    if route == "statistics" and stats_obs and stats_obs.get("intent"):
        intent = stats_obs["intent"]
        intent_name = stats_obs.get("intent_name") or intent
    elif route in ("policy", "mixed"):
        intent = "policy_qa"
        intent_name = ROUTE_LABELS["mixed"] if route == "mixed" else ROUTE_LABELS["policy"]

    elapsed = int((time.time() - started) * 1000)
    result = {
        "answer": composed["answer"],
        "answer_source": composed["answer_source"],
        "intent": intent,
        "intent_name": intent_name,
        "route": route,
        "route_name": ROUTE_LABELS.get(route, route),
        "is_statistics_query": route in ("statistics", "mixed"),
        "method": plan_source,
        "intent_method": (stats_obs or {}).get("method"),
        "confidence": (stats_obs or {}).get("confidence"),
        "slots": (stats_obs or {}).get("slots") or {},
        "title": (stats_obs or {}).get("title") or ((policy_obs or {}).get("retrieval") or {}).get("method", ""),
        "sql": (stats_obs or {}).get("sql") or "",
        "data": (stats_obs or {}).get("data") or {"columns": [], "rows": []},
        "summary": "；".join(o["observation"].get("summary", "") for o in observations
                             if o["observation"].get("ok"))[:800],
        "evidence": (policy_obs or {}).get("evidence") or [],
        "retrieval": (policy_obs or {}).get("retrieval") or {},
        "detail": detail_obs or None,
        "trace": trace,
        "llm": llm_client.status(),
        "elapsed_ms": elapsed,
    }
    _log(question, session_id, user_id, result)
    return result


def _log(question: str, session_id: str, user_id: Optional[int], result: Dict[str, Any]) -> None:
    assistant.log_chat(session_id, user_id, question, result)
    try:
        from datetime import datetime

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = [(
            session_id or "", question[:500], item["step"], item["action"],
            json.dumps(item["args"], ensure_ascii=False)[:300],
            (item["brief"] or "")[:300], item["elapsed_ms"], now,
        ) for item in result.get("trace") or []]
        if rows:
            db.get_connection().executemany(
                """INSERT INTO agent_step_log
                   (session_id, question, step_no, action, args, observation, elapsed_ms, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                rows,
            )
    except Exception:
        pass


def tools_info() -> List[Dict[str, str]]:
    return [{"action": key, **value} for key, value in TOOLS.items()]
