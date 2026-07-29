"""配置参数"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 同时加载根目录 .env 和 configs/.env
load_dotenv()
load_dotenv(Path(__file__).resolve().parent.parent.parent / "configs" / ".env")

# LLM 配置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")

# 创作参数
SEGMENT_LENGTH = 300          # 每轮片段字数
OPTIONS_COUNT = 3             # 选项数量（不含自由输入）
MAX_INTERNAL_ITERATIONS = 3   # Critic 内部最大循环
PASS_THRESHOLD = 6            # Critic 通过阈值（满分10）

# LLM 温度
TEMPERATURE_CREATIVE = 0.8    # 创作温度
TEMPERATURE_CRITIC = 0.3      # Critic 温度

# MCP Bing 搜索配置
MCP_BING_ENABLED = os.getenv("MCP_BING_ENABLED", "true").lower() == "true"

# 其他
MAX_TOKENS = 2048             # 单次最大 token
MAX_BACKTRACK_STEPS = 5       # 最大回溯步数