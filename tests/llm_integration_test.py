# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— LLM 真实调用链路集成测试
=====================================================================
做法：在本地启动一个模拟的 OpenAI 兼容服务（/v1/chat/completions），
      校验真实的大模型调用代码路径（请求报文、结构化输出、响应解析、
      提示词内容），并覆盖 Agent 规划、RAG 重排、答复合成三个环节。

运行：
    python tests/llm_integration_test.py

覆盖：
    1. 催还短信由 LLM 生成（generated_by=LLM，记录模型名）
    2. Agent 由 LLM 规划工具，统计工具内部的意图识别由 LLM 完成
    3. RAG 环节的 LLM 重排与带出处答复
    4. 混合问题两步工具调用
    5. 大模型不可用时全链路自动降级（催还短信、统计问答、RAG）
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

MOCK_PORT = 5099
CALLS = []

os.environ["DB_DIALECT"] = "sqlite"
os.environ["SQLITE_PATH"] = str(BASE_DIR / "data" / "loan_system.db")
os.environ["SMS_PROVIDER"] = "mock"
os.environ["LLM_BASE_URL"] = f"http://127.0.0.1:{MOCK_PORT}/v1"
os.environ["LLM_API_KEY"] = "test-api-key"
os.environ["LLM_MODEL"] = "mock-llm-model"


# ---------------------------------------------------------------------------
# 模拟的 OpenAI 兼容大模型服务（按 system 提示词识别调用场景）
# ---------------------------------------------------------------------------
class MockLLMHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        system, user = "", ""
        for message in payload.get("messages", []):
            if message.get("role") == "system":
                system = message.get("content", "")
            elif message.get("role") == "user":
                user = message.get("content", "")

        CALLS.append({
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "model": payload.get("model"),
            "response_format": payload.get("response_format"),
            "temperature": payload.get("temperature"),
            "system_prompt": system,
            "user_prompt": user,
        })

        if "任务规划器" in system:                      # Agent 规划
            if "天气" in user:
                data = {"steps": [], "reason": "与借资业务无关"}
            elif "许曼" in user:
                data = {"steps": [
                    {"action": "search_policy", "args": {"query": "逾期催收措施"}},
                    {"action": "get_loan_detail", "args": {"name": "许曼"}},
                ], "reason": "先查制度再查台账"}
            elif any(word in user for word in ("制度", "规定", "多久", "催收", "核销", "票据", "办法")):
                data = {"steps": [{"action": "search_policy", "args": {"query": user}}],
                        "reason": "制度规定类问题"}
            else:
                data = {"steps": [{"action": "query_statistics", "args": {"question": user}}],
                        "reason": "统计类问题"}
            content = json.dumps(data, ensure_ascii=False)
        elif "意图识别模块" in system:                  # 统计工具内部意图识别
            if "陈志强" in user:
                data = {"intent": "stat_aging", "slots": {}, "confidence": 0.93,
                        "reason": "模拟大模型改判为账龄分布"}
            else:
                data = {"intent": "stat_overdue", "slots": {"months": 3, "top": 5},
                        "confidence": 0.91, "reason": "模拟大模型判定为逾期统计"}
            content = json.dumps(data, ensure_ascii=False)
        elif "检索结果重排器" in system:                # RAG 重排
            content = json.dumps({"order": [2, 1, 3, 4]}, ensure_ascii=False)
        elif "催收专员" in system:                      # 催还短信
            content = json.dumps({
                "analysis": "模拟大模型风险分析：该笔借资逾期时间较长，回收风险偏高。",
                "sms_content": "【财务部】尊敬的同事您好，系统检测到您的借资已逾期，"
                               "请于 3 个工作日内到财务部办理还款，如有疑问请联系财务部 020-88886666。",
                "suggestion": "模拟建议：电话跟进并暂停新增借资。",
            }, ensure_ascii=False)
        else:                                           # 答复合成 / RAG 生成
            content = "模拟大模型答复：根据检索与统计结果，建议优先跟进逾期借资并核对制度条款。"

        body = json.dumps({
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "model": payload.get("model"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }, ensure_ascii=False).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_mock_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockLLMHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


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


def snapshot() -> tuple:
    json_calls = len([c for c in CALLS if c["response_format"]])
    return len(CALLS), json_calls


def main() -> int:
    server = start_mock_server()
    print(f"\n模拟 OpenAI 兼容服务已启动：http://127.0.0.1:{MOCK_PORT}/v1")

    from app import create_app
    from app.llm import llm_client

    app = create_app()
    client = app.test_client()
    check("登录成功", client.post("/api/auth/login",
                                 json={"username": "admin", "password": "admin123"}
                                 ).get_json()["success"])
    check("LLM 客户端识别为已启用", llm_client.enabled)

    print("\n[1] 催还短信由 LLM 生成")
    data = client.post("/api/collections/run", json={"force": True}).get_json()["data"]
    check("催还批处理生成记录", data["created"] > 0, str(data)[:160])
    item = data["items"][0]
    check("内容来源标记为 LLM", item["generated_by"] == "LLM", item["generated_by"])
    check("记录使用的模型名", item["llm_model"] == "mock-llm-model", item["llm_model"])
    check("短信内容来自模型返回", "【财务部】" in item["content"], item["content"][:50])
    total0, json0 = snapshot()
    check("每笔逾期借资各调用一次大模型", total0 == data["created"],
          f"{total0} vs {data['created']}")

    print("\n[2] Agent 由 LLM 规划，统计工具内部由 LLM 识别意图")
    before = snapshot()
    stats = client.post("/api/assistant/ask",
                        json={"question": "有哪些人借资超过3个月还没有还？"}
                        ).get_json()["data"]
    after = snapshot()
    check("规划方式为 LLM 规划", stats["method"] == "LLM 规划", str(stats["method"]))
    check("统计工具内部意图识别由 LLM 完成", stats["intent_method"] == "LLM",
          str(stats["intent_method"]))
    check("采用大模型返回的意图", stats["intent"] == "stat_overdue", str(stats["intent"]))
    check("采用大模型抽取的条件", int((stats["slots"] or {}).get("months") or 0) == 3,
          str(stats["slots"]))
    check("答复由 LLM 合成", stats["answer_source"] == "LLM", str(stats["answer_source"]))
    check("统计问题共 3 次调用（规划 + 意图 + 合成）",
          after[0] - before[0] == 3, str(after[0] - before[0]))
    check("其中 2 次为 json_object（规划 + 意图）",
          after[1] - before[1] == 2, str(after[1] - before[1]))
    check("Agent 执行了 1 步", len(stats["trace"]) == 1, str([t["action"] for t in stats["trace"]]))

    print("\n[3] RAG 环节：LLM 重排 + 带出处答复")
    before = snapshot()
    policy = client.post("/api/assistant/ask",
                         json={"question": "借资逾期多久算三级催收？"}
                         ).get_json()["data"]
    after = snapshot()
    check("路由为制度问答", policy["route"] == "policy", str(policy["route"]))
    check("返回制度依据", len(policy["evidence"]) >= 2, str(len(policy["evidence"])))
    check("制度答案由 LLM 生成", policy["answer_source"] == "LLM")
    check("制度问题共 4 次调用（规划 + 重排 + 检索答复 + 合成）",
          after[0] - before[0] == 4, str(after[0] - before[0]))
    check("其中 2 次为 json_object（规划 + 重排）",
          after[1] - before[1] == 2, str(after[1] - before[1]))

    print("\n[4] 混合问题：两步工具调用")
    mixed = client.post("/api/assistant/ask",
                        json={"question": "许曼逾期229天，按制度该怎么处理？"}
                        ).get_json()["data"]
    actions = [t["action"] for t in mixed["trace"]]
    check("路由为综合问答", mixed["route"] == "mixed", str(mixed["route"]))
    check("两步工具调用（制度 + 台账）",
          actions == ["search_policy", "get_loan_detail"], str(actions))
    check("台账数据带入答复上下文",
          abs(float((mixed.get("detail") or {}).get("unpaid") or 0) - 8600.0) < 0.01,
          str((mixed.get("detail") or {}).get("unpaid")))

    print("\n[5] 校验发出的 HTTP 报文是否符合 OpenAI 兼容协议")
    check("请求路径为 /v1/chat/completions",
          all(c["path"] == "/v1/chat/completions" for c in CALLS))
    check("携带 Bearer 鉴权头", all(c["auth"] == "Bearer test-api-key" for c in CALLS))
    check("请求体使用配置的模型", all(c["model"] == "mock-llm-model" for c in CALLS))
    prompts = " ".join(c["system_prompt"] for c in CALLS)
    for role, label in (("催收专员", "催还"), ("任务规划器", "Agent 规划"),
                        ("意图识别模块", "意图识别"), ("检索结果重排器", "RAG 重排")):
        check(f"包含{label}提示词", role in prompts)
    check("催还请求携带借款人、逾期天数等业务信息",
          any("逾期天数" in c["user_prompt"] and "约定还款日" in c["user_prompt"] for c in CALLS))
    check("答复合成请求携带工具执行结果",
          any("工具执行结果" in c["user_prompt"] for c in CALLS))

    print("\n[6] 大模型不可用时的全链路降级")
    original = llm_client.base_url
    llm_client.base_url = "http://127.0.0.1:1/v1"     # 指向不可达端口
    data = client.post("/api/collections/run", json={"force": True}).get_json()["data"]
    check("催还短信降级为规则模板", data["items"][0]["generated_by"] == "规则模板",
          data["items"][0]["generated_by"])
    degraded = client.post("/api/assistant/ask", json={"question": "公司借资总额是多少？"}
                           ).get_json()["data"]
    check("统计问答降级为规则规划", degraded["method"] == "规则规划", str(degraded["method"]))
    check("降级后仍返回答复", len(degraded["answer"]) > 10)
    rag = client.post("/api/assistant/ask", json={"question": "核销需要哪些票据？"}
                      ).get_json()["data"]
    check("RAG 降级为规则模板", rag["answer_source"] == "规则模板", str(rag["answer_source"]))
    check("降级后仍返回制度依据", len(rag["evidence"]) >= 1, str(len(rag["evidence"])))
    llm_client.base_url = original

    server.shutdown()
    print("\n" + "=" * 68)
    print(f"  LLM 链路集成测试完成：通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 68)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
