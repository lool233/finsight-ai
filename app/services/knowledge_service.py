# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 知识库服务（RAG 的语料层）
=====================================================================
职责：
    1. 读取 knowledge/ 目录下的财务制度文档（Markdown）
    2. 解析文档元信息与章节结构
    3. 按章节 + 段落切块（控制块长，保留章节标题作为上下文）
    4. 写入知识库表 knowledge_doc / knowledge_chunk
    5. 提供中文分词（2-gram）与词频统计，供检索层构建索引

为什么用 2-gram 而不用 jieba：
    项目坚持最小依赖（仅 Flask + PyMySQL），不引入分词库；中文检索在
    无分词器时用「二元组切分」是工业界常见做法，配合 BM25 效果足够，
    且对未登录词（如"许曼""核销"）同样有效。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

from config import config
from app import db

CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9]*|\d+(?:\.\d+)?")


# ---------------------------------------------------------------------------
# 分词
# ---------------------------------------------------------------------------
def tokenize(text: str) -> List[str]:
    """中文按 2-gram 切分，英文/数字按整词，统一小写。"""
    if not text:
        return []
    tokens: List[str] = [m.group(0).lower() for m in LATIN_RUN.finditer(text)]
    for run in CJK_RUN.findall(text):
        if len(run) == 1:
            tokens.append(run)
            continue
        for i in range(len(run) - 1):
            tokens.append(run[i:i + 2])
    return tokens


def term_freq(text: str) -> Dict[str, int]:
    tf: Dict[str, int] = {}
    for token in tokenize(text):
        tf[token] = tf.get(token, 0) + 1
    return tf


# ---------------------------------------------------------------------------
# 文档解析与切块
# ---------------------------------------------------------------------------
def parse_document(path: Path) -> Dict:
    """解析 Markdown 制度文档：标题、元信息、按二级标题切分的章节。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    title = path.stem
    meta: Dict[str, str] = {}
    sections: List[Tuple[str, List[str]]] = []
    current_heading: str = ""
    current_body: List[str] = []
    seen_section = False

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not seen_section and stripped.startswith("# "):
            title = stripped[2:].strip()
            continue
        if not seen_section and stripped.startswith("- ") and "：" in stripped:
            key, _, value = stripped[2:].partition("：")
            meta[key.strip()] = value.strip()
            continue
        if stripped.startswith("## "):
            if current_heading or current_body:
                sections.append((current_heading or "正文", [t for t in current_body if t]))
            current_heading = stripped[3:].strip()
            current_body = []
            seen_section = True
            continue
        if stripped:
            current_body.append(stripped)
    if current_heading or current_body:
        sections.append((current_heading or "正文", [t for t in current_body if t]))

    return {"title": title, "meta": meta, "sections": sections, "path": path.name}


def split_chunks(heading: str, paragraphs: List[str], size: int) -> List[str]:
    """把章节正文按段落累加切块，单段过长时按句号再切。"""
    chunks: List[str] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer.strip():
            chunks.append(buffer.strip())
        buffer = ""

    for para in paragraphs:
        if len(para) > size:
            # 超长段落：按句末标点再切
            flush()
            piece = ""
            for sentence in re.split(r"(?<=[。；！？])", para):
                if not sentence:
                    continue
                if len(piece) + len(sentence) > size and piece:
                    chunks.append(piece.strip())
                    piece = ""
                piece += sentence
            if piece.strip():
                chunks.append(piece.strip())
            continue
        if len(buffer) + len(para) + 1 > size and buffer:
            flush()
        buffer = f"{buffer}\n{para}" if buffer else para
    flush()
    return [c for c in chunks if c]


def collect_chunks() -> Tuple[List[Dict], List[Dict]]:
    """扫描 knowledge/ 目录，返回 (文档列表, 切块列表)。"""
    kb_dir = Path(config.KNOWLEDGE_DIR)
    if not kb_dir.exists():
        return [], []

    docs: List[Dict] = []
    chunks: List[Dict] = []
    for index, path in enumerate(sorted(kb_dir.glob("*.md")), start=1):
        parsed = parse_document(path)
        doc_code = parsed["meta"].get("文档编号") or f"KB-{index:03d}"
        docs.append({
            "doc_code": doc_code,
            "title": parsed["title"],
            "category": parsed["meta"].get("适用对象", ""),
            "version": parsed["meta"].get("版本", "V1.0"),
            "file_name": parsed["path"],
        })
        seq = 0
        for heading, paragraphs in parsed["sections"]:
            for content in split_chunks(heading, paragraphs, config.RAG_CHUNK_SIZE):
                seq += 1
                chunks.append({
                    "doc_code": doc_code,
                    "doc_title": parsed["title"],
                    "heading": heading,
                    "seq": seq,
                    "content": content,
                    "char_len": len(content),
                })
    return docs, chunks


# ---------------------------------------------------------------------------
# 入库
# ---------------------------------------------------------------------------
def ingest(force: bool = False) -> Dict[str, int]:
    """把 knowledge/ 下的文档切块写入知识库表。force=True 时先清空重建。"""
    docs, chunks = collect_chunks()
    if not docs:
        return {"docs": 0, "chunks": 0}

    existing = count_chunks()
    if force or existing != len(chunks):
        db.affected("DELETE FROM knowledge_chunk")
        db.affected("DELETE FROM knowledge_doc")

        doc_id_map: Dict[str, int] = {}
        for doc in docs:
            doc_id = db.execute(
                """INSERT INTO knowledge_doc (doc_code, title, category, version, file_name, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (doc["doc_code"], doc["title"], doc["category"], doc["version"],
                 doc["file_name"], _now()),
            )
            doc_id_map[doc["doc_code"]] = doc_id

        rows = []
        for chunk in chunks:
            rows.append((
                doc_id_map.get(chunk["doc_code"]), chunk["doc_code"], chunk["doc_title"],
                chunk["heading"], chunk["seq"], chunk["content"], chunk["char_len"], _now(),
            ))
        db.get_connection().executemany(
            """INSERT INTO knowledge_chunk
               (doc_id, doc_code, doc_title, heading, seq, content, char_len, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            rows,
        )
    return {"docs": len(docs), "chunks": len(chunks)}


def count_chunks() -> int:
    try:
        return int(db.query_scalar("SELECT COUNT(*) AS c FROM knowledge_chunk", default=0) or 0)
    except Exception:
        return 0


def load_chunks() -> List[Dict]:
    """读取全部知识块（含文档标题与章节标题），供检索层建索引。"""
    try:
        return db.query_all(
            """SELECT id, doc_code, doc_title, heading, seq, content
                 FROM knowledge_chunk ORDER BY doc_id, seq"""
        )
    except Exception:
        return []


def list_docs() -> List[Dict]:
    try:
        return db.query_all(
            """SELECT d.doc_code, d.title, d.category, d.version, COUNT(c.id) AS chunk_count
                 FROM knowledge_doc d LEFT JOIN knowledge_chunk c ON c.doc_id = d.id
                GROUP BY d.id, d.doc_code, d.title, d.category, d.version
                ORDER BY d.doc_code"""
        )
    except Exception:
        return []


def ensure_ready() -> bool:
    """知识库为空时自动导入（首次启动或换了数据库都无需手工操作）。"""
    try:
        if count_chunks() > 0:
            return True
        return ingest(force=True).get("chunks", 0) > 0
    except Exception:
        # 知识库表不存在（例如沿用了旧版数据库）时静默降级，不影响统计类问答
        return False


def _now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
