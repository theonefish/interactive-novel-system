"""剧情推进 - 根据用户选择/输入生成下段叙述和选项
根据上下文、用户输入、角色描述、记忆、参考素材等信息生成下一段叙述和选项
"""

import json
import re

from src.graph.state import NovelState
from src.utils.llm import llm_call
from src.utils.config import TEMPERATURE_CREATIVE, OPTIONS_COUNT, SEGMENT_LENGTH
from src.tools.memory import build_memory_context, _apply_updates, create_initial_memory
from src.tools.rag_tool import retrieve_for_writing
from src.prompts.writer_prompt import STORY_DRIVER_PROMPT
from src.utils.logger import setup_logger

logger = setup_logger("writer")

def story_driver_node(state: NovelState) -> dict:
    """剧情推进节点"""
    turn = state.get("current_turn", 0) + 1
    segments = state.get("story_segments", [])
    user_choices = state.get("user_choices", [])

    # 构建最近3条历史摘要
    story_history = "\n".join(segments[-3:]) if segments else "暂无"

    # 当前上下文
    current_context = ""
    if user_choices:
        last = user_choices[-1]
        current_context = f"用户选择了：{last.get('content', '')}"

    # 构建角色描述
    characters = state.get("characters", [])
    char_text = "\n".join(
        f"{c.get('name', '?')}（{c.get('role', '')}）：{c.get('personality', '')}"
        for c in characters
    ) or "无"

    # 记忆上下文（带滑动窗口裁剪）
    memory = state.get("memory", {})
    memory_context = build_memory_context(memory, current_turn=state.get("current_turn", 0))

    # RAG 检索参考素材
    rag_context = retrieve_for_writing(
        world_setting=state.get("world_setting", ""),
        story_history=story_history,
        current_context=current_context,
        user_input=state.get("user_request", ""),
    )
    if not rag_context:
        rag_context = "（无参考素材）"

    # 构建提示词
    prompt = STORY_DRIVER_PROMPT.format(
        world_setting=state.get("world_setting", ""),
        characters=char_text,
        rules=state.get("rules", ""),
        memory_context=memory_context,
        rag_context=rag_context,
        story_history=story_history,
        current_context=current_context,
        user_input=state.get("user_request", ""),
        segment_length=SEGMENT_LENGTH,# 段落长度
        options_count=OPTIONS_COUNT,# 选项数量
    )
    # 调用 LLM 生成剧情片段
    response = llm_call(
        system_prompt=prompt,
        user_prompt=f"第{turn}轮剧情：继续推进故事。",
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

    segment = data.get("segment", "")
    options = data.get("options", [])
    memory_updates = data.get("memory_updates", {})

    # 确保 options 有唯一 id
    for i, opt in enumerate(options):
        if not opt.get("id"):
            opt["id"] = chr(65 + i)  # A, B, C...

    # 更新状态
    new_segments = list(segments)
    if segment:
        new_segments.append(segment)

    # 记录历史（用于回溯）
    segment_history = list(state.get("segment_history", []))
    if segment:
        segment_history.append({
            "turn": turn,
            "segment": segment,
            "options": options,
        })

    # 更新记忆（合并 LLM 已生成的 memory_updates）
    memory = state.get("memory", {})
    if not memory:
        memory = create_initial_memory(state.get("characters", []))
    if segment and memory_updates:
        memory = _apply_updates(memory, memory_updates, turn)

    return {
        "story_segments": new_segments,
        "current_segment": segment,
        "current_options": options,
        "current_turn": turn,
        "current_phase": "story_progressing",
        "awaiting_user": True,
        "segment_history": segment_history,
        "memory": memory,
    }