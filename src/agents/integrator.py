"""整合输出 - 拼接所有片段并润色输出完整小说"""

import json
import re

from src.graph.state import NovelState
from src.utils.llm import llm_call
from src.utils.config import TEMPERATURE_CREATIVE
from src.prompts.integrator_prompt import INTEGRATOR_PROMPT


def integrator_node(state: NovelState) -> dict:
    """整合输出节点"""
    segments = state.get("story_segments", [])
    if not segments:
        return {"current_phase": "done", "final_output": "暂无内容。"}

    choices = state.get("user_choices", [])
    choices_text = "\n".join(
        f"第{c.get('turn_id', '?')}轮：{c.get('content', '')}"
        for c in choices
    ) or "无"

    characters = state.get("characters", [])
    char_text = "\n".join(
        f"{c.get('name', '?')}（{c.get('role', '')}）：{c.get('personality', '')}"
        for c in characters
    ) or "无"

    segments_text = "\n\n---\n\n".join(
        f"第{i+1}段\n{s}"
        for i, s in enumerate(segments)
    )

    prompt = INTEGRATOR_PROMPT.format(
        world_setting=state.get("world_setting", ""),
        characters=char_text,
        segments=segments_text,
        choices=choices_text,
    )

    response = llm_call(
        system_prompt=prompt,
        user_prompt="请整合所有剧情片段，输出完整小说。",
        temperature=TEMPERATURE_CREATIVE,
        max_tokens=4096,
    )

    return {
        "final_output": response,
        "current_phase": "completed",
    }