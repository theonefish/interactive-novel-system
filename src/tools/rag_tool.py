"""RAG 检索工具 - 向量检索 + Reranker 重排序

使用 ChromaDB 进行向量存储，SiliconFlow API 进行 Embedding 和 Rerank。

先做向量粗召回、再做 Rerank 精排、最后带缓存返回最相关的知识库片段
"""

import os
import hashlib
import time
import requests
from typing import List
from pathlib import Path
from dotenv import load_dotenv

# 加载 configs/.env
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / "configs" / ".env")

# ─── 配置（从 src.utils.config 获取）─────
import sys
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from src.utils.config import (
    CHROMA_HOST,
    CHROMA_PORT,
    CHROMA_COLLECTION,
    EMBEDDING_MODEL,
    RERANK_MODEL,
    RETRIEVE_K,
    RERANK_TOP_K,
    RAG_CACHE_TTL,
)

EMBEDDING_API_KEY = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_BASE_URL = os.getenv("OPENAI_BASE_URL", )
RERANK_BASE_URL = os.getenv("RERANK_BASE_URL", )

# ─── TTL 缓存（减少重复 API 调用）────────────────────
"""
它给 RAG 检索加了一层缓存：
同样的查询在 5 分钟内直接返回上次结果，减少重复调用底层向量库/搜索接口；
缓存条目超过 128 条时淘汰最旧数据，防止内存无限增长
"""
class _TTLCache:
    """进程内 LRU + TTL 缓存，用于缓存 RAG 检索结果"""
    def __init__(self, maxsize: int = 128, ttl: int = 300):
        self._cache = {}          # 缓存字典：key -> (value, 写入时间戳)
        self._maxsize = maxsize   # 最大缓存条数（容量上限）
        self._ttl = ttl           # 单条记录的存活时间（秒），超时失效

    def get(self, key: str):
        # 命中缓存：取出值与写入时间戳，判断是否仍在 TTL 有效期内
        if key in self._cache:
            val, ts = self._cache[key]
            if time.time() - ts < self._ttl:
                return val        # 未过期 -> 直接返回缓存值
            del self._cache[key]  # 已过期 -> 主动删除，防止脏数据堆积
        return None               # 未命中或已过期，返回 None

    def set(self, key: str, value: str):
        # 容量已满：淘汰「写入时间最早」的那条记录（最老优先淘汰）
        if len(self._cache) >= self._maxsize:
            oldest = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest]
        # 写入新值，并记录当前时间戳
        self._cache[key] = (value, time.time())

_rag_cache = _TTLCache(ttl=RAG_CACHE_TTL)

# ─── Embedding ─────────────────────────────────────

def _get_embeddings():
    """延迟初始化 embeddings 对象"""
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        api_key=EMBEDDING_API_KEY,
        base_url=EMBEDDING_BASE_URL,
    )

def _get_vector_store():
    """获取 Chroma 向量存储"""
    from langchain_chroma import Chroma
    return Chroma(
        host=CHROMA_HOST,
        port=CHROMA_PORT,
        collection_name=CHROMA_COLLECTION,
        embedding_function=_get_embeddings(),
    )

# ─── Reranker ──────────────────────────────────────

def rerank_documents(query: str, documents: List[str], top_k: int = RERANK_TOP_K) -> List[int]:
    """调用 SiliconFlow Rerank API 对文档进行重排序,返回按相关性从高到低的索引列表
    """
    url = RERANK_BASE_URL.rstrip("/") + "/rerank"
    headers = {
        "Authorization": f"Bearer {EMBEDDING_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": RERANK_MODEL,
        "query": query,
        "documents": documents,
        "top_n": top_k,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    results = sorted(data.get("results", []), key=lambda x: x["relevance_score"], reverse=True)
    return [r["index"] for r in results]

# ─── 检索接口 ──────────────────────────────────────

def retrieve(query: str, top_k: int = RERANK_TOP_K) -> str:
    """RAG 检索：向量检索 + Reranker 重排序（带 TTL 缓存）
        query: 检索问题
        top_k: 返回的文档片段数
        检索到的文档内容文本，失败时返回空字符串
    """
    cache_key = hashlib.md5(query.encode()).hexdigest()
    cached = _rag_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        vector_store = _get_vector_store()

        # 1. 向量检索取候选
        candidates = vector_store.similarity_search(query, k=RETRIEVE_K)
        if not candidates:
            return ""

        # 2. Reranker 重排序
        doc_texts = [c.page_content for c in candidates]
        ranked_indices = rerank_documents(query, doc_texts, top_k=top_k)

        # 3. 取最优片段
        top_chunks = [candidates[i] for i in ranked_indices]
        result = "\n\n---\n\n".join(chunk.page_content for chunk in top_chunks)
        if result:
            _rag_cache.set(cache_key, result)
        return result

    except Exception as e:
        print(f"[rag_tool] 检索失败: {e}")
        return ""

def retrieve_for_writing(
    world_setting: str,
    story_history: str,
    current_context: str,
    user_input: str,
) -> str:
    """为写作 agent 构建 RAG 查询并检索参考文档

    将当前故事状态整合为检索 query，返回相关知识库片段。
        world_setting: 世界观设定
        story_history: 历史剧情摘要
        current_context: 当前上下文
        user_input: 用户输入
        检索到的参考文本，无结果时返回空字符串
    """
    # 用用户输入 + 世界观关键词构建查询
    query_parts = []
    if user_input:
        query_parts.append(user_input[:100])
    if world_setting:
        # 取世界观前 50 字作为背景关键词
        query_parts.append(world_setting[:50])
    if current_context:
        query_parts.append(current_context[:50])
    # 如果没有用户输入，则直接使用世界观关键词作为查询
    query = " ".join(query_parts) if query_parts else world_setting
    # 如果 query 为空，则直接返回空字符串，避免无意义的检索
    if not query.strip():
        return ""

    return retrieve(query)