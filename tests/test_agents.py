"""Agent 节点测试 - 测试各 Agent 节点的核心逻辑

使用 mock 替换 LLM 调用，避免依赖外部 API。
"""

import pytest
from unittest.mock import patch, MagicMock

from src.graph.state import NovelState
from src.tools.memory import create_initial_memory


# ─── 测试数据 ────────────────────────────────────────

def _make_initial_state(user_request: str = "末日废土，主角带着女儿寻找绿洲") -> NovelState:
    """构建测试用初始状态"""
    return {
        "user_request": user_request,
        "world_setting": "末日废土世界，资源枯竭，人类散居在地下避难所。",
        "characters": [
            {"name": "林远", "personality": "坚韧、冷静", "role": "主角"},
            {"name": "小雨", "personality": "好奇、勇敢", "role": "女儿"},
        ],
        "rules": "1. 水源是硬通货\n2. 夜间不可外出\n3. 信任需要代价",
        "setting_confirmed": True,
        "story_segments": [],
        "current_segment": "",
        "plot_version": 0,
        "segment_history": [],
        "current_options": [],
        "user_choices": [],
        "current_turn": 0,
        "awaiting_user": False,
        "critique": "",
        "critique_score": 0,
        "risk_warnings": [],
        "final_output": "",
        "memory": create_initial_memory([
            {"name": "林远", "personality": "坚韧、冷静", "role": "主角"},
            {"name": "小雨", "personality": "好奇、勇敢", "role": "女儿"},
        ]),
        "messages": [],
        "human_approval": None,
        "current_phase": "init",
        "iteration_count": 0,
        "max_internal_iterations": 3,
    }


# ─── Supervisor 测试 ────────────────────────────────

class TestSupervisorRoute:
    """测试 supervisor_route 路由逻辑"""

    def test_init_phase_routes_to_world_builder(self):
        from src.agents.supervisor import supervisor_route
        state = _make_initial_state()
        state["current_phase"] = "init"
        assert supervisor_route(state) == "world_builder"

    def test_world_building_unconfirmed_routes_to_supervisor(self):
        from src.agents.supervisor import supervisor_route
        state = _make_initial_state()
        state["current_phase"] = "world_building"
        state["setting_confirmed"] = False
        assert supervisor_route(state) == "supervisor"

    def test_world_building_confirmed_routes_to_story_driver(self):
        from src.agents.supervisor import supervisor_route
        state = _make_initial_state()
        state["current_phase"] = "world_building"
        state["setting_confirmed"] = True
        assert supervisor_route(state) == "story_driver"

    def test_story_progressing_routes_to_story_driver(self):
        from src.agents.supervisor import supervisor_route
        state = _make_initial_state()
        state["current_phase"] = "story_progressing"
        assert supervisor_route(state) == "story_driver"

    def test_critic_loop_rejected_routes_to_story_driver(self):
        from src.agents.supervisor import supervisor_route
        state = _make_initial_state()
        state["current_phase"] = "critic_loop"
        state["human_approval"] = "rejected"
        assert supervisor_route(state) == "story_driver"

    def test_critic_loop_no_rejection_routes_to_critic(self):
        from src.agents.supervisor import supervisor_route
        state = _make_initial_state()
        state["current_phase"] = "critic_loop"
        state["human_approval"] = None
        assert supervisor_route(state) == "critic"

    def test_completed_routes_to_integrator(self):
        from src.agents.supervisor import supervisor_route
        state = _make_initial_state()
        state["current_phase"] = "completed"
        assert supervisor_route(state) == "integrator"

    def test_done_routes_to_end(self):
        from src.agents.supervisor import supervisor_route
        state = _make_initial_state()
        state["current_phase"] = "done"
        assert supervisor_route(state) == "END"

    def test_unknown_phase_defaults_to_supervisor(self):
        from src.agents.supervisor import supervisor_route
        state = _make_initial_state()
        state["current_phase"] = "unknown"
        assert supervisor_route(state) == "supervisor"


class TestSupervisorNode:
    """测试 supervisor_node 状态更新"""

    def test_init_phase_sets_world_building(self):
        from src.agents.supervisor import supervisor_node
        state = _make_initial_state()
        state["current_phase"] = "init"
        result = supervisor_node(state)
        assert result["current_phase"] == "world_building"

    def test_completed_transitions_to_done(self):
        from src.agents.supervisor import supervisor_node
        state = _make_initial_state()
        state["current_phase"] = "completed"
        result = supervisor_node(state)
        assert result["current_phase"] == "done"

    def test_story_progressing_with_generate_full_transitions_to_completed(self):
        from src.agents.supervisor import supervisor_node
        state = _make_initial_state()
        state["current_phase"] = "story_progressing"
        state["user_choices"] = [{"choice_type": "generate_full", "content": "生成全文"}]
        result = supervisor_node(state)
        assert result["current_phase"] == "completed"


class TestParseUserInput:
    """测试 parse_user_input 输入解析"""

    def test_select_option_a(self):
        from src.agents.supervisor import parse_user_input
        result = parse_user_input("A", "story_progressing")
        assert result["action"] == "select_option"
        assert result["selected_option"] == "A"

    def test_select_option_b(self):
        from src.agents.supervisor import parse_user_input
        result = parse_user_input("b", "story_progressing")
        assert result["action"] == "select_option"
        assert result["selected_option"] == "B"

    def test_generate_full_command(self):
        from src.agents.supervisor import parse_user_input
        result = parse_user_input("生成全文", "story_progressing")
        assert result["action"] == "generate_full"

    def test_backtrack_command(self):
        from src.agents.supervisor import parse_user_input
        result = parse_user_input("回溯", "story_progressing")
        assert result["action"] == "backtrack"

    def test_confirm_setting_in_world_building(self):
        from src.agents.supervisor import parse_user_input
        result = parse_user_input("A", "world_building")
        assert result["action"] == "confirm_setting"


class TestHandleBacktrack:
    """测试 handle_backtrack 回溯逻辑"""

    def test_backtrack_pops_last_segment(self):
        from src.agents.supervisor import handle_backtrack
        state = _make_initial_state()
        state["current_turn"] = 3
        state["story_segments"] = ["段落1", "段落2", "段落3"]
        state["segment_history"] = [
            {"turn": 1, "segment": "段落1", "options": [{"id": "A", "text": "选项A"}]},
            {"turn": 2, "segment": "段落2", "options": [{"id": "B", "text": "选项B"}]},
            {"turn": 3, "segment": "段落3", "options": [{"id": "C", "text": "选项C"}]},
        ]

        result = handle_backtrack(state)

        assert len(result["segment_history"]) == 2
        assert result["current_turn"] == 2
        assert len(result["story_segments"]) == 2
        assert result["current_segment"] == "段落2"

    def test_backtrack_blocked_on_first_turn(self):
        from src.agents.supervisor import handle_backtrack
        state = _make_initial_state()
        state["current_turn"] = 1
        state["segment_history"] = [
            {"turn": 1, "segment": "段落1", "options": []},
        ]

        result = handle_backtrack(state)
        # 第一轮不允许回溯
        assert result["current_phase"] == "story_progressing"

    def test_backtrack_empty_history_returns_progressing(self):
        from src.agents.supervisor import handle_backtrack
        state = _make_initial_state()
        state["segment_history"] = []

        result = handle_backtrack(state)
        assert result["current_phase"] == "story_progressing"


# ─── Writer 测试 ───────────────────────────────────

class TestStoryDriverNode:
    """测试 story_driver_node 剧情推进"""

    @patch("src.agents.writer.llm_call")
    @patch("src.agents.writer.retrieve_for_writing", return_value="")
    @patch("src.agents.writer.extract_memory_updates")
    def test_story_driver_returns_segment_and_options(self, mock_extract, mock_rag, mock_llm):
        from src.agents.writer import story_driver_node

        mock_llm.return_value = '{"segment": "林远带着小雨穿过荒芜的沙漠。", "options": [{"id": "A", "text": "继续前进", "hint": "可能会遇到危险", "risk_level": "中等"}, {"id": "B", "text": "原地休息", "hint": "恢复体力", "risk_level": "安全"}, {"id": "C", "text": "探索附近", "hint": "可能有发现", "risk_level": "高风险"}]}'
        mock_extract.return_value = create_initial_memory([])

        state = _make_initial_state()
        state["current_phase"] = "story_progressing"

        result = story_driver_node(state)

        assert result["current_segment"] == "林远带着小雨穿过荒芜的沙漠。"
        assert len(result["current_options"]) == 3
        assert result["current_turn"] == 1
        assert result["current_phase"] == "story_progressing"
        assert result["awaiting_user"] is True
        assert len(result["story_segments"]) == 1
        assert len(result["segment_history"]) == 1

    @patch("src.agents.writer.llm_call")
    @patch("src.agents.writer.retrieve_for_writing", return_value="")
    @patch("src.agents.writer.extract_memory_updates")
    def test_story_driver_ensures_option_ids(self, mock_extract, mock_rag, mock_llm):
        from src.agents.writer import story_driver_node

        # LLM 返回的 options 没有 id
        mock_llm.return_value = '{"segment": "剧情片段。", "options": [{"text": "选项1", "hint": "", "risk_level": "安全"}, {"text": "选项2", "hint": "", "risk_level": "中等"}]}'
        mock_extract.return_value = create_initial_memory([])

        state = _make_initial_state()
        result = story_driver_node(state)

        assert result["current_options"][0]["id"] == "A"
        assert result["current_options"][1]["id"] == "B"

    @patch("src.agents.writer.llm_call")
    @patch("src.agents.writer.retrieve_for_writing", return_value="")
    @patch("src.agents.writer.extract_memory_updates")
    def test_story_driver_handles_invalid_json(self, mock_extract, mock_rag, mock_llm):
        from src.agents.writer import story_driver_node

        mock_llm.return_value = "这不是 JSON"
        mock_extract.return_value = create_initial_memory([])

        state = _make_initial_state()
        result = story_driver_node(state)

        assert result["current_segment"] == ""
        assert result["current_options"] == []
        assert result["current_turn"] == 1


# ─── Reviewer 测试 ─────────────────────────────────

class TestCriticNode:
    """测试 critic_node 质控节点"""

    @patch("src.agents.reviewer.llm_call")
    def test_critic_passed_returns_story_progressing(self, mock_llm):
        from src.agents.reviewer import critic_node

        mock_llm.return_value = '{"score": 8, "passed": true, "issues": [], "risk_warnings": [], "suggestion": "良好"}'

        state = _make_initial_state()
        state["current_segment"] = "一段精彩的剧情。"
        state["current_options"] = [{"id": "A", "text": "选项A", "risk_level": "安全"}]

        result = critic_node(state)

        assert result["critique_score"] == 8
        assert result["current_phase"] == "story_progressing"

    @patch("src.agents.reviewer.llm_call")
    def test_critic_low_score_triggers_interrupt(self, mock_llm):
        from src.agents.reviewer import critic_node
        from langgraph.types import interrupt

        mock_llm.return_value = '{"score": 3, "passed": false, "issues": ["剧情矛盾"], "risk_warnings": ["风险"], "suggestion": "需要重写"}'

        state = _make_initial_state()
        state["current_segment"] = "有问题的剧情。"
        state["current_options"] = [{"id": "A", "text": "选项A", "risk_level": "安全"}]

        # interrupt 会抛出异常
        with pytest.raises(Exception):
            critic_node(state)

    @patch("src.agents.reviewer.llm_call")
    def test_critic_empty_segment_with_setting_returns_progressing(self, mock_llm):
        from src.agents.reviewer import critic_node

        mock_llm.return_value = '{"score": 8, "passed": true, "issues": [], "risk_warnings": [], "suggestion": "设定良好"}'

        state = _make_initial_state()
        state["current_segment"] = ""

        result = critic_node(state)
        assert result["current_phase"] == "story_progressing"
        assert result["setting_confirmed"] is True

    @patch("src.agents.reviewer.llm_call")
    def test_critic_empty_segment_without_setting_returns_progressing(self, mock_llm):
        from src.agents.reviewer import critic_node

        state = _make_initial_state()
        state["current_segment"] = ""
        state["world_setting"] = ""

        result = critic_node(state)
        assert result["current_phase"] == "story_progressing"

    @patch("src.agents.reviewer.llm_call")
    def test_critic_setting_review_low_score(self, mock_llm):
        from src.agents.reviewer import critic_node
        from langgraph.types import interrupt

        mock_llm.return_value = '{"score": 3, "passed": false, "issues": ["设定矛盾"], "risk_warnings": [], "suggestion": "需要修改"}'

        state = _make_initial_state()
        state["current_segment"] = ""

        with pytest.raises(Exception):
            critic_node(state)

    @patch("src.agents.reviewer.llm_call")
    def test_critic_max_iterations_returns_progressing(self, mock_llm):
        from src.agents.reviewer import critic_node

        mock_llm.return_value = '{"score": 4, "passed": false, "issues": ["问题"], "risk_warnings": [], "suggestion": "修改"}'

        state = _make_initial_state()
        state["current_segment"] = "需要修改的剧情。"
        state["current_options"] = [{"id": "A", "text": "选项A", "risk_level": "安全"}]
        state["iteration_count"] = 3
        state["max_internal_iterations"] = 3

        result = critic_node(state)
        assert result["current_phase"] == "story_progressing"


# ─── Integrator 测试 ───────────────────────────────

class TestIntegratorNode:
    """测试 integrator_node 整合输出"""

    @patch("src.agents.integrator.llm_call")
    def test_integrator_returns_final_output(self, mock_llm):
        from src.agents.integrator import integrator_node

        mock_llm.return_value = "这是一篇完整的小说。"

        state = _make_initial_state()
        state["story_segments"] = ["段落1", "段落2", "段落3"]
        state["user_choices"] = [{"turn_id": 1, "content": "选择了A"}]
        state["current_phase"] = "completed"

        result = integrator_node(state)

        assert result["final_output"] == "这是一篇完整的小说。"
        assert result["current_phase"] == "completed"

    @patch("src.agents.integrator.llm_call")
    def test_integrator_empty_segments_returns_done(self, mock_llm):
        from src.agents.integrator import integrator_node

        state = _make_initial_state()
        state["story_segments"] = []

        result = integrator_node(state)
        assert result["current_phase"] == "done"
        assert "暂无内容" in result["final_output"]