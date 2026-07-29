"""RAG 检索工具 - 向量检索 + Reranker 重排序

参考 exchange_rag_agent 实现，适配本项目结构。
使用 ChromaDB 进行向量存储，SiliconFlow API 进行 Embedding 和 Rerank。

前置条件：
    1. ChromaDB 服务运行在 localhost:8081
    2. 知识库文档已通过 document_util.py 入库
"""

import os
import requests
from typing import List, Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(__file__).resolve().parent.parent.parent / "configs" / ".env")

# ─── 配置 ──────────────────────────────────────────

EMBEDDING_API_KEY = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.siliconflow.cn/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
RERANK_BASE_URL = os.getenv("RERANK_BASE_URL", "https://api.siliconflow.cn/v1")

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8081"))
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "default")

RETRIEVE_K = 20       # 向量检索候选数
RERANK_TOP_K = 5      # 重排序后保留数


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
    """调用 SiliconFlow Rerank API 对文档进行重排序

    Returns:
        重排序后的索引列表（按相关性从高到低）
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
    """RAG 检索：向量检索 + Reranker 重排序

    Args:
        query: 检索问题
        top_k: 返回的文档片段数

    Returns:
        检索到的文档内容文本，失败时返回空字符串
    """
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
        return "\n\n---\n\n".join(chunk.page_content for chunk in top_chunks)

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

    Args:
        world_setting: 世界观设定
        story_history: 历史剧情摘要
        current_context: 当前上下文
        user_input: 用户输入

    Returns:
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

    query = " ".join(query_parts) if query_parts else user_input

    if not query.strip():
        return ""

    return retrieve(query)