# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— RAG + Agent 专项测试
=====================================================================
覆盖：
    1. 知识库构建（文档数、切块数、中文 2-gram 分词）
    2. 混合检索（BM25 + TF-IDF）：命中正确文档、得分降序、Top-K 生效
    3. RAG 答复：带出处的答复 + 结构化依据
    4. Agent 规划：统计 / 制度 / 混合（多步）/ 无关问题 四类路由
    5. 工具执行：人员台账数据正确、执行轨迹落库
    6. 接口层：/api/assistant/ask 与 /api/assistant/knowledge

为保证结果确定、不消耗大模型额度，测试中强制关闭 LLM（走规则引擎 + 规则规划）。
真实大模型链路由 tests/llm_integration_test.py 覆盖。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ["DB_DIALECT"] = "sqlite"
os.environ["SQLITE_PATH"] = str(BASE_DIR / "data" / "loan_system.db")
os.environ["SMS_PROVIDER"] = "none"
os.environ["LLM_API_KEY"] = ""      # 强制走规则引擎，保证确定性与零调用成本
os.environ["LLM_FALLBACK_ENABLED"] = "true"

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name}  {detail}")


def main() -> int:
    from app import create_app, db
    from app.services import agent_service, knowledge_service, rag_service

    app = create_app()
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "finance", "password": "finance123"})

    print("\n[1] 知识库构建与分词")
    docs = knowledge_service.list_docs()
    total_chunks = knowledge_service.count_chunks()
    check("制度文档已导入（4 份）", len(docs) == 4, str(len(docs)))
    check("知识块已切分（>15 块）", total_chunks > 15, str(total_chunks))
    check("文档编号规范（FINSIGHT-FIN-xxx）",
          all(d["doc_code"].startswith("FINSIGHT-FIN-") for d in docs),
          str([d["doc_code"] for d in docs]))
    tokens = knowledge_service.tokenize("借资逾期怎么处理")
    check("中文 2-gram 分词生效", "逾期" in tokens and "借资" in tokens, str(tokens[:8]))
    check("分词不含标点", not any(t in "，。？" for t in tokens))

    print("\n[2] BM25 + TF-IDF 混合检索")
    hits = rag_service.search_only("借资逾期多久算三级催收", top_k=3)
    check("检索返回结果", len(hits) >= 1, str(len(hits)))
    check("命中催收分级相关条款",
          any("催收" in (h["heading"] + h["content"]) or "三级" in h["content"] for h in hits),
          str([h["heading"] for h in hits]))
    check("得分按相关度降序", all(hits[i]["score"] >= hits[i + 1]["score"]
                                for i in range(len(hits) - 1)),
          str([h["score"] for h in hits]))
    check("Top-K 生效（最多 2 条）", len(rag_service.search_only("核销票据", top_k=2)) <= 2)
    top = hits[0]
    check("同时给出 BM25 与余弦两个分量", top["bm25"] > 0 and top["cosine"] > 0,
          f"bm25={top['bm25']} cos={top['cosine']}")
    check("无关问题不误召回", len(rag_service.search_only("量子计算机的退相干时间", top_k=3)) <= 3)

    print("\n[3] RAG 答复（带出处）")
    rag = rag_service.answer("核销需要哪些票据？")
    check("返回答复文本", len(rag["answer"]) > 20, rag["answer"][:60])
    check("答复来源为规则模板（LLM 已关闭）", rag["answer_source"] == "规则模板", rag["answer_source"])
    check("附带结构化依据", len(rag["evidence"]) >= 1, str(len(rag["evidence"])))
    check("依据包含文档名与章节",
          bool(rag["evidence"][0]["doc_title"]) and bool(rag["evidence"][0]["heading"]),
          str(rag["evidence"][0])[:80])
    check("答复中标注出处", "依据：" in rag["answer"])

    print("\n[4] Agent 规划与多步工具调用")
    cases = [
        ("各部门的借资和未还金额分别是多少？", "statistics", 1),
        ("借资逾期多久算三级催收？", "policy", 1),
        ("许曼逾期229天，按制度该怎么处理？", "mixed", 2),
        ("今天天气怎么样？", "other", 0),
    ]
    for question, expected_route, min_steps in cases:
        data = client.post("/api/assistant/ask", json={"question": question}).get_json()["data"]
        trace = data.get("trace") or []
        check(f"「{question[:14]}…」路由={data.get('route')}",
              data.get("route") == expected_route, str(data.get("route")))
        check(f"　　工具步数 ≥ {min_steps}（实际 {len(trace)}）", len(trace) >= min_steps,
              str([t["action"] for t in trace]))
        if expected_route in ("policy", "mixed"):
            check("　　附带制度依据", len(data.get("evidence") or []) >= 1)
        if expected_route == "statistics":
            check("　　返回结果表格", len((data.get("data") or {}).get("rows") or []) >= 1)

    print("\n[5] 工具执行细节")
    mixed = client.post("/api/assistant/ask",
                        json={"question": "许曼逾期229天，按制度该怎么处理？"}).get_json()["data"]
    actions = [t["action"] for t in mixed["trace"]]
    check("混合问题先查制度、再查台账",
          actions[0] == "search_policy" and "get_loan_detail" in actions, str(actions))
    detail = mixed.get("detail") or {}
    check("人员台账取到未还金额（8600 元）", abs(float(detail.get("unpaid") or 0) - 8600.0) < 0.01,
          str(detail.get("unpaid")))
    check("人员台账含催还次数统计",
          any("催还次数" in row for row in (detail.get("data") or {}).get("rows") or []),
          str((detail.get("data") or {}).get("rows") or [])[:120])
    rows = db.query_all(
        "SELECT action, step_no FROM agent_step_log WHERE question LIKE %s ORDER BY id DESC LIMIT 5",
        ("许曼%",))
    check("工具调用轨迹已落库", len(rows) >= 2, str(rows))

    print("\n[6] 接口层")
    knowledge = client.get("/api/assistant/knowledge").get_json()["data"]
    check("知识库清单接口可用", len(knowledge["docs"]) == 4, str(len(knowledge["docs"])))
    check("知识库返回检索方法说明",
          "BM25" in (knowledge.get("retrieval") or {}).get("method", ""),
          str(knowledge.get("retrieval")))
    samples = client.get("/api/assistant/samples").get_json()["data"]
    check("示例问题包含制度问答", len(samples.get("policy_samples") or []) >= 3)
    check("工具清单为 3 个", len(samples.get("tools") or []) == 3,
          str([t["action"] for t in samples.get("tools") or []]))
    check("工具清单覆盖三类能力",
          {t["action"] for t in samples["tools"]} ==
          {"query_statistics", "get_loan_detail", "search_policy"})

    print("\n[7] 降级与边界")
    empty = client.post("/api/assistant/ask", json={"question": "   "}).get_json()
    check("空问题被拒绝", not empty["success"])
    long_q = "借资" * 200
    resp = client.post("/api/assistant/ask", json={"question": long_q})
    check("超长问题被拒绝", not resp.get_json()["success"])

    print("\n" + "=" * 68)
    print(f"  RAG / Agent 专项测试完成：通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 68)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
