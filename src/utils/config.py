"""配置参数

配置优先级：.env 环境变量 > configs/settings.yaml 默认值

注意：.env 中的值始终优先，YAML 仅作为未设置时的后备默认值。
引用了 configs/settings.yaml 中的对应键路径：
  llm -> openai_api_key / openai_base_url / model / max_tokens
  story -> segment_length / options_count
  quality -> max_internal_iterations / pass_threshold / temperature_creative / temperature_critic
  rag -> chroma_host / chroma_port / chroma_collection / ...
  misc -> max_backtrack_steps / mcp_bing_enabled
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 统一加载 configs/.env（单一配置来源）
load_dotenv(Path(__file__).resolve().parent.parent.parent / "configs" / ".env")

# ── 读取 YAML 配置作默认值 ──────────────────────────

import yaml

_yaml_path = Path(__file__).resolve().parent.parent.parent / "configs" / "settings.yaml"
_settings = {}
if _yaml_path.exists():
    with open(_yaml_path, "r", encoding="utf-8") as _f:
        _raw = yaml.safe_load(_f) or {}
        _settings = _raw

def _yaml_val(*keys: str, default=None):
    """从 YAML 嵌套字典中取值，keys 为逐级键路径"""
    val = _settings
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return default
    return val if val is not None else default

# ── LLM 配置 ─────────────────────────────────────────

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", _yaml_val("llm", "openai_api_key", default=""))
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", _yaml_val("llm", "openai_base_url", default="https://api.openai.com/v1"))
LLM_MODEL = os.getenv("LLM_MODEL", _yaml_val("llm", "model", default="gpt-4o"))
# critic（判分）可以单独换便宜模型；留空表示沿用主模型
CRITIC_MODEL = os.getenv("CRITIC_MODEL", _yaml_val("llm", "critic_model", default=""))
# 写剧情单次输出上限（段落后不需要太多 token，可按需调小）
WRITER_MAX_TOKENS = int(os.getenv("WRITER_MAX_TOKENS",
    str(_yaml_val("llm", "writer_max_tokens", default=2048))))

# ── 创作参数 ─────────────────────────────────────────

SEGMENT_LENGTH = int(os.getenv("SEGMENT_LENGTH",
    str(_yaml_val("story", "segment_length", default=300))))
OPTIONS_COUNT = int(os.getenv("OPTIONS_COUNT",
    str(_yaml_val("story", "options_count", default=3))))
# 注入 prompt 的历史段数（只带最近 N 段，更早的不注入）
HISTORY_SEGMENTS_IN_PROMPT = int(os.getenv("HISTORY_SEGMENTS_IN_PROMPT",
    str(_yaml_val("story", "history_segments_in_prompt", default=2))))
# 注入 prompt 的角色数上限
MAX_CHARACTERS_IN_PROMPT = int(os.getenv("MAX_CHARACTERS_IN_PROMPT",
    str(_yaml_val("story", "max_characters_in_prompt", default=6))))
# 记忆摘要注入上限（字符）
MEMORY_CONTEXT_MAX_CHARS = int(os.getenv("MEMORY_CONTEXT_MAX_CHARS",
    str(_yaml_val("story", "memory_context_max_chars", default=400))))
MAX_INTERNAL_ITERATIONS = int(os.getenv("MAX_INTERNAL_ITERATIONS",
    str(_yaml_val("quality", "max_internal_iterations", default=3))))
# 每几轮做一次剧情审核（1 = 每轮都审）；高风险选项与手动重新生成仍强制审核
CRITIC_EVERY_N_TURNS = int(os.getenv("CRITIC_EVERY_N_TURNS",
    str(_yaml_val("quality", "critic_every_n_turns", default=2))))
PASS_THRESHOLD = int(os.getenv("PASS_THRESHOLD",
    str(_yaml_val("quality", "pass_threshold", default=6))))

# ── LLM 温度 ─────────────────────────────────────────

TEMPERATURE_CREATIVE = float(os.getenv("TEMPERATURE_CREATIVE",
    str(_yaml_val("quality", "temperature_creative", default=0.8))))
TEMPERATURE_CRITIC = float(os.getenv("TEMPERATURE_CRITIC",
    str(_yaml_val("quality", "temperature_critic", default=0.3))))

# ── RAG 检索配置 ────────────────────────────────────

CHROMA_HOST = os.getenv("CHROMA_HOST", _yaml_val("rag", "chroma_host", default="localhost"))
CHROMA_PORT = int(os.getenv("CHROMA_PORT", str(_yaml_val("rag", "chroma_port", default=8081))))
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", _yaml_val("rag", "chroma_collection", default="default"))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", _yaml_val("rag", "embedding_model", default="BAAI/bge-m3"))
RERANK_MODEL = os.getenv("RERANK_MODEL", _yaml_val("rag", "rerank_model", default="BAAI/bge-reranker-v2-m3"))
RETRIEVE_K = int(os.getenv("RETRIEVE_K", str(_yaml_val("rag", "retrieve_k", default=20))))
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", str(_yaml_val("rag", "rerank_top_k", default=3))))
# 注入 prompt 时每个检索片段的字符上限
RAG_MAX_CHARS_PER_CHUNK = int(os.getenv("RAG_MAX_CHARS_PER_CHUNK",
    str(_yaml_val("rag", "max_chars_per_chunk", default=300))))
# 联网搜索结果缓存时长（秒）：重做世界观时不再重复搜索
SEARCH_CACHE_TTL = int(os.getenv("SEARCH_CACHE_TTL",
    str(_yaml_val("rag", "search_cache_ttl", default=3600))))
RAG_CACHE_TTL = int(os.getenv("RAG_CACHE_TTL", str(_yaml_val("rag", "cache_ttl", default=300))))

# ── MCP Bing 搜索配置 ───────────────────────────────

MCP_BING_ENABLED = os.getenv("MCP_BING_ENABLED",
    str(_yaml_val("misc", "mcp_bing_enabled", default="true"))).lower() == "true"

# ── 其他 ─────────────────────────────────────────────

MAX_TOKENS = int(os.getenv("MAX_TOKENS",
    str(_yaml_val("llm", "max_tokens", default=2048))))
MAX_BACKTRACK_STEPS = int(os.getenv("MAX_BACKTRACK_STEPS",
    str(_yaml_val("misc", "max_backtrack_steps", default=5))))