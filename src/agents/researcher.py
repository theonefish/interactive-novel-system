"""世界观构建 - 生成设定、角色和开场场景"""

import json
import re

from src.graph.state import NovelState
from src.utils.llm import llm_call
from src.utils.config import TEMPERATURE_CREATIVE, TEMPERATURE_CRITIC
from src.prompts.researcher_prompt import WORLD_BUILDER_PROMPT
from src.tools.search_tool import search_for_world_building
from src.utils.logger import setup_logger

logger = setup_logger("researcher")
def world_builder_node(state: NovelState) -> dict:
    """世界观构建节点"""
    user_request = state.get("user_request", "")
    if not user_request:
        return {"current_phase": "done"}

    # 调用 Bing 搜索收集背景资料
    search_results = search_for_world_building(user_request)
    if search_results:
        search_context = f"【搜索参考资料】\n{search_results}"
    else:
        search_context = ""

    prompt = WORLD_BUILDER_PROMPT.format(
        user_request=user_request,
        search_context=search_context,
    )
    response = llm_call(
        system_prompt=prompt,
        user_prompt=f"为用户需求「{user_request}」构建世界观。",
        temperature=TEMPERATURE_CREATIVE,
        max_tokens=2048,
    )

    # 解析 JSON
    try:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            data = {}
    except json.JSONDecodeError:
        data = {}

    return {
        "world_setting": data.get("world_setting", ""),
        "characters": data.get("characters", []),
        "rules": data.get("rules", ""),
        "current_phase": "world_building",
        "setting_confirmed": False,
        "current_turn": 0,
    }