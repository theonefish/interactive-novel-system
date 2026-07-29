"""内部质控 - 设定一致性检查和选项风险标注"""

import json
import re

from langgraph.types import interrupt

from src.graph.state import NovelState
from src.utils.llm import llm_call
from src.utils.config import TEMPERATURE_CRITIC, PASS_THRESHOLD
from src.prompts.reviewer_prompt import CRITIC_PROMPT


def _format_characters(characters: list) -> str:
    """格式化角色信息"""
    return "\n".join(
        f"{c.get('name', '?')}（{c.get('role', '')}）：{c.get('personality', '')}"
        for c in characters
    ) or "无"


def _parse_critic_response(response: str) -> dict:
    """解析 critic LLM 返回的 JSON"""
    try:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except json.JSONDecodeError:
        pass
    return {}


def _review_setting(state: NovelState) -> dict:
    """审查世界观设定"""
    characters = state.get("characters", [])
    char_text = _format_characters(characters)

    prompt = CRITIC_PROMPT.format(
        world_setting=state.get("world_setting", ""),
        characters=char_text,
        rules=state.get("rules", ""),
        segment="（世界观设定审查：请检查设定是否自洽、合规、有吸引力）",
        options="无",
        pass_threshold=PASS_THRESHOLD,
    )

    response = llm_call(
        system_prompt=prompt,
        user_prompt="请评审世界观设定。",
        temperature=TEMPERATURE_CRITIC,
        max_tokens=1024,
    )

    data = _parse_critic_response(response)
    score = data.get("score", 0)
    passed = data.get("passed", False)

    updates = {
        "critique": data.get("suggestion", ""),
        "critique_score": score,
        "risk_warnings": data.get("risk_warnings", []),
    }

    iteration_count = state.get("iteration_count", 0)
    max_iterations = state.get("max_internal_iterations", 3)

    # 低分 -> 人工审核中断（达到最大迭代次数时直接放行）
    if not passed and score < PASS_THRESHOLD and iteration_count < max_iterations:
        review_data = {
            "question": "这个世界观设定质量较低，需要你审核确认。",
            "segment": state.get("world_setting", ""),
            "score": score,
            "issues": data.get("issues", []),
            "suggestion": data.get("suggestion", ""),
            "options": [
                {"id": "approved", "text": "批准，继续使用这个设定"},
                {"id": "rejected", "text": "驳回，要求重新生成设定"},
            ],
        }

        human_feedback = interrupt(review_data)

        if human_feedback == "approved":
            updates["human_approval"] = "approved"
            updates["current_phase"] = "story_progressing"
            updates["setting_confirmed"] = True
        else:
            updates["human_approval"] = "rejected"
            updates["current_phase"] = "critic_loop"
            updates["iteration_count"] = iteration_count + 1
            updates["critique"] = f"用户驳回设定，反馈：{human_feedback}"
            updates["setting_confirmed"] = False

        return updates

    if passed or iteration_count >= max_iterations:
        updates["current_phase"] = "story_progressing"
        updates["setting_confirmed"] = True
    else:
        updates["current_phase"] = "critic_loop"
        updates["iteration_count"] = iteration_count + 1
        updates["setting_confirmed"] = False

    return updates


def _review_segment(state: NovelState) -> dict:
    """审查剧情片段"""
    segment = state.get("current_segment", "")
    options = state.get("current_options", [])
    options_text = "\n".join(
        f"{o.get('id', '?')}. {o.get('text', '')}（{o.get('risk_level', '未标注')}）"
        for o in options
    ) or "无"

    characters = state.get("characters", [])
    char_text = _format_characters(characters)

    prompt = CRITIC_PROMPT.format(
        world_setting=state.get("world_setting", ""),
        characters=char_text,
        rules=state.get("rules", ""),
        segment=segment,
        options=options_text,
        pass_threshold=PASS_THRESHOLD,
    )

    response = llm_call(
        system_prompt=prompt,
        user_prompt="请评审最新剧情片段。",
        temperature=TEMPERATURE_CRITIC,
        max_tokens=1024,
    )

    data = _parse_critic_response(response)
    score = data.get("score", 0)
    passed = data.get("passed", False)
    risk_warnings = data.get("risk_warnings", [])

    updates = {
        "critique": data.get("suggestion", ""),
        "critique_score": score,
        "risk_warnings": risk_warnings,
    }

    iteration_count = state.get("iteration_count", 0)
    max_iterations = state.get("max_internal_iterations", 3)

    # 低分 -> 人工审核中断（但达到最大迭代次数时跳过中断，直接放行）
    if not passed and score < PASS_THRESHOLD and iteration_count < max_iterations:
        review_data = {
            "question": "这段剧情质量评分较低，需要你审核确认。",
            "segment": segment,
            "score": score,
            "issues": data.get("issues", []),
            "suggestion": data.get("suggestion", ""),
            "options": [
                {"id": "approved", "text": "批准，继续使用这段剧情"},
                {"id": "rejected", "text": "驳回，要求重写"},
            ],
        }

        human_feedback = interrupt(review_data)

        if human_feedback == "approved":
            updates["human_approval"] = "approved"
            updates["current_phase"] = "story_progressing"
        else:
            updates["human_approval"] = "rejected"
            updates["current_phase"] = "critic_loop"
            updates["iteration_count"] = iteration_count + 1
            updates["critique"] = f"用户驳回，反馈：{human_feedback}"

        return updates

    # 通过或达到最大迭代次数
    if passed or iteration_count >= max_iterations:
        updates["current_phase"] = "story_progressing"
    else:
        updates["current_phase"] = "critic_loop"
        updates["iteration_count"] = iteration_count + 1

    return updates


def critic_node(state: NovelState) -> dict:
    """质控节点：根据当前状态审查设定或剧情片段"""
    segment = state.get("current_segment", "")
    is_setting_review = not segment and bool(state.get("world_setting", ""))

    if is_setting_review:
        return _review_setting(state)

    if not segment:
        return {"current_phase": "story_progressing"}

    return _review_segment(state)