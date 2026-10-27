# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 数据库初始化脚本
=====================================================================
用法：
    python init_db.py              # 按 .env 中的 DB_DIALECT 初始化数据库
    python init_db.py sqlite       # 强制初始化本地 SQLite 演示库（零依赖）
    python init_db.py mysql        # 提示使用 MySQL 官方 SQL 脚本

说明：
    - 正式环境（课程设计验收）请按《数据库SQL脚本/01_schema.sql》《02_init_data.sql》
      在 MySQL 8.0 中建库建表并导入数据。
    - 未安装 MySQL 时，可用 DB_DIALECT=sqlite 直接初始化本地演示库并完整体验系统功能。
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path

# 允许通过命令行参数强制指定方言（优先于 .env 配置）
if len(sys.argv) > 1 and sys.argv[1].lower() in ("sqlite", "mysql"):
    os.environ["DB_DIALECT"] = sys.argv[1].lower()

from config import config  # noqa: E402
from app import db  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 演示数据（与《数据库SQL脚本/02_init_data.sql》保持一致，日期按“今天”动态推算）
# ---------------------------------------------------------------------------
USERS = [
    ("admin", "3608a731580aba8d742d81d2ee770b23ef9e913113662fd1cff595cc86248a95",
     "系统管理员", "admin", "信息中心", "13900000001"),
    ("finance", "36d6321bd64455f5ab2cd5037981df3c9712211fa55eb24bf45ea779a5b45fc0",
     "孙丽华", "finance", "财务部", "13900000002"),
    ("sales", "e1b5054ff849c5b8bca0bcce07800ecc76be2368482b086db43cfe01e43f3077",
     "陈志强", "sales", "华南销售一部", "13800001111"),
]

SALES = [
    ("XS2021001", "陈志强", "男", "13800001111", "华南销售一部", "广州", "销售代表", "2021-03-01", "在职", "大客户跟进"),
    ("XS2021002", "林晓雯", "女", "13800002222", "华南销售一部", "深圳", "高级销售", "2021-07-15", "在职", "重点客户维护"),
    ("XS2022003", "王浩然", "男", "13800003333", "华南销售二部", "东莞", "销售代表", "2022-02-20", "在职", None),
    ("XS2022004", "赵敏", "女", "13800004444", "华东销售部", "上海", "区域经理", "2022-05-10", "在职", "华东区域负责人"),
    ("XS2020005", "刘海涛", "男", "13800005555", "华东销售部", "杭州", "销售代表", "2020-09-01", "在职", None),
    ("XS2023006", "周雅琴", "女", "13800006666", "华北大区", "北京", "销售代表", "2023-03-06", "在职", None),
    ("XS2019007", "吴建国", "男", "13800007777", "西南销售部", "成都", "销售代表", "2019-11-11", "在职", "借资次数较多"),
    ("XS2023008", "郑雪", "女", "13800008888", "华北大区", "天津", "销售代表", "2023-08-01", "在职", None),
    ("XS2020009", "黄志远", "男", "13800009999", "华南销售二部", "佛山", "高级销售", "2020-04-18", "在职", None),
    ("XS2024010", "许曼", "女", "13800001010", "西南销售部", "重庆", "销售代表", "2024-01-08", "离职", "已离职，借资需重点跟进"),
]

# (借资单号, 销售人员序号, 金额, 距今借资天数, 类型, 用途, 备注, 最终状态)
LOANS = [
    ("JZ20250001", 1, 28000.00, 200, "差旅借款", "2025年华东区客户走访差旅费预支", "多次口头提醒未还", None),
    ("JZ20250002", 2, 15000.00, 168, "市场推广借款", "深圳电子展展位物料制作费用", "已于上月归还部分", None),
    ("JZ20250003", 5, 46000.00, 250, "项目周转借款", "杭州大客户项目投标保证金周转", "金额较大，需财务总监审批延期", None),
    ("JZ20250004", 7, 12000.00, 141, "客户招待借款", "成都区域重点客户商务招待", None, None),
    ("JZ20250005", 10, 8600.00, 320, "备用金", "重庆市场开拓备用金（人员已离职）", "人员离职，需重点催收", None),
    ("JZ20250006", 4, 32000.00, 100, "差旅借款", "上海区域年度客户答谢会差旅预支", None, None),
    ("JZ20250007", 6, 9800.00, 95, "市场推广借款", "北京高校渠道推广物料费用", None, None),
    ("JZ20250008", 9, 21000.00, 92, "项目周转借款", "佛山制造企业项目前期垫资", None, None),
    ("JZ20250009", 1, 6000.00, 30, "差旅借款", "广州客户日常拜访差旅费", None, None),
    ("JZ20250010", 3, 13500.00, 20, "客户招待借款", "东莞客户工厂考察接待费用", None, None),
    ("JZ20250011", 8, 7200.00, 15, "市场推广借款", "天津区域线下推广活动经费", None, None),
    ("JZ20250012", 2, 18000.00, 10, "项目周转借款", "深圳客户续约项目前期费用", None, None),
    ("JZ20250013", 6, 4500.00, 5, "备用金", "北京区域临时备用金", None, None),
    ("JZ20250014", 3, 11000.00, 150, "差旅借款", "东莞客户年度走访差旅费", "已全额归还", "已还清"),
    ("JZ20250015", 4, 26000.00, 210, "市场推广借款", "上海展会推广费用（已结清）", "已全额归还", "已还清"),
    ("JZ20250016", 5, 5000.00, 130, "客户招待借款", "杭州客户招待费用（票据核销）", "凭票据核销", "已核销"),
    ("JZ20250017", 9, 8000.00, 60, "差旅借款", "佛山客户现场支持差旅费", None, None),
]

# (借资单号, 还款金额, 距今还款天数, 还款方式, 备注)
REPAYMENTS = [
    ("JZ20250002", 5000.00, 20, "银行转账", "第一笔部分还款"),
    ("JZ20250006", 20000.00, 12, "工资抵扣", "按申请从当月工资中扣除"),
    ("JZ20250014", 11000.00, 25, "银行转账", "一次性还清"),
    ("JZ20250015", 26000.00, 40, "银行转账", "一次性还清"),
    ("JZ20250016", 5000.00, 30, "其他", "票据核销"),
    ("JZ20250017", 3000.00, 8, "银行转账", "第一笔部分还款"),
]


def _days_ago(days: int) -> str:
    from datetime import timedelta

    return (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")


def init_sqlite() -> None:
    conn = db.get_connection()
    assert not conn.is_mysql, "当前为 MySQL 模式，请使用 SQL 脚本初始化"

    schema_file = BASE_DIR / "schema" / "schema_sqlite.sql"
    print(f"[1/3] 执行结构脚本：{schema_file}")
    conn.raw.executescript(schema_file.read_text(encoding="utf-8"))
    conn.raw.commit()

    print("[2/3] 写入基础数据（用户 / 销售人员 / 借资 / 还款）…")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for username, pwd, real_name, role, dept, phone in USERS:
        conn.execute(
            """INSERT INTO sys_user (username, password_hash, real_name, role, dept, phone,
                                     status, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s)""",
            (username, pwd, real_name, role, dept, phone, now, now),
        )

    sales_ids = {}
    for (emp_no, name, gender, phone, dept, region, job_title, entry, status, remark) in SALES:
        sid = conn.execute(
            """INSERT INTO sales_person (emp_no, name, gender, phone, dept, region, job_title,
                                         entry_date, status, remark, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (emp_no, name, gender, phone, dept, region, job_title, entry, status, remark, now, now),
        )
        sales_ids[emp_no] = sid
        sales_ids[name] = sid

    loan_ids = {}
    for (loan_no, idx, amount, days, loan_type, purpose, remark, final_status) in LOANS:
        sales_id = sales_ids[SALES[idx - 1][1]]
        loan_date = date.today() - _timedelta(days)
        deadline = db.add_months(loan_date, config.OVERDUE_MONTHS)
        loan_id = conn.execute(
            """INSERT INTO loan_record
               (loan_no, sales_id, amount, loan_date, repay_deadline, loan_type, purpose,
                status, repaid_amount, remark, created_by, is_deleted, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, '待还款', 0, %s, '孙丽华', 0, %s, %s)""",
            (loan_no, sales_id, amount, loan_date.strftime("%Y-%m-%d"),
             deadline.strftime("%Y-%m-%d"), loan_type, purpose, remark, now, now),
        )
        loan_ids[loan_no] = loan_id
        if final_status:
            conn.affected("UPDATE loan_record SET status = %s WHERE id = %s",
                          (final_status, loan_id))

    for (loan_no, amount, days, method, remark) in REPAYMENTS:
        conn.execute(
            """INSERT INTO repayment_record (loan_id, repay_amount, repay_date, repay_method,
                                             operator, remark, created_at)
               VALUES (%s, %s, %s, %s, '孙丽华', %s, %s)""",
            (loan_ids[loan_no], amount, _days_ago(days), method, remark, now),
        )

    print("[3/3] 依据还款流水重算借资状态…")
    from app.services.loan_service import sync_loan_status

    for loan_no, loan_id in loan_ids.items():
        sync_loan_status(loan_id)
    for loan_no, _idx, _amount, _days, _t, _p, _r, final_status in LOANS:
        if final_status in ("已还清", "已核销"):
            conn.affected("UPDATE loan_record SET status = %s WHERE id = %s",
                          (final_status, loan_ids[loan_no]))

    stat = conn.query_one(
        """SELECT (SELECT COUNT(*) FROM sys_user) AS u,
                  (SELECT COUNT(*) FROM sales_person) AS s,
                  (SELECT COUNT(*) FROM loan_record) AS l,
                  (SELECT COUNT(*) FROM repayment_record) AS r,
                  (SELECT COUNT(*) FROM loan_record WHERE repaid_amount < amount
                     AND status NOT IN ('已还清','已核销')) AS unpaid""")
    print("\n初始化完成：", stat)

    # ---------------- 知识库（RAG 语料）入库 ----------------
    from app.services import knowledge_service

    kb = knowledge_service.ingest(force=True)
    print(f"知识库导入完成：{kb['docs']} 份制度文档，切分 {kb['chunks']} 个知识块")

    print(f"演示数据库文件：{config.SQLITE_PATH}")
    print("默认账号：admin/admin123（管理员）、finance/finance123（财务）、sales/sales123（只读）")


def _timedelta(days: int):
    from datetime import timedelta

    return timedelta(days=days)


def main() -> None:
    target = (sys.argv[1].lower() if len(sys.argv) > 1 else config.DB_DIALECT)
    print(f"数据库方言：{target}")
    if target == "mysql":
        print(
            "\n请使用 MySQL 客户端依次执行以下脚本完成初始化：\n"
            "    mysql -u root -p < 数据库SQL脚本/01_schema.sql\n"
            "    mysql -u root -p loan_system < 数据库SQL脚本/02_init_data.sql\n"
            "    mysql -u root -p loan_system < 数据库SQL脚本/03_demo_queries.sql   # 验证查询（可选）\n"
        )
        return
    if target != "sqlite":
        print(f"不支持的方言：{target}（可选 sqlite / mysql）")
        sys.exit(1)
    if config.DB_DIALECT != "sqlite":
        print("提示：请先在 .env 中设置 DB_DIALECT=sqlite，或改用 `python init_db.py sqlite`。")
    init_sqlite()


if __name__ == "__main__":
    main()
