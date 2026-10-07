"""内部质控 - 设定一致性检查和选项风险标注

两道关卡：
1. critic_node：调用模型打分，把结果写进 state（含是否需要人工审核）；
2. review_gate_node：只负责 interrupt 等用户 —— 单独一个节点，
   这样「恢复中断」时不会再把同一段内容送进模型审第二遍（省一次 token，也避免评分漂移）。

审核节奏：默认每 CRITIC_EVERY_N_TURNS 轮审一次（第 1、3、5… 轮），
高风险选项与用户主动「重新生成」时强制审核。
"""

from langgraph.types import interrupt

from src.graph.state import NovelState
from src.utils.llm import llm_call
from src.utils.config import (
    TEMPERATURE_CRITIC, PASS_THRESHOLD, CRITIC_MODEL,
    CRITIC_EVERY_N_TURNS, MAX_CHARACTERS_IN_PROMPT,
)
from src.prompts.reviewer_prompt import CRITIC_PROMPT
from src.utils.json_parse import parse_json_response
from src.utils.prompt_utils import format_characters
from src.utils.logger import setup_logger

logger = setup_logger("reviewer")

# 视为「高风险」的选项标注（模型可能输出中文或英文）
HIGH_RISK_LEVELS = {"高风险", "危险", "high", "risky", "high_risk"}


def _parse_critic_response(response: str) -> dict:
    """解析 critic LLM 返回的 JSON（兼容代码围栏 / 前后说明文字 / 被截断的输出）"""
    return parse_json_response(response, logger)


def _rollback_last_segment(state: NovelState) -> dict:
    """驳回重写时回滚上一次生成的剧情片段。

    剧情是在 critic 审查之前就写进 state 的，若审查驳回而不回滚，
    被废弃的片段会留在 story_segments / segment_history 里，
    导致重写后出现重复内容、轮次虚增。
    只有末条历史的轮次正好等于当前轮次时才回滚，避免重复弹出。
    """
    turn = state.get("current_turn", 0)
    segments = list(state.get("story_segments", []))
    history = list(state.get("segment_history", []))

    if not history or history[-1].get("turn") != turn:
        return {}

    history.pop()
    if segments:
        segments.pop()

    return {
        "story_segments": segments,
        "segment_history": history,
        "current_turn": max(turn - 1, 0),
    }


def _last_selected_option(state: NovelState) -> dict:
    """取用户最近一次选择所对应的那个选项（用于判断风险等级）。

    注意：选项 id 每轮都会重置成 A/B/C，不能只看 current_options（那是本轮新生成的
    选项，用户还没见过）。用户选择时记录里的 turn_id 指向他当时看到的那一段，
    按 turn_id 回历史里取对应选项才是准确的。
    """
    choices = state.get("user_choices") or []
    if not choices:
        return {}

    last = choices[-1]
    selected = last.get("selected_option")
    if not selected:
        return {}
    selected = str(selected).upper()

    turn_id = last.get("turn_id")
    for item in state.get("segment_history") or []:
        if item.get("turn") != turn_id:
            continue
        for option in item.get("options") or []:
            if str(option.get("id", "")).upper() == selected:
                return option
        break

    # 兜底：历史里找不到时再看当前选项（例如首轮或历史被清空）
    for option in state.get("current_options") or []:
        if str(option.get("id", "")).upper() == selected:
            return option
    return {}


def _is_regenerate_request(state: NovelState) -> bool:
    """用户最近一次操作是不是「重新生成剧情」。"""
    choices = state.get("user_choices") or []
    return bool(choices) and choices[-1].get("choice_type") == "regenerate"


def should_review_segment(state: NovelState) -> bool:
    """这一段是否需要送 critic 审核（省 token 的核心开关）。"""
    if _last_selected_option(state).get("risk_level") in HIGH_RISK_LEVELS:
        logger.info("[should_review_segment] 高风险选项 → 强制审核")
        return True
    if _is_regenerate_request(state):
        logger.info("[should_review_segment] 用户主动重写 → 强制审核")
        return True

    every_n = max(CRITIC_EVERY_N_TURNS, 1)
    turn = state.get("current_turn", 0)
    return (turn - 1) % every_n == 0


def build_setting_review_payload(state: NovelState, data: dict) -> dict:
    """组装「设定低分」审核载荷（给用户看，不发给模型）。"""
    return {
        "kind": "setting_review",
        "question": "这个世界观设定质量较低，需要你审核确认。",
        "segment": state.get("world_setting", ""),
        "score": data.get("score", 0),
        "issues": data.get("issues", []),
        "suggestion": data.get("suggestion", ""),
        "options": [
            {"id": "approved", "text": "批准，继续使用这个设定"},
            {"id": "rejected", "text": "驳回，要求重新生成设定"},
        ],
    }


def build_segment_review_payload(state: NovelState, data: dict) -> dict:
    """组装「剧情低分」审核载荷（给用户看，不发给模型）。"""
    return {
        "kind": "segment_review",
        "question": "这段剧情质量评分较低，需要你审核确认。",
        "segment": state.get("current_segment", ""),
        "score": data.get("score", 0),
        "issues": data.get("issues", []),
        "suggestion": data.get("suggestion", ""),
        "options": [
            {"id": "approved", "text": "批准，继续使用这段剧情"},
            {"id": "rejected", "text": "驳回，要求重写"},
        ],
    }


def apply_human_review(state: NovelState, human_feedback) -> dict:
    """把用户对审核的答复落成状态更新（设定审核 / 剧情审核共用）。"""
    kind = (state.get("pending_review") or {}).get("kind")
    approved = str(human_feedback).strip() == "approved"
    iteration_count = state.get("iteration_count", 0)

    if kind == "setting_review":
        if approved:
            # 低分设定被用户批准 = 同时确认设定，不再二次弹窗
            return {
                "human_approval": "approved",
                "current_phase": "story_progressing",
                "setting_confirmed": True,
                "iteration_count": 0,
                "pending_review": None,
            }
        return {
            "human_approval": "rejected",
            "current_phase": "critic_loop",
            "iteration_count": iteration_count + 1,
            "critique": f"用户驳回设定，反馈：{human_feedback}",
            "setting_confirmed": False,
            "pending_review": None,
        }

    if approved:
        return {
            "human_approval": "approved",
            "current_phase": "story_progressing",
            "iteration_count": 0,
            "pending_review": None,
        }

    updates = {
        "human_approval": "rejected",
        "current_phase": "critic_loop",
        "iteration_count": iteration_count + 1,
        "critique": f"用户驳回，反馈：{human_feedback}",
        "pending_review": None,
    }
    updates.update(_rollback_last_segment(state))
    return updates


def review_gate_node(state: NovelState) -> dict:
    """人工审核闸门：只做 interrupt，不调用模型。

    以前 interrupt() 直接写在 critic 节点里，LangGraph 恢复时会重跑整个节点，
    同一段内容被审两遍（多一次 token，分数还会漂移）。拆开后 critic 只算一次。
    """
    payload = state.get("pending_review") or {}
    if not payload:
        logger.warning("[review_gate] 没有待审核内容，直接放行")
        return {"current_phase": "story_progressing", "pending_review": None}

    human_feedback = interrupt(payload)
    logger.info(f"[review_gate] 用户审核 kind={payload.get('kind')} -> {human_feedback!r}")
    return apply_human_review(state, human_feedback)


def _review_setting(state: NovelState) -> dict:
    """审查世界观设定"""
    iteration_count = state.get("iteration_count", 0)
    max_iterations = state.get("max_internal_iterations", 3)
    effective_threshold = max(PASS_THRESHOLD - iteration_count, 1)

    prompt = CRITIC_PROMPT.format(
        world_setting=state.get("world_setting", ""),
        characters=format_characters(state.get("characters", []), MAX_CHARACTERS_IN_PROMPT),
        rules=state.get("rules", ""),
        segment="（世界观设定审查：请检查设定是否自洽、合规、有吸引力）",
        options="无",
        pass_threshold=effective_threshold,
    )

    response = llm_call(
        system_prompt=prompt,
        user_prompt="请评审世界观设定。",
        temperature=TEMPERATURE_CRITIC,
        max_tokens=1024,
        model=CRITIC_MODEL or None,
        node="critic",
    )
    data = _parse_critic_response(response)
    score = data.get("score", 0)
    passed = data.get("passed", False)

    updates = {
        "critique": data.get("suggestion", ""),
        "critique_score": score,
        "risk_warnings": data.get("risk_warnings", []),
    }

    # 低分 → 挂起等用户审核（由 review_gate 负责 interrupt）
    if not passed and score < effective_threshold and iteration_count < max_iterations:
        updates["current_phase"] = "review_pending"
        updates["pending_review"] = build_setting_review_payload(state, data)
        return updates

    # 通过或达到最大迭代次数：交回 supervisor 做「世界观确认」，不再自动放行
    updates["setting_confirmed"] = False
    if passed or iteration_count >= max_iterations:
        updates["current_phase"] = "world_building"
        updates["iteration_count"] = 0
    else:
        updates["current_phase"] = "critic_loop"
        updates["iteration_count"] = iteration_count + 1
    return updates


def _review_segment(state: NovelState) -> dict:
    """审查剧情片段"""
    iteration_count = state.get("iteration_count", 0)
    max_iterations = state.get("max_internal_iterations", 3)
    effective_threshold = max(PASS_THRESHOLD - iteration_count, 1)

    segment = state.get("current_segment", "")
    options = state.get("current_options", [])
    options_text = "\n".join(
        f"{o.get('id', '?')}. {o.get('text', '')}（{o.get('risk_level', '未标注')}）"
        for o in options
    ) or "无"

    prompt = CRITIC_PROMPT.format(
        world_setting=state.get("world_setting", ""),
        characters=format_characters(state.get("characters", []), MAX_CHARACTERS_IN_PROMPT),
        rules=state.get("rules", ""),
        segment=segment,
        options=options_text,
        pass_threshold=effective_threshold,
    )

    response = llm_call(
        system_prompt=prompt,
        user_prompt="请评审最新剧情片段。",
        temperature=TEMPERATURE_CRITIC,
        max_tokens=1024,
        model=CRITIC_MODEL or None,
        node="critic",
    )
    data = _parse_critic_response(response)
    score = data.get("score", 0)
    passed = data.get("passed", False)

    updates = {
        "critique": data.get("suggestion", ""),
        "critique_score": score,
        "risk_warnings": data.get("risk_warnings", []),
    }

    # 低分 → 挂起等用户审核（由 review_gate 负责 interrupt）
    if not passed and score < effective_threshold and iteration_count < max_iterations:
        updates["current_phase"] = "review_pending"
        updates["pending_review"] = build_segment_review_payload(state, data)
        return updates

    # 通过或达到最大迭代次数：放行并重置本轮审查计数
    if passed or iteration_count >= max_iterations:
        updates["current_phase"] = "story_progressing"
        updates["iteration_count"] = 0
    else:
        updates["current_phase"] = "critic_loop"
        updates["iteration_count"] = iteration_count + 1
        updates.update(_rollback_last_segment(state))
    return updates


def critic_node(state: NovelState) -> dict:
    """质控节点：根据当前状态审查设定或剧情片段"""
    segment = state.get("current_segment", "")
    has_world = bool(state.get("world_setting", ""))

    if not segment and has_world:
        return _review_setting(state)

    if not segment:
        # 既没有剧情也没有世界观：说明 world_builder 这次没拿到可用设定
        # （模型输出被截断 / 带代码围栏 / 解析失败）。绝不能带着空世界观直接写剧情，
        # 否则前端根本看不到「世界观确认」这一步。这里打回重做，超过上限才报错。
        iteration_count = state.get("iteration_count", 0)
        max_iterations = state.get("max_internal_iterations", 3)
        logger.warning(f"[critic_node] 世界观为空，重试构建 (iteration={iteration_count}/{max_iterations})")

        if iteration_count < max_iterations:
            return {
                "current_phase": "critic_loop",
                "iteration_count": iteration_count + 1,
                "critique": "世界观构建未返回有效设定，正在重新构建。",
            }
        return {
            "current_phase": "done",
            "error": "世界观构建失败：模型多次未返回可解析的设定，请重试或更换模型。",
        }

    # 按节奏决定是否审核这一段（高风险选项与手动重写强制审）
    if not should_review_segment(state):
        logger.info(f"[critic_node] 第 {state.get('current_turn')} 轮按节奏跳过审核（每 {CRITIC_EVERY_N_TURNS} 轮审一次）")
        return {"current_phase": "story_progressing"}

    return _review_segment(state)
