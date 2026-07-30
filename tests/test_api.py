"""API 接口测试 - 测试 FastAPI 服务器端点"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """创建测试客户端"""
    from server import app
    return TestClient(app)


@pytest.fixture
def mock_graph():
    """Mock LangGraph 应用实例（异步接口）"""
    with patch("server.app_graph") as mock:
        mock_return = {
            "current_phase": "story_progressing",
            "current_turn": 1,
            "current_segment": "剧情片段文本",
            "current_options": [
                {"id": "A", "text": "选项A", "risk_level": "安全"},
                {"id": "B", "text": "选项B", "risk_level": "中等"},
            ],
            "world_setting": "末日废土世界",
            "characters": [{"name": "主角", "role": "主角", "personality": "勇敢"}],
            "rules": "规则1",
            "critique": "",
            "critique_score": 0,
            "risk_warnings": [],
            "final_output": "",
            "human_approval": None,
        }
        # 异步接口：ainvoke / aget_state
        mock.ainvoke = AsyncMock(return_value=mock_return)
        mock.aget_state = AsyncMock(return_value=MagicMock(values=mock_return))
        # 兼容流式接口
        mock.astream_events = MagicMock(return_value=iter([]))
        yield mock


# ─── 健康检查 & 文档 ───────────────────────────────

class TestAppBasics:
    """测试应用基础功能"""

    def test_app_has_correct_title(self, client):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "交互式小说创作系统"

    def test_docs_endpoint_accessible(self, client):
        response = client.get("/docs")
        assert response.status_code == 200

    def test_redoc_endpoint_accessible(self, client):
        response = client.get("/redoc")
        assert response.status_code == 200


# ─── POST /api/sessions 测试 ───────────────────────

class TestCreateSession:
    """测试创建会话"""

    def test_create_session_success(self, client, mock_graph):
        response = client.post(
            "/api/sessions",
            json={"user_request": "末日废土，主角带着女儿寻找绿洲"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["session_id"]  # 非空
        assert data["phase"] == "story_progressing"
        assert data["turn"] == 1
        assert data["segment"] == "剧情片段文本"
        assert len(data["options"]) == 2
        assert data["world_setting"] == "末日废土世界"

    def test_create_session_empty_request_returns_400(self, client, mock_graph):
        response = client.post("/api/sessions", json={"user_request": ""})
        assert response.status_code == 400

    def test_create_session_whitespace_request_returns_400(self, client, mock_graph):
        response = client.post("/api/sessions", json={"user_request": "   "})
        assert response.status_code == 400

    def test_create_session_missing_field_returns_422(self, client, mock_graph):
        response = client.post("/api/sessions", json={})
        assert response.status_code == 422

    def test_create_session_graph_error_returns_500(self, client, mock_graph):
        mock_graph.ainvoke.side_effect = Exception("LLM 调用失败")
        response = client.post(
            "/api/sessions",
            json={"user_request": "测试需求"},
        )
        assert response.status_code == 500
        assert "启动失败" in response.json()["detail"]


# ─── POST /api/sessions/{id}/action 测试 ───────────

class TestSendAction:
    """测试发送用户操作"""

    def test_send_action_select_option(self, client, mock_graph):
        session_id = "test-session-001"
        response = client.post(
            f"/api/sessions/{session_id}/action",
            json={"action": "A"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id
        assert data["phase"] == "story_progressing"

    def test_send_action_with_payload(self, client, mock_graph):
        response = client.post(
            "/api/sessions/test-session-002/action",
            json={"action": "custom", "payload": "我想探索左边的小路"},
        )
        assert response.status_code == 200

    def test_send_action_generate_full(self, client, mock_graph):
        response = client.post(
            "/api/sessions/test-session-003/action",
            json={"action": "生成全文"},
        )
        assert response.status_code == 200

    def test_send_action_missing_action_field_returns_422(self, client, mock_graph):
        response = client.post(
            "/api/sessions/test-session-004/action",
            json={},
        )
        assert response.status_code == 422

    def test_send_action_graph_error_returns_500(self, client, mock_graph):
        mock_graph.ainvoke.side_effect = Exception("执行失败")
        response = client.post(
            "/api/sessions/test-session-005/action",
            json={"action": "A"},
        )
        assert response.status_code == 500
        assert "执行失败" in response.json()["detail"]


# ─── GET /api/sessions/{id} 测试 ───────────────────

class TestGetSession:
    """测试获取会话状态"""

    def test_get_session_success(self, client, mock_graph):
        response = client.get("/api/sessions/test-session-001")
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test-session-001"
        assert data["phase"] == "story_progressing"
        assert data["turn"] == 1
        assert data["segment"] == "剧情片段文本"

    def test_get_session_not_found_returns_404(self, client, mock_graph):
        mock_graph.aget_state.return_value = None
        response = client.get("/api/sessions/nonexistent-session")
        assert response.status_code == 404
        assert "会话不存在" in response.json()["detail"]

    def test_get_session_internal_error_returns_500(self, client, mock_graph):
        mock_graph.aget_state.side_effect = Exception("数据库错误")
        response = client.get("/api/sessions/test-session-error")
        assert response.status_code == 500
        assert "获取状态失败" in response.json()["detail"]


# ─── GET /api/sessions/{id}/stream 测试 ───────────

class TestStreamSession:
    """测试 SSE 流式输出"""

    def test_stream_returns_event_stream(self, client, mock_graph):
        # Mock 异步生成器
        async def mock_astream(*args, **kwargs):
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="你")}}
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="好")}}

        mock_graph.astream_events = mock_astream

        response = client.get(
            "/api/sessions/test-stream-001/stream",
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

    def test_stream_session_not_found_returns_404(self, client, mock_graph):
        mock_graph.aget_state = AsyncMock(return_value=None)
        response = client.get("/api/sessions/nonexistent/stream")
        assert response.status_code == 404

    def test_stream_session_error_returns_500(self, client, mock_graph):
        mock_graph.aget_state = AsyncMock(side_effect=Exception("连接错误"))
        response = client.get("/api/sessions/error-session/stream")
        assert response.status_code == 500


# ─── 响应模型测试 ──────────────────────────────────

class TestSessionResponse:
    """测试 SessionResponse 模型字段"""

    def test_response_contains_all_fields(self, client, mock_graph):
        response = client.post(
            "/api/sessions",
            json={"user_request": "测试需求"},
        )
        data = response.json()
        expected_fields = {
            "session_id", "phase", "turn", "segment", "options",
            "world_setting", "characters", "rules",
            "critique", "risk_warnings", "final_output",
            "human_approval", "error",
        }
        assert expected_fields.issubset(set(data.keys()))

    def test_response_default_values(self, client, mock_graph):
        mock_graph.ainvoke.return_value = {
            "current_phase": "init",
            "current_turn": 0,
        }
        response = client.post(
            "/api/sessions",
            json={"user_request": "测试"},
        )
        data = response.json()
        assert data["segment"] == ""
        assert data["options"] == []
        assert data["world_setting"] == ""
        assert data["characters"] == []
        assert data["rules"] == ""
        assert data["critique"] == ""
        assert data["risk_warnings"] == []
        assert data["final_output"] == ""
        assert data["human_approval"] is None
        assert data["error"] == ""

    def test_response_with_human_approval(self, client, mock_graph):
        mock_graph.ainvoke.return_value = {
            "current_phase": "critic_loop",
            "current_turn": 2,
            "current_segment": "需要审核的段落",
            "human_approval": "pending",
        }
        response = client.post(
            "/api/sessions",
            json={"user_request": "测试"},
        )
        data = response.json()
        assert data["human_approval"] == "pending"


# ─── 阶段转换测试 ──────────────────────────────────

class TestPhaseDisplay:
    """测试不同 phase 在 API 响应中的展示"""

    def test_world_building_phase_displayed(self, client, mock_graph):
        mock_graph.ainvoke.return_value = {
            "current_phase": "world_building",
            "current_turn": 0,
            "world_setting": "奇幻世界",
        }
        response = client.post(
            "/api/sessions",
            json={"user_request": "测试"},
        )
        assert response.json()["phase"] == "world_building"

    def test_completed_phase_displayed(self, client, mock_graph):
        mock_graph.ainvoke.return_value = {
            "current_phase": "completed",
            "current_turn": 5,
            "final_output": "完整小说",
        }
        response = client.post(
            "/api/sessions",
            json={"user_request": "测试"},
        )
        assert response.json()["phase"] == "completed"
        assert response.json()["final_output"] == "完整小说"

    def test_done_phase_displayed(self, client, mock_graph):
        mock_graph.ainvoke.return_value = {
            "current_phase": "done",
            "current_turn": 5,
        }
        response = client.post(
            "/api/sessions",
            json={"user_request": "测试"},
        )
        assert response.json()["phase"] == "done"

    def test_unknown_phase_shows_processing(self, client, mock_graph):
        mock_graph.ainvoke.return_value = {
            "current_phase": "unknown_state",
            "current_turn": 0,
        }
        response = client.post(
            "/api/sessions",
            json={"user_request": "测试"},
        )
        assert response.json()["phase"] == "processing"


# ─── 辅助函数测试 ──────────────────────────────────

class TestHelpers:
    """测试内部辅助函数"""

    def test_build_initial_state_contains_all_fields(self):
        from server import _build_initial_state
        state = _build_initial_state("测试需求")
        assert state["user_request"] == "测试需求"
        assert state["current_phase"] == "init"
        assert state["setting_confirmed"] is False
        assert state["story_segments"] == []
        assert state["current_turn"] == 0
        assert state["memory"] is not None
        assert state["messages"] == []
        assert state["human_approval"] is None
        assert state["max_internal_iterations"] == 3

    def test_build_initial_state_has_memory(self):
        from server import _build_initial_state
        from src.tools.memory import MemoryState
        state = _build_initial_state("测试")
        assert "characters" in state["memory"]
        assert "plot_threads" in state["memory"]
        assert "foreshadowing" in state["memory"]

    def test_state_to_response_maps_fields(self):
        from server import _state_to_response
        state = {
            "current_phase": "story_progressing",
            "current_turn": 3,
            "current_segment": "段落",
            "current_options": [{"id": "A", "text": "选项"}],
            "world_setting": "世界",
            "characters": [{"name": "角色"}],
            "rules": "规则",
            "critique": "评审",
            "risk_warnings": ["警告"],
            "final_output": "",
            "human_approval": None,
        }
        resp = _state_to_response(state, "session-123")
        assert resp.session_id == "session-123"
        assert resp.phase == "story_progressing"
        assert resp.turn == 3
        assert resp.segment == "段落"
        assert len(resp.options) == 1
        assert resp.world_setting == "世界"
        assert len(resp.characters) == 1
        assert resp.rules == "规则"
        assert resp.critique == "评审"
        assert resp.risk_warnings == ["警告"]
