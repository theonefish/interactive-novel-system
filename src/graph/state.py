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
    plot_version: int # 剧情版本
    segment_history: List[SegmentHistoryItem] # 剧情片段历史记录

    # 交互
    current_options: List[OptionItem] # 当前选项
    user_choices: List[UserChoice] # 用户选择记录
    current_turn: int # 当前轮次
    awaiting_user: bool # 是否等待用户输入

    # 质控
    critique: str # 质控内容
    critique_score: int # 质控分数
    risk_warnings: List[str] #风险警告

    # 输出
    final_output: str

    # 记忆
    memory: MemoryState    # 记忆状态

    # LangGraph 消息
    messages: Annotated[list, add_messages] # 消息列表

    # 人工审核（Human-in-the-Loop）
    human_approval: Optional[Literal["pending", "approved", "rejected"]]#记录用户批准/驳回，驱动打回或放行

    # 控制
    current_phase: str #
    iteration_count: int # 当前迭代次数
    max_internal_iterations: int # 最大迭代次数