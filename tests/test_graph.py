"""图编排测试 - 测试 LangGraph 图构建、节点注册和边路由"""

import pytest
from unittest.mock import patch, MagicMock

from src.graph.state import NovelState
from src.tools.memory import create_initial_memory


def _make_state(phase: str = "init", **kwargs) -> NovelState:
    """构建测试状态"""
    base = {
        "user_request": "测试需求",
        "world_setting": "测试世界观",
        "characters": [],
        "rules": "",
        "setting_confirmed": False,
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
        "memory": create_initial_memory([]),
        "messages": [],
        "human_approval": None,
        "current_phase": phase,
        "iteration_count": 0,
        "max_internal_iterations": 3,
    }
    base.update(kwargs)
    return base


# ─── 图构建测试 ─────────────────────────────────────

class TestGraphBuild:
    """测试图的构建和编译"""

    def test_build_graph_returns_compiled_app(self):
        from src.graph.workflow import build_graph
        app = build_graph()
        assert app is not None
        assert hasattr(app, "invoke")
        assert hasattr(app, "astream_events")

    def test_build_workflow_has_all_nodes(self):
        from src.graph.workflow import _build_workflow
        workflow = _build_workflow()
        # StateGraph.nodes 在编译前可访问
        node_names = set(workflow.nodes.keys())
        expected_nodes = {"supervisor", "world_builder", "story_driver", "critic", "integrator"}
        assert expected_nodes.issubset(node_names)

    def test_graph_entry_point_is_supervisor(self):
        from src.graph.workflow import _build_workflow
        workflow = _build_workflow()
        # StateGraph.edges 是 set of (from, to) tuples
        assert ("__start__", "supervisor") in workflow.edges

    def test_build_graph_async_returns_coroutine(self):
        import asyncio
        from src.graph.workflow import build_graph_async
        coro = build_graph_async()
        assert asyncio.iscoroutine(coro)
        # 关闭未使用的协程
        coro.close()


# ─── 路由边测试 ─────────────────────────────────────

class TestGraphRouting:
    """测试条件边路由逻辑"""

    def test_init_routes_to_world_builder(self):
        from src.agents.supervisor import supervisor_route
        state = _make_state("init")
        assert supervisor_route(state) == "world_builder"

    def test_world_building_confirmed_routes_to_story_driver(self):
        from src.agents.supervisor import supervisor_route
        state = _make_state("world_building", setting_confirmed=True)
        assert supervisor_route(state) == "story_driver"

    def test_completed_routes_to_integrator(self):
        from src.agents.supervisor import supervisor_route
        state = _make_state("completed")
        assert supervisor_route(state) == "integrator"

    def test_done_routes_to_end(self):
        from langgraph.graph import END
        from src.agents.supervisor import supervisor_route
        state = _make_state("done")
        assert supervisor_route(state) == END

    def test_critic_loop_rejected_routes_to_story_driver(self):
        from src.agents.supervisor import supervisor_route
        state = _make_state("critic_loop", human_approval="rejected")
        assert supervisor_route(state) == "story_driver"


# ─── 状态流转测试 ───────────────────────────────────

class TestStateFlow:
    """测试完整状态流转链路"""

    def test_init_to_world_building_transition(self):
        from src.agents.supervisor import supervisor_node, supervisor_route
        state = _make_state("init")
        result = supervisor_node(state)
        # init 阶段不修改状态，交由路由进入 world_builder
        assert result == {} or result.get("current_phase") == "world_building"
        assert supervisor_route(state) == "world_builder"

    def test_world_building_to_story_driver_through_critic(self):
        """world_builder → critic → story_driver 的设定审查流转"""
        from src.agents.supervisor import critic_route, supervisor_route

        # 1. critic 完成设定审查并通过 -> story_driver
        state = _make_state("world_building")
        state["setting_confirmed"] = True
        state["current_phase"] = "story_progressing"
        route = critic_route(state)
        assert route == "story_driver"

        # 2. story_progressing 且 awaiting_user -> supervisor 路由到 supervisor
        #    在 supervisor_node 中通过 interrupt 暂停等待用户输入
        state["awaiting_user"] = True
        route = supervisor_route(state)
        assert route == "supervisor"

    def test_critic_route_setting_review_failed(self):
        """设定审查未通过 -> 打回 world_builder"""
        from src.agents.supervisor import critic_route

        state = _make_state("critic_loop")
        state["current_segment"] = ""
        state["world_setting"] = "测试世界观"
        route = critic_route(state)
        assert route == "world_builder"

    def test_critic_route_segment_passed(self):
        """剧情审查通过 -> 返回 supervisor 等待用户"""
        from src.agents.supervisor import critic_route

        state = _make_state("story_progressing")
        state["current_segment"] = "一段剧情"
        route = critic_route(state)
        assert route == "supervisor"

    def test_critic_route_segment_failed(self):
        """剧情审查未通过 -> 打回 story_driver 重写"""
        from src.agents.supervisor import critic_route

        state = _make_state("critic_loop")
        state["current_segment"] = "一段有问题的剧情"
        route = critic_route(state)
        assert route == "story_driver"

    def test_critic_loop_retry_flow(self):
        """critic 低分 -> critic_loop -> 重试"""
        from src.agents.supervisor import supervisor_route

        # critic 未通过，未达最大迭代
        state = _make_state("critic_loop", iteration_count=1, human_approval=None)
        route = supervisor_route(state)
        assert route == "critic"

    def test_critic_loop_rejected_flow(self):
        """critic 被用户驳回 -> 重新生成"""
        from src.agents.supervisor import supervisor_route

        state = _make_state("critic_loop", human_approval="rejected")
        route = supervisor_route(state)
        assert route == "story_driver"

    def test_completed_to_done_flow(self):
        """integrator 完成 -> supervisor -> done"""
        from langgraph.graph import END
        from src.agents.supervisor import supervisor_node, supervisor_route

        state = _make_state("completed")
        result = supervisor_node(state)
        assert result["current_phase"] == "done"

        route = supervisor_route(_make_state("done"))
        assert route == END


# ─── 端到端集成测试（mock LLM）──────────────────────

class TestEndToEndFlow:
    """模拟完整流程的集成测试"""

    @patch("src.agents.researcher.llm_call")
    @patch("src.agents.researcher.search_for_world_building", return_value="")
    def test_world_builder_produces_valid_state(self, mock_search, mock_llm):
        from src.agents.researcher import world_builder_node

        mock_llm.return_value = '{"world_setting": "末日世界", "characters": [{"name": "主角", "personality": "勇敢", "role": "主角"}], "rules": "规则1"}'

        state = _make_state("init")
        result = world_builder_node(state)

        assert result["world_setting"] == "末日世界"
        assert len(result["characters"]) == 1
        assert result["current_phase"] == "world_building"
        assert result["setting_confirmed"] is False
        assert result["current_turn"] == 0

    @patch("src.agents.integrator.llm_call")
    def test_full_integration_pipeline(self, mock_llm):
        """测试 integrator 端到端输出"""
        from src.agents.integrator import integrator_node

        mock_llm.return_value = "完整小说正文。"

        state = _make_state("completed")
        state["story_segments"] = ["第一段", "第二段"]
        state["user_choices"] = [{"turn_id": 1, "content": "选择A"}]

        result = integrator_node(state)

        assert result["final_output"] == "完整小说正文。"
        assert result["current_phase"] == "completed"
        mock_llm.assert_called_once()