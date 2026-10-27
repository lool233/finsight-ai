# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 知识库构建脚本
=====================================================================
把 knowledge/ 目录下的制度文档切块并写入数据库（RAG 的语料索引）。

用法：
    python kb_build.py          # 重建知识库（清空后重新切块入库）
    python kb_build.py --stat   # 只查看当前知识库状态

说明：
    · 使用 SQLite 演示库时，`python init_db.py sqlite` 已自动完成导入；
    · 使用 MySQL 时，可执行《数据库SQL脚本/04_knowledge_data.sql》导入，
      也可配置好 .env 后执行本脚本（两种方式结果一致）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import config  # noqa: E402
from app import db  # noqa: E402
from app.services import knowledge_service, rag_service  # noqa: E402


def show_stat() -> None:
    docs = knowledge_service.list_docs()
    print(f"知识库目录：{config.KNOWLEDGE_DIR}")
    print(f"文档数量：{len(docs)}　知识块总数：{knowledge_service.count_chunks()}")
    for doc in docs:
        print(f"  · {doc['doc_code']}　{doc['title']}（{doc['chunk_count']} 块）")


def main() -> None:
    if "--stat" in sys.argv:
        show_stat()
        return

    result = knowledge_service.ingest(force=True)
    index = rag_service.get_index(rebuild=True)
    print(f"已导入 {result['docs']} 份文档，切分 {result['chunks']} 个知识块，"
          f"索引规模 {index.n if index else 0}")
    show_stat()

    # 自检：用三个典型问题验证检索命中
    for question in ("借资逾期多久算三级催收", "核销需要什么票据", "借资单号怎么生成"):
        hits = rag_service.search_only(question, top_k=2)
        top = hits[0] if hits else None
        print(f"\n问题：{question}")
        print(f"  Top1：{top['doc_title']} / {top['heading']}（score={top['score']}）" if top
              else "  未命中")


if __name__ == "__main__":
    main()
