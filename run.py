# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 启动入口
=====================================================================
运行：
    python run.py                # 使用 .env 中的配置启动
    python run.py --port 8000    # 指定端口
启动后访问：http://127.0.0.1:5000
默认账号：admin / admin123（管理员）   finance / finance123（财务）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import config  # noqa: E402
from app import create_app  # noqa: E402

app = create_app()


def banner() -> None:
    from app.llm import llm_client
    from app.services.sms_gateway import sms_gateway

    llm = llm_client.status()
    sms = sms_gateway.status()
    print("=" * 72)
    print(f"  {config.APP_NAME}  v{config.APP_VERSION}")
    print(f"  {config.APP_SUBTITLE}")
    print("=" * 72)
    print(f"  访问地址   : http://{config.HOST}:{config.PORT}")
    print(f"  数据库方言 : {config.DB_DIALECT}"
          + (f"  ({config.MYSQL_USER}@{config.MYSQL_HOST}:{config.MYSQL_PORT}/{config.MYSQL_DATABASE})"
             if config.DB_DIALECT == 'mysql' else f"  ({config.SQLITE_PATH})"))
    print(f"  大模型模式 : {llm['mode']}  [{llm['model']}]")
    print(f"  短信平台   : {sms['description']}")
    print(f"  逾期规则   : 借资超过 {config.OVERDUE_MONTHS} 个月未还即进入催还流程")
    print("-" * 72)
    print("  默认账号   : admin/admin123（管理员） finance/finance123（财务）")
    print("  按 Ctrl+C 停止服务")
    print("=" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{config.APP_NAME} 启动入口")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--debug", action="store_true", default=config.DEBUG)
    parser.add_argument("--no-debug", dest="debug", action="store_false")
    args = parser.parse_args()

    banner()
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)


if __name__ == "__main__":
    main()
