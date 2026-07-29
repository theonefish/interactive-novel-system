"""内部质控 - 设定一致性检查和选项风险标注"""

import json
import re

from langgraph.types import interrupt

from src.graph.state import NovelState
from src.utils.llm import llm_call
from src.utils.config import TEMPERATURE_CRITIC, PASS_THRESHOLD
from src.prompts.reviewer_prompt import CRITIC_PROMPT


def critic_node(state: NovelState) -> dict:
    """质控节点"""
    segment = state.get("current_segment", "")
    if not segment:
        return {"current_phase": "story_progressing"}

    options = state.get("current_options", [])
    options_text = "\n".join(
        f"{o.get('id', '?')}. {o.get('text', '')}（{o.get('risk_level', '未标注')}）"
        for o in options
    ) or "无"

    characters = state.get("characters", [])
    char_text = "\n".join(
        f"{c.get('name', '?')}（{c.get('role', '')}）：{c.get('personality', '')}"
        for c in characters
    ) or "无"

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

    # 解析 JSON
    try:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            data = {}
    except json.JSONDecodeError:
        data = {}

    score = data.get("score", 0)
    passed = data.get("passed", False)
    risk_warnings = data.get("risk_warnings", [])

    # 更新状态
    updates = {
        "critique": data.get("suggestion", ""),
        "critique_score": score,
        "risk_warnings": risk_warnings,
    }

    # 低分 -> 人工审核中断（但达到最大迭代次数时跳过中断，直接放行）
    if not passed and score < PASS_THRESHOLD and state.get("iteration_count", 0) < state.get("max_internal_iterations", 3):
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

        # 中断等待人工审批
        human_feedback = interrupt(review_data)

        if human_feedback == "approved":
            updates["human_approval"] = "approved"
            updates["current_phase"] = "story_progressing"
        else:
            # 驳回：重新生成
            updates["human_approval"] = "rejected"
            updates["current_phase"] = "critic_loop"
            updates["iteration_count"] = state.get("iteration_count", 0) + 1
            updates["critique"] = f"用户驳回，反馈：{human_feedback}"

        return updates

    # 通过或达到最大迭代次数
    if passed or state.get("iteration_count", 0) >= state.get("max_internal_iterations", 3):
        updates["current_phase"] = "story_progressing"
    else:
        updates["current_phase"] = "critic_loop"
        updates["iteration_count"] = state.get("iteration_count", 0) + 1

    return updates