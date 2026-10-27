# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— RAG 检索增强服务
=====================================================================
实现一个不依赖向量数据库的轻量 RAG（Retrieval-Augmented Generation）：

    检索  BM25（词频-逆文档频率的经典排序函数）
        + TF-IDF 余弦相似度
        → 混合打分（0.6 × BM25 归一化 + 0.4 × 余弦）
    重排  LLM 重排（可选）：把 Top-8 候选交给大模型按相关性重排，取 Top-K
    增强  检索片段拼入提示词，要求模型「只依据给定条款回答并标注出处」
    生成  输出答复 + 结构化依据（文档名 / 章节 / 片段 / 得分）

设计取舍：
    · 不引入 faiss / chromadb / sklearn，纯 Python + 标准库实现，保持零额外依赖；
    · 中文用 2-gram 切分替代分词器（见 knowledge_service.tokenize）；
    · 向量检索预留扩展点：RagIndex 的 build/search 与后端实现解耦，
      接入真实 embedding 服务时只需替换 _vector_score 即可。
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

from config import config
from app.llm import LLMUnavailable, llm_client
from app.services import knowledge_service as kb

BM25_K1 = 1.2
BM25_B = 0.75
WEIGHT_BM25 = 0.6
WEIGHT_VECTOR = 0.4

_INDEX: Optional["RagIndex"] = None
_INDEX_SIZE = -1


# ---------------------------------------------------------------------------
# 索引
# ---------------------------------------------------------------------------
class RagIndex:
    """BM25 + TF-IDF 倒排索引（内存态，按知识块数量变化自动重建）"""

    def __init__(self, chunks: List[Dict[str, Any]]):
        self.chunks = chunks
        self.n = len(chunks)
        self.term_freqs: List[Dict[str, int]] = []
        self.doc_lens: List[int] = []
        self.doc_vectors: List[Dict[str, float]] = []
        self.df: Dict[str, int] = {}

        for chunk in chunks:
            text = f"{chunk['doc_title']} {chunk['heading']} {chunk['content']}"
            tf = kb.term_freq(text)
            self.term_freqs.append(tf)
            self.doc_lens.append(sum(tf.values()) or 1)
            for term in tf:
                self.df[term] = self.df.get(term, 0) + 1

        self.avgdl = sum(self.doc_lens) / self.n if self.n else 0.0
        self.idf: Dict[str, float] = {
            term: math.log((self.n + 1) / (freq + 1)) + 1.0
            for term, freq in self.df.items()
        }
        # 预计算文档的 TF-IDF 向量并归一化
        for tf, length in zip(self.term_freqs, self.doc_lens):
            vector = {
                term: (count / length) * self.idf.get(term, 1.0)
                for term, count in tf.items()
            }
            self.doc_vectors.append(_normalize(vector))

    # -- 两种打分 ---------------------------------------------------------
    def _bm25(self, query_terms: List[str], i: int) -> float:
        tf = self.term_freqs[i]
        dl = self.doc_lens[i]
        score = 0.0
        for term in query_terms:
            freq = tf.get(term)
            if not freq:
                continue
            idf = self.idf.get(term, 0.0)
            denom = freq + BM25_K1 * (1 - BM25_B + BM25_B * dl / (self.avgdl or 1))
            score += idf * freq * (BM25_K1 + 1) / (denom or 1)
        return score

    def _vector_score(self, query_terms: List[str], i: int) -> float:
        """TF-IDF 余弦相似度；接入真实 embedding 时替换本方法即可。"""
        query_tf = {}
        for term in query_terms:
            query_tf[term] = query_tf.get(term, 0) + 1
        length = sum(query_tf.values()) or 1
        query_vector = _normalize({
            term: (count / length) * self.idf.get(term, 1.0)
            for term, count in query_tf.items()
        })
        doc_vector = self.doc_vectors[i]
        # 只遍历较短的一侧，减少计算量
        if len(query_vector) < len(doc_vector):
            return sum(weight * doc_vector.get(term, 0.0) for term, weight in query_vector.items())
        return sum(weight * query_vector.get(term, 0.0) for term, weight in doc_vector.items())

    # -- 检索 -------------------------------------------------------------
    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_terms = kb.tokenize(query)
        if not query_terms or not self.n:
            return []

        raw_bm25 = [self._bm25(query_terms, i) for i in range(self.n)]
        max_bm25 = max(raw_bm25) or 1.0
        results: List[Dict[str, Any]] = []
        for i, chunk in enumerate(self.chunks):
            bm25 = raw_bm25[i]
            cosine = self._vector_score(query_terms, i)
            hybrid = WEIGHT_BM25 * (bm25 / max_bm25) + WEIGHT_VECTOR * cosine
            if hybrid <= 0:
                continue
            results.append({
                "chunk_id": chunk["id"],
                "doc_code": chunk["doc_code"],
                "doc_title": chunk["doc_title"],
                "heading": chunk["heading"],
                "content": chunk["content"],
                "score": round(hybrid, 4),
                "bm25": round(bm25, 4),
                "cosine": round(cosine, 4),
            })
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:max(top_k, 1)]


def _normalize(vector: Dict[str, float]) -> Dict[str, float]:
    norm = math.sqrt(sum(value * value for value in vector.values()))
    if not norm:
        return {}
    return {term: value / norm for term, value in vector.items()}


# ---------------------------------------------------------------------------
# 索引生命周期
# ---------------------------------------------------------------------------
def get_index(rebuild: bool = False) -> Optional[RagIndex]:
    global _INDEX, _INDEX_SIZE
    if not kb.ensure_ready():
        return None
    size = kb.count_chunks()
    if rebuild or _INDEX is None or size != _INDEX_SIZE:
        _INDEX = RagIndex(kb.load_chunks())
        _INDEX_SIZE = size
    return _INDEX


def rebuild() -> int:
    """重建知识库与索引（导入文档后调用）。"""
    kb.ingest(force=True)
    index = get_index(rebuild=True)
    return index.n if index else 0


# ---------------------------------------------------------------------------
# LLM 重排
# ---------------------------------------------------------------------------
RERANK_PROMPT = """你是检索结果重排器。给定用户问题和若干候选条款片段，请按与问题的相关性从高到低排序。
只输出 JSON：{"order": [编号从高到低排列]}，不要输出其他内容。"""


def rerank(question: str, candidates: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    if len(candidates) <= 2 or not llm_client.enabled or not config.RAG_RERANK:
        return candidates[:top_k]
    listing = []
    pool = candidates[:8]
    for i, item in enumerate(pool, start=1):
        listing.append(f"[{i}]《{item['doc_title']}》{item['heading']}：{item['content'][:120]}")
    try:
        data = llm_client.chat_json([
            {"role": "system", "content": RERANK_PROMPT},
            {"role": "user", "content": f"用户问题：{question}\n\n候选片段：\n" + "\n".join(listing)},
        ], temperature=0.0)
    except LLMUnavailable:
        return candidates[:top_k]

    order = data.get("order") if isinstance(data, dict) else None
    if not isinstance(order, list):
        return candidates[:top_k]
    reordered: List[Dict[str, Any]] = []
    used = set()
    for item in order:
        try:
            index = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= index <= len(pool) and index not in used:
            used.add(index)
            reordered.append(pool[index - 1])
    reordered.extend([item for i, item in enumerate(pool, start=1) if i not in used])
    return reordered[:top_k]


# ---------------------------------------------------------------------------
# 生成带出处的答复
# ---------------------------------------------------------------------------
RAG_ANSWER_PROMPT = """你是企业财务制度问答助手。请严格依据下面提供的制度条款回答用户问题。

要求：
1. 只使用给定条款中的信息，不得编造条款编号、金额、期限；条款不足以回答时，明确说明"制度中未明确规定"，并给出最接近的条款；
2. 回答后用「依据：《文档名称》- 章节」的格式标注出处，可标注多条；
3. 能用条目说明的用条目，控制在 250 字以内，不要输出 SQL 或代码。"""


def answer(question: str, top_k: Optional[int] = None) -> Dict[str, Any]:
    """RAG 主流程：检索 → （重排）→ 拼上下文 → 生成答复 → 返回依据。"""
    top_k = top_k or config.RAG_TOP_K
    index = get_index()
    if index is None:
        return {"answer": "知识库尚未就绪，请联系管理员执行知识库初始化。", "answer_source": "系统提示",
                "evidence": [], "retrieval": {"candidates": 0}}

    candidates = index.search(question, top_k=max(top_k * 2, top_k))
    if not candidates:
        return {"answer": "知识库中没有检索到与问题相关的制度条款。", "answer_source": "系统提示",
                "evidence": [], "retrieval": {"candidates": 0}}

    picked = rerank(question, candidates, top_k)
    method = "BM25+TFIDF 混合检索"
    if llm_client.enabled and config.RAG_RERANK and len(candidates) > 2:
        method += " + LLM 重排"

    if not llm_client.enabled:
        best = picked[0]
        answer_text = (
            f"依据《{best['doc_title']}》{best['heading']}：\n{best['content']}\n\n"
            f"依据：《{best['doc_title']}》- {best['heading']}"
        )
        source = "规则模板"
    else:
        context = "\n\n".join(
            f"【{i}】《{item['doc_title']}》{item['heading']}：{item['content']}"
            for i, item in enumerate(picked, start=1)
        )
        try:
            answer_text = llm_client.chat_text([
                {"role": "system", "content": RAG_ANSWER_PROMPT},
                {"role": "user", "content": f"制度条款：\n{context}\n\n用户问题：{question}"},
            ], temperature=0.2)
            source = "LLM"
        except LLMUnavailable:
            best = picked[0]
            answer_text = f"依据《{best['doc_title']}》{best['heading']}：{best['content']}"
            source = "规则模板"

    return {
        "answer": answer_text,
        "answer_source": source,
        "evidence": [
            {
                "doc_code": item["doc_code"],
                "doc_title": item["doc_title"],
                "heading": item["heading"],
                "content": item["content"],
                "score": item["score"],
                "bm25": item["bm25"],
                "cosine": item["cosine"],
            }
            for item in picked
        ],
        "retrieval": {"method": method, "candidates": len(candidates), "top_k": len(picked)},
    }


def search_only(question: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
    index = get_index()
    if index is None:
        return []
    return index.search(question, top_k=top_k or config.RAG_TOP_K)
