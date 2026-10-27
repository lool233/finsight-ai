# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 端到端接口冒烟测试
=====================================================================
运行（自动使用 SQLite 演示库，不影响 MySQL 配置）：
    python tests/smoke_test.py            # 需先执行 python init_db.py sqlite
    python -m pytest tests/smoke_test.py  # 亦兼容 pytest
覆盖：登录鉴权、借资增删改查、还款登记、逾期扫描、LLM 催还批处理、
      AI 助手自然语言统计查询、统计报表、系统状态。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# 冒烟测试固定使用 SQLite 演示库，避免误改生产数据
os.environ["DB_DIALECT"] = "sqlite"
os.environ["SQLITE_PATH"] = str(BASE_DIR / "data" / "loan_system.db")
os.environ["SMS_PROVIDER"] = os.environ.get("SMS_PROVIDER", "mock")

from app import create_app  # noqa: E402

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
    app = create_app()
    client = app.test_client()

    print("\n[1] 认证与鉴权")
    resp = client.get("/api/loans")
    check("未登录访问受保护接口返回 401", resp.status_code == 401, str(resp.status_code))
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    check("错误密码登录被拒绝", resp.status_code == 200 and not resp.get_json()["success"])
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    check("管理员登录成功", resp.get_json()["success"], str(resp.get_json()))
    resp = client.get("/api/auth/profile")
    check("获取当前登录用户", resp.get_json()["data"]["username"] == "admin")

    print("\n[2] 数据看板与统计")
    data = client.get("/api/stats/dashboard").get_json()["data"]
    check("看板总览数据可用", data["overview"]["loan_count"] > 0,
          str(data["overview"]))
    check("看板包含部门/类型/趋势统计", all(k in data for k in ("dept", "type", "trend", "aging", "top")))
    overview = data["overview"]
    print(f"       借资总额={overview['total_amount']} 未还={overview['unpaid_amount']} "
          f"逾期笔数={overview['overdue_count']} 逾期金额={overview['overdue_amount']}")

    print("\n[3] 销售人员增删改查")
    resp = client.post("/api/sales", json={
        "emp_no": "XS9999001", "name": "测试销售", "phone": "13900001234",
        "dept": "测试部门", "region": "测试区域", "job_title": "销售代表",
        "entry_date": "2025-01-01", "status": "在职"
    })
    check("新增销售人员", resp.get_json()["success"], str(resp.get_json()))
    sales_id = resp.get_json()["data"]["id"]
    resp = client.post("/api/sales", json={
        "emp_no": "XS9999001", "name": "重复工号", "phone": "13900001234", "dept": "测试部门"
    })
    check("重复工号被拒绝", not resp.get_json()["success"])
    resp = client.put(f"/api/sales/{sales_id}", json={"name": "测试销售改名", "phone": "13900005678"})
    check("修改销售人员", resp.get_json()["data"]["name"] == "测试销售改名")
    resp = client.post("/api/sales", json={
        "emp_no": "XS9999002", "name": "手机号错误", "phone": "123", "dept": "测试部门"
    })
    check("手机号格式校验生效", not resp.get_json()["success"])

    print("\n[4] 借资信息增删改查")
    resp = client.post("/api/loans", json={
        "sales_id": sales_id, "amount": 12000.00, "loan_date": "2025-01-01",
        "loan_type": "差旅借款", "purpose": "冒烟测试借资", "remark": "自动化测试"
    })
    check("新增借资记录", resp.get_json()["success"], str(resp.get_json()))
    loan = resp.get_json()["data"]
    loan_id = loan["id"]
    check("自动生成借资单号", bool(loan["loan_no"]))
    check("约定还款日按借资日+3个月计算", loan["repay_deadline"] == "2025-04-01",
          loan["repay_deadline"])
    check("逾期天数计算正确", loan["overdue_days"] > 0 and loan["is_overdue"],
          f"{loan['overdue_days']} / {loan['is_overdue']}")

    resp = client.put(f"/api/loans/{loan_id}", json={"amount": 15000.00, "remark": "修改金额"})
    check("修改借资记录", float(resp.get_json()["data"]["amount"]) == 15000.00)

    resp = client.get("/api/loans", query_string={"keyword": "测试销售改名"})
    check("按关键字查询借资", resp.get_json()["data"]["total"] >= 1)

    print("\n[5] 还款登记")
    resp = client.post(f"/api/loans/{loan_id}/repayments",
                       json={"repay_amount": 5000, "repay_date": "2025-02-01",
                             "repay_method": "银行转账"})
    check("登记部分还款", resp.get_json()["success"], str(resp.get_json()))
    row = resp.get_json()["data"]
    check("还款后状态为部分还款", row["status"] == "部分还款", row["status"])
    check("已还金额正确", float(row["repaid_amount"]) == 5000.0)
    resp = client.put(f"/api/loans/{loan_id}", json={"amount": 1.00})
    check("借资金额小于已还金额被拒绝", not resp.get_json()["success"],
          str(resp.get_json()))
    resp = client.post(f"/api/loans/{loan_id}/repayments", json={"repay_amount": 999999})
    check("超额还款被拒绝", not resp.get_json()["success"])
    resp = client.post(f"/api/loans/{loan_id}/repayments", json={"repay_amount": 10000})
    check("还清后状态为已还清", resp.get_json()["data"]["status"] == "已还清")

    print("\n[6] 逾期扫描与 LLM 催还")
    resp = client.get("/api/collections/overdue")
    overdue = resp.get_json()["data"]
    check("扫描到逾期借资", overdue["total"] > 0, str(overdue["total"]))
    for item in overdue["items"][:5]:
        print(f"       · {item['sales_name']} {item['loan_no']} 逾期 {item['overdue_days']} 天 "
              f"{item['collection_level']} 未还 {item['unpaid_amount']}")
    resp = client.get("/api/collections/status")
    check("获取 LLM / 短信配置状态", resp.get_json()["success"])

    sample = overdue["items"][0]
    resp = client.post(f"/api/collections/preview/{sample['loan_id']}")
    preview = resp.get_json()["data"]
    check("单笔催还文案试生成", len(preview["content"]) > 10, str(preview)[:200])
    print(f"       催还短信：{preview['content'][:90]}…")
    print(f"       内容来源：{preview['generated_by']}")

    resp = client.post("/api/collections/run", json={"force": True})
    result = resp.get_json()["data"]
    check("催还批处理执行成功", result["created"] > 0, str(result)[:300])
    check("生成催还记录并记录发送状态",
          all(it["send_status"] for it in result["items"]))
    print(f"       批次={result['batch_no']} 扫描={result['scanned']} 生成={result['created']} "
          f"下发成功={result['sent_ok']} 跳过={result['skipped']}")
    resp = client.post("/api/collections/run", json={})
    check("重复催还自动去重", resp.get_json()["data"]["skipped"] > 0,
          str(resp.get_json()["data"]["skipped"]))
    resp = client.get("/api/collections")
    check("查询催还记录列表", resp.get_json()["data"]["total"] > 0)
    coll_id = resp.get_json()["data"]["items"][0]["id"]
    resp = client.post(f"/api/collections/{coll_id}/resend")
    check("催还短信重发", resp.get_json()["success"], str(resp.get_json()))

    print("\n[7] AI 智能助手（自然语言查询统计）")
    questions = [
        "目前公司借资总体情况怎么样？",
        "各部门的借资和未还金额分别是多少？",
        "有哪些人借资超过3个月还没有还？",
        "未还金额最多的前5名销售人员是谁？",
        "陈志强的借资明细和还款情况如何？",
        "最近6个月的借资趋势如何？",
        "逾期账龄分布情况怎样？",
        "你好，你会做什么？",
    ]
    for q in questions:
        resp = client.post("/api/assistant/ask", json={"question": q})
        payload = resp.get_json()
        ok_flag = payload["success"]
        data = payload.get("data") or {}
        check(f"提问「{q[:14]}…」→ 意图={data.get('intent_name')}",
              ok_flag and bool(data.get("answer")), str(payload)[:200])
        print(f"       答复（{data.get('answer_source')}）：{(data.get('answer') or '')[:80]}…")
    resp = client.post("/api/assistant/ask", json={"question": ""})
    check("空问题被拦截", not resp.get_json()["success"])

    resp = client.post("/api/assistant/ask", json={"question": "今天天气怎么样？"})
    off_topic = resp.get_json()["data"]
    check("非借资类问题被判定为非查询统计并给出引导",
          off_topic["intent"] == "other" and not off_topic["is_statistics_query"],
          f"{off_topic['intent']} / {off_topic['is_statistics_query']}")

    print("\n[8] 统计报表与系统状态")
    for url in ("/api/stats/overview", "/api/stats/dept", "/api/stats/type",
                "/api/stats/trend", "/api/stats/aging", "/api/stats/top"):
        check(f"接口 {url} 正常", client.get(url).get_json()["success"])
    info = client.get("/api/stats/system").get_json()["data"]
    check("系统状态包含数据库信息", "connected" in info["database"])
    check("系统状态包含 LLM 信息", "model" in info["llm"])
    check("操作日志已记录", len(info["logs"]) > 0)

    print("\n[9] 清理测试数据")
    resp = client.delete(f"/api/loans/{loan_id}")
    check("删除借资记录（逻辑删除）", resp.get_json()["success"])
    resp = client.delete(f"/api/sales/{sales_id}")
    check("删除销售人员（存在借资记录时被拒绝，保留台账）",
          not resp.get_json()["success"], str(resp.get_json()))
    print("       （逻辑删除的借资记录仍关联该销售人员，属预期的数据保护行为）")

    print("\n[10] 权限校验（销售人员角色只读）")
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "sales", "password": "sales123"})
    resp = client.post("/api/loans", json={"sales_id": 1, "amount": 100, "loan_date": "2025-01-01"})
    check("只读角色不能新增借资", resp.status_code == 403, str(resp.status_code))
    resp = client.get("/api/loans")
    check("只读角色可以查询借资", resp.get_json()["success"])

    print("\n" + "=" * 64)
    print(f"  冒烟测试完成：通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 64)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
