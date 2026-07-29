"""共享状态定义"""

from typing import TypedDict, List, Optional, Annotated, Literal
from langgraph.graph.message import add_messages
from operator import add

from src.tools.memory import MemoryState


class OptionItem(TypedDict):
    """选项结构"""
    id: str
    text: str
    hint: str
    risk_level: str


class UserChoice(TypedDict):
    """用户选择记录"""
    turn_id: int
    choice_type: str
    content: str
    selected_option: Optional[str]


class SegmentHistoryItem(TypedDict):
    """剧情片段历史记录"""
    turn: int
    segment: str
    options: List[OptionItem]


class NovelState(TypedDict):
    """交互式小说创作的全局状态"""
    # 用户输入
    user_request: str

    # 世界观设定
    world_setting: str
    characters: List[dict]
    rules: str
    setting_confirmed: bool

    # 剧情
    story_segments: List[str]
    current_segment: str
    plot_version: int
    segment_history: List[SegmentHistoryItem]

    # 交互
    current_options: List[OptionItem]
    user_choices: List[UserChoice]
    current_turn: int
    awaiting_user: bool

    # 质控
    critique: str
    critique_score: int
    risk_warnings: List[str]

    # 输出
    final_output: str

    # 记忆
    memory: MemoryState

    # LangGraph 消息
    messages: Annotated[list, add_messages]

    # 人工审核（Human-in-the-Loop）
    human_approval: Optional[Literal["pending", "approved", "rejected"]]

    # 控制
    current_phase: str
    iteration_count: int
    max_internal_iterations: int