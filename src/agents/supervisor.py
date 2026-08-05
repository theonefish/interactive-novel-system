"""调度中心 - 解析用户输入并路由到对应节点"""
# 核心职责是：
# 解析用户输入（理解意图）、
# 管理小说生成状态（回溯、生成全文、选项选择）、
# 以及进行节点路由（决定下一步由哪一个 Agent/节点执行）。
import json
import re
from typing import Optional

from langgraph.graph import END
from langgraph.types import interrupt

from src.graph.state import NovelState
from src.utils.llm import llm_call
from src.utils.config import TEMPERATURE_CRITIC, MAX_BACKTRACK_STEPS
from src.prompts.supervisor_prompt import ROUTE_PROMPT
from src.utils.logger import setup_logger

logger = setup_logger("supervisor")

# 全局规则定义与关键词匹配，可以快速决策，节省成本
COMMON_RULES = [
    (r"继续|然后呢|下一步|接着说", {"action": "select_option", "selected_option": "A"}),
    (r"不行|换一个|重来|不好|不要|算了", {"action": "backtrack", "selected_option": None}),
    (r"写完整|全部|完本|完结", {"action": "generate_full", "selected_option": None}),
    (r"确认|可以|就这样|没问题|很好", {"action": "free_input", "selected_option": None}),
]


def parse_user_input(user_input: str, phase: str) -> dict:
    """解析用户输入，采用多级降级策略"""
    user_input = user_input.strip()

    # 特殊指令（优先级最高）
    if user_input in ("生成全文", "结束"):
        return {"action": "generate_full", "selected_option": None}
    if user_input in ("回到上一步", "回溯"):
        return {"action": "backtrack", "selected_option": None}

    # 世界观构建阶段的 A/B 确认
    if phase == "world_building":
        if user_input.upper() == "A":
            return {"action": "confirm_setting", "selected_option": None}
        if user_input.upper() == "B":
            return {"action": "modify_setting", "selected_option": None}

    # 通用选项选择（不区分阶段）
    if user_input.upper() in ("A", "B", "C", "D"):
        return {"action": "select_option", "selected_option": user_input.upper()}

    # 关键词规则匹配
    for pattern, result in COMMON_RULES:
        if re.search(pattern, user_input):
            return result

    # 兜底：LLM 解析
    prompt = ROUTE_PROMPT.format(phase=phase, user_input=user_input)
    response = llm_call(
        system_prompt=prompt,
        user_prompt=f"用户输入：{user_input}\n当前阶段：{phase}",
        temperature=TEMPERATURE_CRITIC,
        max_tokens=256,
    )
    # 最后一道结构化解析尝试，失败就降级为自由输入，保证函数永远返回一个可用的路由结果，不会崩溃
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
    # 无历史、首轮、或已达回溯上限时，保持剧情推进、不回溯
    if (not segment_history
            or state.get("current_turn", 0) <= 1
            or len(segment_history) >= MAX_BACKTRACK_STEPS):
        return {"current_phase": "story_progressing"}

    # 弹出最后一段并恢复状态
    segment_history = list(segment_history)
    segment_history.pop()

    # 同步回退剧情段列表
    new_segments = list(state.get("story_segments", []))
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


def _get_resume_input(state: NovelState) -> Optional[str]:
    """获取用户输入（支持 Command(resume=...) 或直接 state['user_input']）"""
    """屏蔽了 LangGraph 中断恢复（__resume__）和自定义字段（user_input / resume）两种来源的差别，
    按优先级取出并转成字符串；用 is not None 正确保留合法的空字符串输入，
    取不到则返回 None 让上层改走中断等待。"""
    for key in ("user_input", "__resume__", "resume"):
        value = state.get(key)
        if value is not None:
            return str(value)
    return None


def _apply_user_choice(state: NovelState, user_input: str) -> dict:
    """解析用户输入并更新选择记录"""
    phase = state.get("current_phase", "story_progressing")  # 取出当前所处的阶段，缺省当作剧情推进中
    parsed = parse_user_input(user_input, phase)  # 把用户输入字符串解析成结构化指令（含 action 等字段）

    choice_type = parsed["action"]  # 取出解析后的动作类型，用于后续分支判断
    selected_option = parsed.get("selected_option")  # 取出被选中的选项（A/B/C 等），可能没有则为 None

    if choice_type == "backtrack":  # 若用户要求回溯
        return handle_backtrack(state)  # 交给回溯处理函数，直接回退历史并短路返回

    if choice_type == "generate_full":  # 若用户要求生成全文（整合输出）
        return {"current_phase": "completed"}  # 仅把阶段置为已完成，让路由去整合节点，不做普通选择记录

    new_choice = {  # 组装一条本轮用户选择记录
        "turn_id": state.get("current_turn", 0),  # 用当前轮次标记，方便回溯/整合时按轮回放
        "choice_type": choice_type,  # 记录解析出的动作类型
        "content": user_input,  # 保留用户原始输入文本
        "selected_option": selected_option,  # 记录被选中的选项（可能为 None）
    }

    user_choices = list(state.get("user_choices", []))  # 复制原有选择列表，避免修改不可变 state
    user_choices.append(new_choice)  # 把本轮选择追加进去

    return {  # 返回对 state 的更新
        "user_choices": user_choices,  # 更新后的选择历史
        "awaiting_user": False,  # 已收到并处理输入，不再等待用户
        "current_phase": "story_progressing",  # 保持剧情推进中，路由到 story_driver 生成下一段
    }


def supervisor_node(state: NovelState) -> dict:
    """调度中心节点"""
    phase = state.get("current_phase", "init")
    logger.info(f"[supervisor_node] 进入 phase={phase} awaiting_user={state.get('awaiting_user')} choices={len(state.get('user_choices', []))}")

    # 优先处理已传入的用户输入（直接 state['user_input'] 或 Command(resume=...)）
    direct_input = _get_resume_input(state)
    if direct_input and phase in ("story_progressing", "world_building", "critic_loop"):
        return _apply_user_choice(state, direct_input)

    updates = {}

    if phase == "init":
        # 交由条件路由进入 world_builder，不在此修改状态
        logger.info("[supervisor_node] phase=init，移交路由进入 world_builder")
        return {}

    elif phase == "world_building":
        # critic 已通过设定审查，进入剧情推进
        updates["setting_confirmed"] = True
        updates["current_phase"] = "story_progressing"
        return updates

    elif phase == "story_progressing":
        # 检查是否需要生成全文
        user_choices = state.get("user_choices", [])
        if user_choices:
            last = user_choices[-1]
            if last.get("choice_type") == "generate_full":
                updates["current_phase"] = "completed"
                return updates

        # 无选项意味着需要生成新剧情：
        # - 新会话刚进入此阶段（无 segment 无 options）
        # - 续写会话（保留了原 segment 作为上下文，但清空了 options）
        # 两种情况都先路由到 story_driver 生成新剧情和选项
        if not state.get("current_options"):
            logger.info("[supervisor_node] story_progressing 无选项，移交 story_driver 生成新剧情")
            return {}

        # 已有剧情和选项，通过 interrupt 等待用户输入
        options = state.get("current_options", [])
        options_text = "\n".join(
            f"{opt.get('id', '?')}. {opt.get('text', '')}" for opt in options
        ) or "无选项"

        user_input = interrupt({
            "message": "请做出选择或自由输入",
            "options": options,
            "hint": options_text,
        })

        # 恢复后继续处理用户输入
        return _apply_user_choice(state, str(user_input))

    elif phase == "completed":
        updates["current_phase"] = "done"
        return updates

    return updates


def critic_route(state: NovelState) -> str:
    """critic 节点后的条件路由"""
    phase = state.get("current_phase", "story_progressing")
    segment = state.get("current_segment", "")
    is_setting_review = not segment and bool(state.get("world_setting", ""))

    if is_setting_review:
        # 设定审查：未通过则打回 world_builder，通过则进入剧情
        if phase == "critic_loop":
            return "world_builder"
        return "story_driver"

    # 剧情审查：未通过则打回 story_driver，通过则返回 supervisor 等待用户
    if phase == "critic_loop":
        return "story_driver"

    return "supervisor"


def supervisor_route(state: NovelState) -> str:
    """条件路由 - 根据当前阶段决定下一个节点"""
    phase = state.get("current_phase", "init")
    logger.info(f"[supervisor_route] 路由决策 phase={phase} "
                f"setting_confirmed={state.get('setting_confirmed')} "
                f"awaiting_user={state.get('awaiting_user')} "
                f"has_world={bool(state.get('world_setting'))}")

    if phase == "init":
        return "world_builder"

    if phase == "world_building":
        # 设定已确认 → 进入剧情；尚未构建世界观 → 继续构建；已构建未确认 → 交回 supervisor 等待确认
        if state.get("setting_confirmed", False):
            return "story_driver"
        if not state.get("world_setting"):
            return "world_builder"
        return "supervisor"

    if phase == "story_progressing":
        # 已生成剧情并等待用户输入：回到 supervisor，在其 interrupt 处暂停，
        # 这样 action/stream 端点才能用 Command(resume=...) 恢复。
        if state.get("awaiting_user", False):
            return "supervisor"
        # 已收到用户输入，或续写新会话刚启动时继续生成剧情
        return "story_driver"

    if phase == "critic_loop":
        approval = state.get("human_approval", None)
        if approval == "rejected":
            return "story_driver"
        return "critic"

    if phase == "completed":
        return "integrator"

    if phase == "done":
        return END

    return "supervisor"