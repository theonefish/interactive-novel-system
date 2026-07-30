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

# 同时加载根目录 .env 和 configs/.env
load_dotenv()
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

# ── 创作参数 ─────────────────────────────────────────

SEGMENT_LENGTH = int(os.getenv("SEGMENT_LENGTH",
    str(_yaml_val("story", "segment_length", default=300))))
OPTIONS_COUNT = int(os.getenv("OPTIONS_COUNT",
    str(_yaml_val("story", "options_count", default=3))))
MAX_INTERNAL_ITERATIONS = int(os.getenv("MAX_INTERNAL_ITERATIONS",
    str(_yaml_val("quality", "max_internal_iterations", default=3))))
PASS_THRESHOLD = int(os.getenv("PASS_THRESHOLD",
    str(_yaml_val("quality", "pass_threshold", default=6))))

# ── LLM 温度 ─────────────────────────────────────────

TEMPERATURE_CREATIVE = float(os.getenv("TEMPERATURE_CREATIVE",
    str(_yaml_val("quality", "temperature_creative", default=0.8))))
TEMPERATURE_CRITIC = float(os.getenv("TEMPERATURE_CRITIC",
    str(_yaml_val("quality", "temperature_critic", default=0.3))))

# ── MCP Bing 搜索配置 ───────────────────────────────

MCP_BING_ENABLED = os.getenv("MCP_BING_ENABLED",
    str(_yaml_val("misc", "mcp_bing_enabled", default="true"))).lower() == "true"

# ── 其他 ─────────────────────────────────────────────

MAX_TOKENS = int(os.getenv("MAX_TOKENS",
    str(_yaml_val("llm", "max_tokens", default=2048))))
MAX_BACKTRACK_STEPS = int(os.getenv("MAX_BACKTRACK_STEPS",
    str(_yaml_val("misc", "max_backtrack_steps", default=5))))