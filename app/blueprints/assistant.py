# -*- coding: utf-8 -*-
"""
AI 智能助手接口（NL2SQL + RAG + 多工具 Agent）
=====================================================================
处理链路：
    用户提问 → Agent 规划工具（统计查询 / 制度检索 / 人员台账）
    → 逐个执行并记录执行轨迹 → 合成答复（数据结论 + 制度依据 + 出处）
"""
from __future__ import annotations

from flask import Blueprint, request, session

from app.llm import llm_client
from app.services import agent_service, assistant_service as svc
from app.services import knowledge_service, rag_service
from app.utils import BizError, current_user, login_required, ok, payload, require
from config import config

bp = Blueprint("assistant", __name__)


@bp.get("/samples")
@login_required
def samples():
    return ok({
        "samples": svc.SAMPLES,
        "policy_samples": [
            "借资逾期多久算三级催收？",
            "核销需要哪些票据？",
            "借资单号怎么生成？",
            "许曼逾期229天，按制度该怎么处理？",
        ],
        "intents": svc.INTENT_LABELS,
        "routes": agent_service.ROUTE_LABELS,
        "tools": agent_service.tools_info(),
        "llm": llm_client.status(),
        "knowledge": {
            "docs": knowledge_service.list_docs(),
            "chunks": knowledge_service.count_chunks(),
            "top_k": config.RAG_TOP_K,
            "rerank": config.RAG_RERANK,
        },
    })


@bp.post("/ask")
@login_required
def ask():
    data = payload()
    require(data, "question")
    question = str(data["question"]).strip()
    if not question:
        raise BizError("请输入您想咨询的问题")
    if len(question) > 300:
        raise BizError("问题过长，请控制在 300 字以内")

    user = current_user() or {}
    session_id = session.get("sid")
    if not session_id:
        import uuid

        session_id = uuid.uuid4().hex
        session["sid"] = session_id

    result = agent_service.run(question, session_id=session_id, user_id=user.get("id"))
    return ok(result)


@bp.get("/history")
@login_required
def history():
    session_id = session.get("sid", "")
    return ok(svc.history(session_id, limit=10))


@bp.get("/knowledge")
@login_required
def knowledge():
    """知识库文档清单；带 doc_code 时返回该文档的知识块预览。"""
    doc_code = request.args.get("doc_code", "")
    docs = knowledge_service.list_docs()
    chunks = []
    if doc_code:
        chunks = [c for c in knowledge_service.load_chunks() if c.get("doc_code") == doc_code][:50]
    return ok({
        "docs": docs,
        "chunks": chunks,
        "chunks_total": knowledge_service.count_chunks(),
        "retrieval": {"method": "BM25 + TF-IDF 混合检索", "top_k": config.RAG_TOP_K,
                      "rerank": config.RAG_RERANK},
    })
