"""调度中心 - 解析用户输入并路由到对应节点"""

import json
import re

from src.graph.state import NovelState
from src.utils.llm import llm_call
from src.utils.config import TEMPERATURE_CRITIC, MAX_BACKTRACK_STEPS
from src.prompts.supervisor_prompt import ROUTE_PROMPT


def parse_user_input(user_input: str, phase: str) -> dict:
    """解析用户输入"""
    user_input = user_input.strip()

    # 特殊指令（优先级最高）
    if user_input in ("生成全文", "结束"):
        return {"action": "generate_full", "selected_option": None}
    if user_input in ("回到上一步", "回溯"):
        return {"action": "backtrack", "selected_option": None}

    if phase == "world_building":
        if user_input.upper() == "A":
            return {"action": "confirm_setting", "selected_option": None}
        if user_input.upper() == "B":
            return {"action": "modify_setting", "selected_option": None}

    # 通用选项选择
    if user_input.upper() in ("A", "B", "C", "D"):
        return {"action": "select_option", "selected_option": user_input.upper()}

    # 兜底：LLM 解析
    prompt = ROUTE_PROMPT.format(phase=phase, user_input=user_input)
    response = llm_call(
        system_prompt=prompt,
        user_prompt=f"用户输入：{user_input}\n当前阶段：{phase}",
        temperature=TEMPERATURE_CRITIC,
        max_tokens=256,
    )

    try:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except (json.JSONDecodeError, KeyError):
        pass

    return {"action": "free_input", "selected_option": None}


def handle_backtrack(state: NovelState) -> dict:
    """处理回溯请求"""
    segment_history = state.get("segment_history", [])
    if not segment_history:
        return {"current_phase": "story_progressing"}

    # 只允许在第一轮之后回溯
    if state.get("current_turn", 0) <= 1:
        return {"current_phase": "story_progressing"}

    # 限制回溯步数
    steps_used = len(segment_history)
    if steps_used >= MAX_BACKTRACK_STEPS:
        return {"current_phase": "story_progressing"}

    # 弹出最后一段
    segment_history = list(segment_history)
    last_item = segment_history.pop()

    # 恢复状态
    segments = state.get("story_segments", [])
    new_segments = list(segments)
    if new_segments:
        new_segments.pop()

    return {
        "segment_history": segment_history,
        "story_segments": new_segments,
        "current_segment": segment_history[-1]["segment"] if segment_history else "",
        "current_options": segment_history[-1]["options"] if segment_history else [],
        "current_turn": state.get("current_turn", 1) - 1,
        "current_phase": "story_progressing",
        "awaiting_user": True,
    }


def supervisor_node(state: NovelState) -> dict:
    """调度中心节点"""
    phase = state.get("current_phase", "init")
    updates = {}

    if phase == "init":
        updates["current_phase"] = "world_building"
        return updates

    elif phase == "world_building":
        updates["awaiting_user"] = True
        return updates

    elif phase == "story_progressing":
        # 检查是否需要生成全文
        user_choices = state.get("user_choices", [])
        if user_choices:
            last = user_choices[-1]
            if last.get("choice_type") == "generate_full":
                updates["current_phase"] = "completed"
                return updates

        updates["awaiting_user"] = True
        return updates

    elif phase == "completed":
        updates["current_phase"] = "done"
        return updates

    return updates


def supervisor_route(state: NovelState) -> str:
    """条件路由 - 根据当前阶段决定下一个节点"""
    phase = state.get("current_phase", "init")

    if phase == "init":
        return "world_builder"

    if phase == "world_building":
        if state.get("setting_confirmed", False):
            return "story_driver"
        return "supervisor"

    if phase == "story_progressing":
        return "story_driver"

    if phase == "critic_loop":
        approval = state.get("human_approval", None)
        if approval == "rejected":
            return "story_driver"
        return "critic"

    if phase == "completed":
        return "integrator"

    if phase == "done":
        return "END"

    return "supervisor"