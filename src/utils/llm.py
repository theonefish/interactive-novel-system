"""LLM 调用封装"""

from openai import OpenAI
from src.utils.config import OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL, MAX_TOKENS


_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def llm_call(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    temperature: float = 0.8,
    max_tokens: int = None,
) -> str:
    """调用 OpenAI 兼容接口"""
    response = _client.chat.completions.create(
        model=model or LLM_MODEL,
        temperature=temperature,
        max_tokens=max_tokens or MAX_TOKENS,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content or ""