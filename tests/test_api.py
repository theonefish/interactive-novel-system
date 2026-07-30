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


@pytest.fixture(autouse=True)
def mock_session_store():
    """自动 mock session_store，避免测试触碰真实 SQLite"""
    with patch("server.session_store") as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_long_term_memory():
    """自动 mock long_term_memory，避免测试触碰真实 SQLite"""
    with patch("server.long_term_memory") as mock:
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


# ─── GET /api/sessions 测试 ───────────────────────

class TestListSessions:
    """测试获取会话列表"""

    def test_list_returns_sessions_array(self, client, mock_session_store):
        mock_session_store.list_session_metas.return_value = [
            {
                "session_id": "s1",
                "title": "会话1",
                "current_phase": "story_progressing",
                "current_turn": 2,
                "segment_count": 2,
                "preview": "预览1",
            },
            {
                "session_id": "s2",
                "title": "会话2",
                "current_phase": "world_building",
                "current_turn": 0,
                "segment_count": 0,
                "preview": "",
            },
        ]
        response = client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["session_id"] == "s1"
        assert data[1]["session_id"] == "s2"
        mock_session_store.list_session_metas.assert_called_once()

    def test_list_empty_returns_empty_array(self, client, mock_session_store):
        mock_session_store.list_session_metas.return_value = []
        response = client.get("/api/sessions")
        assert response.status_code == 200
        assert response.json() == []


# ─── PATCH /api/sessions/{id} 测试 ─────────────────

class TestUpdateSessionTitle:
    """测试更新会话标题"""

    def test_update_title_success(self, client, mock_session_store):
        session_id = "patch-001"
        updated_meta = {
            "session_id": session_id,
            "title": "新标题",
            "current_phase": "story_progressing",
            "current_turn": 1,
            "segment_count": 1,
            "preview": "预览",
        }
        mock_session_store.get_session_meta.return_value = updated_meta
        response = client.patch(
            f"/api/sessions/{session_id}",
            json={"title": "新标题"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id
        assert data["title"] == "新标题"
        mock_session_store.update_session_meta.assert_called_once_with(
            session_id, {"title": "新标题"}
        )

    def test_update_title_session_not_found_returns_404(self, client, mock_session_store):
        mock_session_store.get_session_meta.return_value = None
        response = client.patch(
            "/api/sessions/nonexistent",
            json={"title": "标题"},
        )
        assert response.status_code == 404
        assert "会话不存在" in response.json()["detail"]
        mock_session_store.update_session_meta.assert_not_called()

    def test_update_title_missing_field_returns_422(self, client, mock_session_store):
        response = client.patch(
            "/api/sessions/some-id",
            json={},
        )
        assert response.status_code == 422


# ─── DELETE /api/sessions/{id} 测试 ─────────────────

class TestDeleteSession:
    """测试删除会话"""

    def test_delete_returns_204(self, client, mock_session_store):
        response = client.delete("/api/sessions/delete-001")
        assert response.status_code == 204
        mock_session_store.delete_session_meta.assert_called_once_with("delete-001")

    def test_delete_nonexistent_returns_204(self, client, mock_session_store):
        # 删除是幂等的，即使不存在也返回 204
        response = client.delete("/api/sessions/nonexistent")
        assert response.status_code == 204


# ─── 元数据写入集成测试 ──────────────────────────

class TestSessionMetaIntegration:
    """测试 create_session / send_action 会调用 session_store"""

    def test_create_session_calls_save_session_meta(self, client, mock_graph, mock_session_store):
        client.post(
            "/api/sessions",
            json={"user_request": "末日废土，主角带着女儿寻找绿洲"},
        )
        mock_session_store.save_session_meta.assert_called_once()
        call_args = mock_session_store.save_session_meta.call_args[0][0]
        assert call_args["title"] == "末日废土，主角带着女儿寻找绿洲"[:20]
        assert call_args["current_phase"] == "story_progressing"

    def test_send_action_calls_update_session_meta(self, client, mock_graph, mock_session_store):
        client.post(
            "/api/sessions/test-session-action/action",
            json={"action": "A"},
        )
        mock_session_store.update_session_meta.assert_called_once()
        call_args = mock_session_store.update_session_meta.call_args
        assert call_args[0][0] == "test-session-action"
        updates = call_args[0][1]
        assert updates["current_phase"] == "story_progressing"
        assert updates["current_turn"] == 1


# ─── POST /api/sessions/{id}/resume 测试 ──────────

class TestResumeSession:
    """测试续写会话"""

    def test_resume_success(self, client, mock_graph, mock_long_term_memory, mock_session_store):
        mock_long_term_memory.get_long_term_memory.return_value = {
            "memory_id": "orig-001",
            "title": "末日废土",
            "world_setting": "废土世界",
            "characters": [{"name": "主角", "role": "主角"}],
            "rules": "规则1",
            "story_segments": ["段落1", "段落2"],
            "memory_state": {"characters": [], "plot_threads": []},
            "final_output": "完整小说",
            "created_at": "2026-01-01T00:00:00",
            "completed_at": "2026-01-02T00:00:00",
        }
        # mock_graph.ainvoke 已由 mock_graph fixture 配置返回 story_progressing
        response = client.post("/api/sessions/orig-001/resume")
        assert response.status_code == 200
        data = response.json()
        # 新 session_id 应不同于原 memory_id
        assert data["session_id"] != "orig-001"
        assert data["phase"] == "story_progressing"
        # 验证加载了长期记忆
        mock_long_term_memory.get_long_term_memory.assert_called_once_with("orig-001")
        # 验证执行了图
        mock_graph.ainvoke.assert_called_once()
        # 验证写入了新会话元数据
        mock_session_store.save_session_meta.assert_called_once()
        meta_call = mock_session_store.save_session_meta.call_args[0][0]
        assert meta_call["session_id"] == data["session_id"]
        assert meta_call["title"] == "末日废土"

    def test_resume_memory_not_found_returns_404(self, client, mock_long_term_memory):
        mock_long_term_memory.get_long_term_memory.return_value = None
        response = client.post("/api/sessions/nonexistent/resume")
        assert response.status_code == 404
        assert "长期记忆不存在" in response.json()["detail"]
        mock_long_term_memory.get_long_term_memory.assert_called_once_with("nonexistent")


# ─── GET /api/memories 测试 ───────────────────────

class TestListMemories:
    """测试获取长期记忆列表"""

    def test_list_returns_memories(self, client, mock_long_term_memory):
        mock_long_term_memory.list_long_term_memories.return_value = [
            {
                "memory_id": "m1",
                "title": "记忆1",
                "completed_at": "2026-01-01T00:00:00",
                "preview": "预览1",
            },
            {
                "memory_id": "m2",
                "title": "记忆2",
                "completed_at": "2026-01-02T00:00:00",
                "preview": "预览2",
            },
        ]
        response = client.get("/api/memories")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["memory_id"] == "m1"
        assert data[1]["memory_id"] == "m2"
        mock_long_term_memory.list_long_term_memories.assert_called_once()

    def test_list_empty_returns_empty_array(self, client, mock_long_term_memory):
        mock_long_term_memory.list_long_term_memories.return_value = []
        response = client.get("/api/memories")
        assert response.status_code == 200
        assert response.json() == []


# ─── GET /api/memories/{id} 测试 ──────────────────

class TestGetMemory:
    """测试获取单条长期记忆"""

    def test_get_memory_success(self, client, mock_long_term_memory):
        mock_long_term_memory.get_long_term_memory.return_value = {
            "memory_id": "m1",
            "title": "记忆1",
            "world_setting": "世界",
            "characters": [{"name": "主角"}],
            "rules": "规则",
            "story_segments": ["段落"],
            "memory_state": {"characters": []},
            "final_output": "成稿",
            "created_at": "2026-01-01T00:00:00",
            "completed_at": "2026-01-02T00:00:00",
        }
        response = client.get("/api/memories/m1")
        assert response.status_code == 200
        data = response.json()
        assert data["memory_id"] == "m1"
        assert data["title"] == "记忆1"
        assert data["world_setting"] == "世界"
        assert data["characters"] == [{"name": "主角"}]
        mock_long_term_memory.get_long_term_memory.assert_called_once_with("m1")

    def test_get_memory_not_found_returns_404(self, client, mock_long_term_memory):
        mock_long_term_memory.get_long_term_memory.return_value = None
        response = client.get("/api/memories/nonexistent")
        assert response.status_code == 404
        assert "长期记忆不存在" in response.json()["detail"]


# ─── 会话完成保存长期记忆测试 ──────────────────────

class TestSaveLongTermMemoryOnDone:
    """测试 send_action 完成后 phase=done 时保存长期记忆"""

    def test_save_long_term_memory_called_when_done(self, client, mock_graph, mock_long_term_memory):
        mock_graph.ainvoke.return_value = {
            "current_phase": "done",
            "current_turn": 5,
            "current_segment": "",
            "story_segments": ["段落1", "段落2"],
            "final_output": "完整小说",
            "world_setting": "世界",
            "characters": [],
            "rules": "规则",
            "memory": {"characters": []},
            "current_options": [],
            "risk_warnings": [],
            "critique": "",
            "critique_score": 0,
            "human_approval": None,
        }
        response = client.post(
            "/api/sessions/done-session/action",
            json={"action": "生成全文"},
        )
        assert response.status_code == 200
        assert response.json()["phase"] == "done"
        mock_long_term_memory.save_long_term_memory.assert_called_once()
        call_args = mock_long_term_memory.save_long_term_memory.call_args
        assert call_args[0][0] == "done-session"
        # 第二个参数为图执行结果
        assert call_args[0][1]["current_phase"] == "done"

    def test_save_long_term_memory_not_called_when_not_done(self, client, mock_graph, mock_long_term_memory):
        # mock_graph fixture 默认返回 phase=story_progressing
        response = client.post(
            "/api/sessions/progressing-session/action",
            json={"action": "A"},
        )
        assert response.status_code == 200
        mock_long_term_memory.save_long_term_memory.assert_not_called()
