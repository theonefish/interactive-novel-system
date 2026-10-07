"""世界观构建 - 生成设定、角色和开场场景
以用户输入内容为主，调用 Bing 搜索收集背景资料，作为辅助生成设定、角色和开场场景
"""

from src.graph.state import NovelState
from src.utils.llm import llm_call
from src.utils.config import TEMPERATURE_CREATIVE, TEMPERATURE_CRITIC
from src.prompts.researcher_prompt import WORLD_BUILDER_PROMPT
from src.utils.json_parse import parse_json_response
from src.tools.search_tool import search_for_world_building
from src.utils.logger import setup_logger

logger = setup_logger("researcher")

def world_builder_node(state: NovelState) -> dict:
    """世界观构建节点"""
    user_request = state.get("user_request", "")
    if not user_request:
        return {"current_phase": "done"}

    # 调用 Bing 搜索收集背景资料
    search_results = search_for_world_building(user_request) # 调用搜索工具
    if search_results:
        search_context = f"【搜索参考资料】\n{search_results}"
    else:
        search_context = ""# 没有搜索结果时，search_context 为空字符串
    # 上一次设定被驳回时，把反馈带回给模型，避免原样重生成同样的设定
    revision_feedback = state.get("critique", "")
    revision_block = (
        f"【上一次驳回反馈（必须针对性修改）】\n{revision_feedback}"
        if revision_feedback else ""
    )
    # 调用 LLM 生成设定、角色和开场场景
    prompt = WORLD_BUILDER_PROMPT.format(
        user_request=user_request,
        search_context=search_context,
        revision_feedback=revision_block,
    )
    # 调用 LLM 生成设定、角色和开场场景
    response = llm_call(
        system_prompt=prompt,
        user_prompt=f"为用户需求「{user_request}」构建世界观。",
        temperature=TEMPERATURE_CREATIVE,
        # 该模型会先输出 reasoning_content，加上检索资料后的 prompt 较长，
        # 2048 容易被截断成不完整 JSON，这里留足余量。
        max_tokens=4096,
        node="world_builder",
    )

    # 解析 JSON（兼容代码围栏 / 前后说明文字 / 被截断的输出）
    data = parse_json_response(response, logger)
    if not data.get("world_setting"):
        logger.warning("[world_builder] 未拿到 world_setting，本次世界观构建视为失败")

    return {
        "world_setting": data.get("world_setting", ""),
        "characters": data.get("characters", []),
        "rules": data.get("rules", ""),
        "current_phase": "world_building",
        "setting_confirmed": False,
        "current_turn": 0,
    }