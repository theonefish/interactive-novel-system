"""
RAG检索文档 + BGE Reranker 重排序
"""
import json
from pathlib import Path
from typing import List

import requests
from langchain_chroma import Chroma
from langchain_core.tools import tool
from typing_extensions import Annotated

from models.llm import embeddings, embedding_api_key, rerank_model, rerank_base_url

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 检索时先取更多候选，再交给 Reranker 精排
RETRIEVE_K = 20       # 向量检索返回的候选数
RERANK_TOP_K = 5      # 重排序后保留的最优结果数

retrieve_vector_store = Chroma(
    host="localhost",
    port=8081,
    collection_name="default",
    embedding_function=embeddings,
)


def rerank_documents(query: str, documents: List[str], top_k: int = RERANK_TOP_K) -> List[int]:
    """
    调用 SiliconFlow Rerank API 对文档进行重排序
    返回重排序后的索引列表（按相关性从高到低）
    """
    url = rerank_base_url.rstrip("/") + "/rerank"
    headers = {
        "Authorization": f"Bearer {embedding_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": rerank_model,
        "query": query,
        "documents": documents,
        "top_n": top_k,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # 按 relevance_score 从高到低排序返回索引
    results = sorted(data.get("results", []), key=lambda x: x["relevance_score"], reverse=True)
    return [r["index"] for r in results]


@tool
def retrieve(query: Annotated[str, "用户要检索的问题"]):
    """进行RAG检索相关文档片段的工具，先向量检索再 Reranker 重排序"""
    # 1. 向量检索取更多候选
    candidates = retrieve_vector_store.similarity_search(query, k=RETRIEVE_K)
    if not candidates:
        return "未检索到相关文档内容。"

    # 2. Reranker 重排序
    doc_texts = [c.page_content for c in candidates]
    ranked_indices = rerank_documents(query, doc_texts, top_k=RERANK_TOP_K)

    # 3. 按重排序结果取最优片段
    top_chunks = [candidates[i] for i in ranked_indices]
    content = "\n\n---\n\n".join([chunk.page_content for chunk in top_chunks])
    return content