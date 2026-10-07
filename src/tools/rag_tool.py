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
    RAG_MAX_CHARS_PER_CHUNK,
)
from src.utils.prompt_utils import truncate_text
from src.utils.ttl_cache import TTLCache

EMBEDDING_API_KEY = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_BASE_URL = os.getenv("OPENAI_BASE_URL", )
RERANK_BASE_URL = os.getenv("RERANK_BASE_URL", )

# ─── TTL 缓存（减少重复 API 调用）────────────────────
# 缓存的 key 只由「稳定的检索词」决定，保证同一会话里多次检索能命中缓存。
_rag_cache = TTLCache(ttl=RAG_CACHE_TTL)

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
        result = format_chunks(top_chunks)
        if result:
            _rag_cache.set(cache_key, result)
        return result

    except Exception as e:
        print(f"[rag_tool] 检索失败: {e}")
        return ""

def format_chunks(chunks: List) -> str:
    """把检索到的片段拼成参考素材，每片按上限截断（控制注入 prompt 的体积）。"""
    return "\n\n---\n\n".join(
        truncate_text(chunk.page_content, RAG_MAX_CHARS_PER_CHUNK) for chunk in chunks
    )


def build_stable_query(user_input: str, world_setting: str) -> str:
    """用「不随每轮变化」的内容构造检索词。

    以前 query 里带了「用户选择了：X」，每轮都变 → TTL 缓存永远不命中，
    每轮都要重新做 embedding + rerank。改成只用用户需求 + 世界观关键词。
    """
    parts = []
    if user_input:
        parts.append(user_input[:100])
    if world_setting:
        parts.append(world_setting[:80])
    return " ".join(parts).strip()


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
    # 只用稳定内容做检索词（story_history / current_context 不参与），
    # 这样同一会话里多轮检索的 query 一致，TTL 缓存能真正命中。
    query = build_stable_query(user_input, world_setting)
    if not query:
        return ""

    return retrieve(query)