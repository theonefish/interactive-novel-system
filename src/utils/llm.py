"""LLM 调用封装

使用 LangChain 的 ChatOpenAI（开启 streaming），以便 LangGraph 的
astream_events 能捕获 on_chat_model_stream 事件，实现 SSE 逐 token 推送。
对外接口 llm_call 保持「同步、返回完整字符串」，现有调用方无需改动。
"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from src.utils.config import OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL, MAX_TOKENS


def _build_chat(model: str, temperature: float, max_tokens: int) -> ChatOpenAI:
    """构造 ChatOpenAI 实例（开启流式，兼容 LangGraph 事件系统）"""
    return ChatOpenAI(
        model=model or LLM_MODEL,
        temperature=temperature,
        max_tokens=max_tokens or MAX_TOKENS,
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
        streaming=True,
    )


def llm_call(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    temperature: float = 0.8,
    max_tokens: int = None,
) -> str:
    """调用 OpenAI 兼容接口（流式聚合返回完整文本）"""
    chat = _build_chat(model, temperature, max_tokens)
    response = chat.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])
    return response.content or ""