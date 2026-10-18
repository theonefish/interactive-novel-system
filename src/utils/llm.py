"""LLM 调用封装

使用 LangChain 的 ChatOpenAI（开启 streaming），以便 LangGraph 的
astream_events 能捕获 on_chat_model_stream 事件，实现 SSE 逐 token 推送。
对外接口 llm_call 保持「同步、返回完整字符串」，现有调用方无需改动。
每次调用都会把 token 用量记入 src/utils/usage.py，便于做省 token 的量化对比。
"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from src.utils.config import OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL, MAX_TOKENS
from src.utils.usage import normalize_usage, record_usage


def _build_chat(model: str, temperature: float, max_tokens: int) -> ChatOpenAI:
    """构造 ChatOpenAI 实例（开启流式 + 带上用量统计，兼容 LangGraph 事件系统）"""
    return ChatOpenAI(
        model=model or LLM_MODEL,
        temperature=temperature,
        max_tokens=max_tokens or MAX_TOKENS,
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
        streaming=True,
        stream_usage=True,  # 流式下也要返回 token 用量，否则无法计量
    )


def _collect_stream(chat, messages):
    """自己消费流式输出，返回 (完整文本, 最后一个带用量的分片)。

    为什么不直接用 chat.invoke()：LangChain 合并流式分片时会把 usage_metadata
    **求和**（langchain_core.messages.ai 的 add_usage），而部分 OpenAI 兼容服务
    （实测 SiliconFlow）在流式下每个分片都带 usage，导致统计被放大几百倍
    （曾出现一次写剧情 input=169 万）。这里只取最后一个分片的用量，即真实用量。
    """
    parts = []
    last_usage = None
    for chunk in chat.stream(messages):
        content = getattr(chunk, "content", None)
        if content:
            parts.append(content)
        usage = getattr(chunk, "usage_metadata", None)
        if usage:
            last_usage = usage
    return "".join(parts), last_usage


def llm_call(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    temperature: float = 0.8,
    max_tokens: int = None,
    node: str = "",
) -> str:
    """调用 OpenAI 兼容接口（流式返回完整文本），并记录本次 token 用量。

    node: 调用方节点名（world_builder / story_driver / critic / integrator / supervisor），
          仅用于用量归类统计。
    """
    chat = _build_chat(model, temperature, max_tokens)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    text, last_usage = _collect_stream(chat, messages)
    record_usage(node or "llm", (model or LLM_MODEL), normalize_usage(last_usage))
    return text
