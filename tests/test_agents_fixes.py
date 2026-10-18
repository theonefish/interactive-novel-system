"""P0/P1 修复的行为回归测试。

需要完整后端依赖（langgraph / fastapi / langchain-openai / python-dotenv / pyyaml），
缺少依赖时整个模块会被跳过，不阻塞前端或静态检查。
"""

import json
import pathlib

import pytest

pytest.importorskip("langgraph")
pytest.importorskip("fastapi")
pytest.importorskip("langchain_openai")
pytest.importorskip("dotenv")
pytest.importorskip("yaml")

import server  # noqa: E402
from src.agents import reviewer, supervisor  # noqa: E402


def _state(**overrides):
    state = {
        "world_setting": "设定",
        "characters": [],
        "rules": "",
        "current_segment": "",
        "current_options": [],
        "story_segments": [],
        "segment_history": [],
        "current_turn": 0,
        "iteration_count": 0,
        "max_internal_iterations": 3,
        "awaiting_user": False,
        "setting_confirmed": False,
        "current_phase": "story_progressing",
        "human_approval": None,
        "user_choices": [],
    }
    state.update(overrides)
    return state


def _critic_json(score, passed):
    return json.dumps({
        "score": score,
        "passed": passed,
        "issues": [],
        "risk_warnings": [],
        "suggestion": "suggestion",
    })


# ─── server：interrupt 载荷 → API 字段 ───────────────────────────

def test_review_interrupt_marks_pending():
    payload = {"kind": "segment_review", "question": "低分", "score": 3}
    resp = server._state_to_response(_state(), "sid", payload)
    assert resp.human_approval == "pending"
    assert resp.review == payload


def test_choice_interrupt_keeps_options_flow():
    resp = server._state_to_response(_state(), "sid", {"kind": "choice", "message": "请选择"})
    assert resp.human_approval is None
    assert resp.review is None


def test_extract_interrupt_supported_shapes():
    class Item:
        def __init__(self, value):
            self.value = value

    class Snap:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    assert server._extract_interrupt(None) is None
    assert server._extract_interrupt({}) is None
    assert server._extract_interrupt({"__interrupt__": [Item({"kind": "a"})]}) == {"kind": "a"}
    assert server._extract_interrupt(Snap(interrupts=[Item({"kind": "b"})])) == {"kind": "b"}
    assert server._extract_interrupt(Snap(tasks=[Snap(interrupts=[Item({"kind": "c"})])])) == {"kind": "c"}
    assert server._extract_interrupt(Snap(tasks=[])) is None


# ─── reviewer：驳回回滚 / 计数重置 ──────────────────────────────

def test_segment_rejection_rolls_back_and_increments(monkeypatch):
    monkeypatch.setattr(reviewer, "llm_call", lambda **_: _critic_json(2, False))
    history = [
        {"turn": 1, "segment": "第一段", "options": []},
        {"turn": 2, "segment": "第二段", "options": []},
    ]
    state = _state(
        current_segment="第二段",
        story_segments=["第一段", "第二段"],
        segment_history=history,
        current_turn=2,
    )

    # 第一步：critic 算分并把结果挂起（不调 interrupt、不回滚）
    pending = reviewer._review_segment(state)
    assert pending["current_phase"] == "review_pending"
    assert pending["pending_review"]["kind"] == "segment_review"
    assert pending["pending_review"]["score"] == 2
    assert "story_segments" not in pending

    # 第二步：用户驳回 → 回滚 + 打回重写
    updates = reviewer.apply_human_review({**state, **pending}, "太差，重写")

    assert updates["current_phase"] == "critic_loop"
    assert updates["story_segments"] == ["第一段"]
    assert updates["segment_history"] == [history[0]]
    assert updates["current_turn"] == 1
    assert updates["iteration_count"] == 1
    assert updates["pending_review"] is None


def test_segment_pass_resets_iteration_count(monkeypatch):
    monkeypatch.setattr(reviewer, "llm_call", lambda **_: _critic_json(9, True))
    state = _state(
        current_segment="一段",
        story_segments=["一段"],
        segment_history=[{"turn": 1, "segment": "一段", "options": []}],
        current_turn=1,
        iteration_count=2,
    )

    updates = reviewer._review_segment(state)

    assert updates["current_phase"] == "story_progressing"
    assert updates["iteration_count"] == 0
    assert "story_segments" not in updates


def test_segment_rollback_is_guarded_against_double_pop(monkeypatch):
    monkeypatch.setattr(reviewer, "llm_call", lambda **_: _critic_json(1, False))
    state = _state(
        current_segment="第二段",
        story_segments=["第一段", "第二段"],
        segment_history=[{"turn": 1, "segment": "第一段", "options": []}],
        current_turn=2,
    )

    pending = reviewer._review_segment(state)
    updates = reviewer.apply_human_review({**state, **pending}, "驳回")

    assert updates["current_phase"] == "critic_loop"
    assert "story_segments" not in updates


def test_rollback_helper_returns_empty_when_history_mismatches():
    assert reviewer._rollback_last_segment(_state()) == {}


def test_setting_pass_waits_for_user_confirmation(monkeypatch):
    monkeypatch.setattr(reviewer, "llm_call", lambda **_: _critic_json(9, True))
    state = _state(world_setting="设定", current_phase="world_building", iteration_count=3)

    updates = reviewer._review_setting(state)

    assert updates["current_phase"] == "world_building"
    assert updates["setting_confirmed"] is False
    assert updates["iteration_count"] == 0


def test_critic_route_setting_pass_goes_to_supervisor():
    state = _state(world_setting="设定", current_phase="world_building")
    assert supervisor.critic_route(state) == "supervisor"


# ─── supervisor：世界观确认 / 新一轮计数重置 ────────────────────

def test_world_confirmation_approved(monkeypatch):
    monkeypatch.setattr(supervisor, "interrupt", lambda _payload: "approved")
    state = _state(world_setting="设定", current_phase="world_building", iteration_count=2)

    updates = supervisor.supervisor_node(state)

    assert updates["setting_confirmed"] is True
    assert updates["current_phase"] == "story_progressing"
    assert updates["iteration_count"] == 0


def test_world_confirmation_rejected_regenerates_setting(monkeypatch):
    monkeypatch.setattr(supervisor, "interrupt", lambda _payload: "太老套了")
    state = _state(world_setting="设定", current_phase="world_building", iteration_count=1)

    updates = supervisor.supervisor_node(state)

    assert updates["world_setting"] == ""
    assert updates["setting_confirmed"] is False
    assert updates["current_phase"] == "world_building"
    assert updates["iteration_count"] == 2
    assert "太老套了" in updates["critique"]
    assert supervisor.supervisor_route({**state, **updates}) == "world_builder"


def test_apply_user_choice_resets_iteration_count(monkeypatch):
    monkeypatch.setattr(
        supervisor,
        "parse_user_input",
        lambda *_: {"action": "select_option", "selected_option": "A"},
    )
    state = _state(current_turn=2, iteration_count=2)

    updates = supervisor._apply_user_choice(state, "A")

    assert updates["iteration_count"] == 0
    assert updates["user_choices"][-1]["selected_option"] == "A"


# ─── 防重复点击：服务端兜底 + 前端防抖 ────────────────────────────

def test_send_action_rejects_duplicate_request_while_running():
    """同一会话执行中再来一个请求，必须 409，而不是并发写同一个 checkpoint。"""
    from fastapi.testclient import TestClient

    server._running_sessions.add("busy-sid")
    try:
        r = TestClient(server.app).post("/api/sessions/busy-sid/action", json={"action": "A"})
        assert r.status_code == 409, r.text[:200]
        assert "正在生成中" in r.json()["detail"]
    finally:
        server._running_sessions.discard("busy-sid")


def test_stream_session_skips_graph_when_session_is_running():
    """重复点击时 SSE 直接回错误事件，不进入图执行。"""
    from fastapi.testclient import TestClient

    class _Snap:
        values = {"current_phase": "story_progressing"}

    class _Graph:
        async def aget_state(self, config):
            return _Snap()

    original = server.app_graph_async
    server.app_graph_async = _Graph()
    server._running_sessions.add("busy-sid")
    try:
        with TestClient(server.app).stream(
            "GET", "/api/sessions/busy-sid/stream", params={"action": "A"}
        ) as resp:
            body = "".join(resp.iter_text())
        assert "event: error" in body, body[:200]
        assert "正在生成中" in body, body[:200]
        assert "event: done" in body, body[:200]
    finally:
        server._running_sessions.discard("busy-sid")
        server.app_graph_async = original


def test_frontend_approval_panel_is_debounced_and_accepts_input():
    """前端：审核按钮在生成中禁用；世界观确认阶段可填写修改要求。"""
    app = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "src" / "App.vue"
    src = app.read_text(encoding="utf-8")

    # 通过 / 修改-驳回 / 输入框 / 提交按钮 都要绑定 isWaiting
    assert src.count(':disabled="isWaiting"') >= 4
    # runStream / sendUserInput / openRejection / sendApproval 都要提前返回
    assert src.count("if (isWaiting.value) return") >= 4
    assert "rejectLabel" in src
    assert "修改世界观" in src
    assert "rejectionHint" in src


# ─── 世界观构建失败不得静默进入剧情 ──────────────────────────────

def test_empty_world_triggers_rebuild_instead_of_writing_story():
    """world_builder 没给出设定时，必须打回重做，而不是跳过「世界观确认」直接写剧情。"""
    state = _state(world_setting="", current_segment="", current_phase="world_building")

    updates = reviewer.critic_node(state)

    assert updates["current_phase"] == "critic_loop"
    assert updates["iteration_count"] == 1
    assert supervisor.critic_route({**state, **updates}) == "world_builder"


def test_empty_world_gives_up_after_max_iterations():
    state = _state(world_setting="", current_segment="",
                   iteration_count=3, max_internal_iterations=3)

    updates = reviewer.critic_node(state)

    assert updates["current_phase"] == "done"
    assert "世界观构建失败" in updates["error"]
    assert supervisor.critic_route({**state, **updates}) == "supervisor"


def test_normal_setting_review_route_unchanged():
    """有世界观时仍然是「审查通过 → 回 supervisor 等确认」。"""
    state = _state(world_setting="设定", current_segment="", current_phase="world_building")
    assert supervisor.critic_route(state) == "supervisor"


# ─── 重新生成剧情 ─────────────────────────────────────────────────

def test_parse_regenerate_command():
    parsed = supervisor.parse_user_input("重新生成剧情", "story_progressing")
    assert parsed["action"] == "regenerate"


def test_parse_backtrack_unchanged():
    """「重来/回到上一步」仍然是回退，不能和重新生成混在一起。"""
    assert supervisor.parse_user_input("回到上一步", "story_progressing")["action"] == "backtrack"
    assert supervisor.parse_user_input("重来", "story_progressing")["action"] == "backtrack"


def test_regenerate_replaces_current_segment(monkeypatch):
    """原地重写：轮次与段落数不变，当前片段被丢弃，随后由 story_driver 重写。"""
    monkeypatch.setattr(supervisor, "parse_user_input",
                        lambda *_: {"action": "regenerate", "selected_option": None})
    history = [
        {"turn": 1, "segment": "第一段", "options": []},
        {"turn": 2, "segment": "第二段", "options": []},
    ]
    state = _state(
        current_segment="第二段",
        story_segments=["第一段", "第二段"],
        segment_history=history,
        current_turn=2,
        current_options=[{"id": "A", "text": "旧选项"}],
    )

    updates = supervisor._apply_user_choice(state, "重新生成剧情")

    assert updates["current_turn"] == 1
    assert updates["story_segments"] == ["第一段"]
    assert updates["segment_history"] == [history[0]]
    assert updates["current_phase"] == "story_progressing"
    assert updates["awaiting_user"] is False
    assert updates["iteration_count"] == 0
    assert updates["current_options"] == []
    assert updates["user_choices"][-1]["choice_type"] == "regenerate"


def test_regenerate_without_story_is_noop():
    updates = supervisor.handle_regenerate(_state())
    assert updates == {"current_phase": "story_progressing", "awaiting_user": False}
    assert "story_segments" not in updates


def test_frontend_has_regenerate_button():
    app = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "src" / "App.vue"
    src = app.read_text(encoding="utf-8")
    assert "重新生成剧情" in src
    assert "canRegenerate" in src
    assert "RefreshRight" in src


# ─── 省 token：审核节奏 / 审核闸门 / 只调一次模型 ────────────────

def test_review_flow_calls_model_only_once(monkeypatch):
    """审核中断恢复不能把同一段再送进模型（原来会重复调用一次）。"""
    calls = []

    def fake_llm(**_):
        calls.append(1)
        return _critic_json(2, False)

    monkeypatch.setattr(reviewer, "llm_call", fake_llm)
    state = _state(
        current_segment="一段",
        story_segments=["一段"],
        segment_history=[{"turn": 1, "segment": "一段", "options": []}],
        current_turn=1,
    )

    pending = reviewer._review_segment(state)
    reviewer.apply_human_review({**state, **pending}, "驳回")

    assert len(calls) == 1


def test_should_review_segment_follows_cadence():
    """每 2 轮审一次：第 1、3 轮审，第 2 轮跳过。"""
    assert reviewer.should_review_segment(_state(current_turn=1)) is True
    assert reviewer.should_review_segment(_state(current_turn=2)) is False
    assert reviewer.should_review_segment(_state(current_turn=3)) is True


def test_should_review_segment_forces_high_risk_choice():
    state = _state(
        current_turn=2,
        current_options=[{"id": "B", "text": "硬闯", "risk_level": "高风险"}],
        user_choices=[{"turn_id": 1, "choice_type": "select_option",
                       "content": "B", "selected_option": "B"}],
    )
    assert reviewer.should_review_segment(state) is True


def test_should_review_segment_forces_after_regenerate():
    state = _state(
        current_turn=2,
        user_choices=[{"turn_id": 1, "choice_type": "regenerate",
                       "content": "重新生成剧情", "selected_option": None}],
    )
    assert reviewer.should_review_segment(state) is True


def test_critic_node_skips_model_call_when_cadence_says_no(monkeypatch):
    def boom(**_):
        raise AssertionError("第 2 轮不应调用 critic 模型")

    monkeypatch.setattr(reviewer, "llm_call", boom)
    state = _state(current_segment="第二段", current_turn=2, story_segments=["第一段", "第二段"])

    updates = reviewer.critic_node(state)

    assert updates == {"current_phase": "story_progressing"}


def test_review_gate_interrupts_with_pending_payload(monkeypatch):
    captured = {}

    def fake_interrupt(payload):
        captured.update(payload)
        return "approved"

    monkeypatch.setattr(reviewer, "interrupt", fake_interrupt)
    state = _state(
        current_phase="review_pending",
        pending_review={"kind": "segment_review", "question": "低分", "score": 3,
                        "options": [{"id": "approved"}, {"id": "rejected"}]},
        iteration_count=1,
    )

    updates = reviewer.review_gate_node(state)

    assert captured["kind"] == "segment_review"
    assert updates["current_phase"] == "story_progressing"
    assert updates["iteration_count"] == 0
    assert updates["pending_review"] is None


def test_review_gate_without_payload_passes_through():
    updates = reviewer.review_gate_node(_state(current_phase="review_pending", pending_review=None))
    assert updates["current_phase"] == "story_progressing"


def test_review_pending_route_goes_to_gate():
    state = _state(current_phase="review_pending", pending_review={"kind": "segment_review"})
    assert supervisor.critic_route(state) == "review_gate"
    assert supervisor.supervisor_route(state) == "review_gate"


def test_build_stable_query_ignores_volatile_context():
    from src.tools.rag_tool import build_stable_query
    a = build_stable_query("赛博朋克侦探", "新港，义体记忆可交易")
    b = build_stable_query("赛博朋克侦探", "新港，义体记忆可交易")
    assert a == b and "赛博朋克侦探" in a


# ─── 续写重复提交防护 ────────────────────────────────────────────

def test_resume_rejects_duplicate_while_in_flight():
    """同一份记忆并发续写必须 409（连点会造出多个重复会话 + 多次生成）。"""
    from fastapi.testclient import TestClient

    server._resuming_memories.add("busy-memory")
    try:
        r = TestClient(server.app).post("/api/sessions/busy-memory/resume", json={})
        assert r.status_code == 409, r.text[:200]
        assert "正在续写中" in r.json()["detail"]
    finally:
        server._resuming_memories.discard("busy-memory")


def test_resume_guard_is_released_after_failure():
    """闸门必须在 finally 里释放，否则记忆会被永久锁住。"""
    import inspect

    src = inspect.getsource(server.resume_session)
    assert "_resuming_memories.add(session_id)" in src
    assert "finally:" in src and "_resuming_memories.discard(session_id)" in src


def test_frontend_sidebar_is_debounced_while_busy():
    root = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "src"
    sidebar = (root / "components" / "SessionSidebar.vue").read_text(encoding="utf-8")
    app = (root / "App.vue").read_text(encoding="utf-8")

    assert "busy: { type: Boolean, default: false }" in sidebar
    assert ':disabled="busy"' in sidebar          # 新建按钮
    assert ':loading="busy"' in sidebar           # 续写按钮
    assert "function resumeSession" in sidebar and "if (props.busy) return" in sidebar
    assert "function selectSession" in sidebar
    assert ':busy="isWaiting"' in app             # App 把等待状态传进侧栏


# ─── 流式用量：只取最后一个分片，不做求和 ────────────────────────

def test_llm_call_takes_last_chunk_usage_not_the_sum(monkeypatch):
    """核心回归：每个分片都带 usage 时，只能记「最后一次」的用量，不能求和。

    （SiliconFlow 流式下每个分片都带 usage，LangChain 会把它们加起来 → 曾放大几百倍）
    """
    from src.utils import llm as llm_module
    from src.utils import usage as usage_module

    class _Chunk:
        def __init__(self, content="", usage_metadata=None):
            self.content = content
            self.usage_metadata = usage_metadata

    class _FakeChat:
        def stream(self, messages):
            # 模拟：每个分片都报同一份（累计）用量
            for i in range(300):
                yield _Chunk("字", {"input_tokens": 2000, "output_tokens": 0, "total_tokens": 2000})
            yield _Chunk("", {"input_tokens": 2000, "output_tokens": 700, "total_tokens": 2700})

    monkeypatch.setattr(llm_module, "_build_chat", lambda *a, **k: _FakeChat())
    usage_module.reset_usage()

    text = llm_module.llm_call("sys", "user", node="story_driver")

    assert text == "字" * 300
    calls = usage_module.last_calls()
    assert len(calls) == 1
    assert calls[0]["input"] == 2000, calls[0]      # 不是 2000*301
    assert calls[0]["output"] == 700
    assert calls[0]["node"] == "story_driver"
    usage_module.reset_usage()


# ─── 回溯上限按「次数」而不是「段数」 ────────────────────────────

def test_backtrack_still_works_after_many_segments():
    """6 段剧情时仍然可以回退（老实现用 len(segment_history) 判断，5 段后永久失效）。"""
    history = [{"turn": i, "segment": f"第{i}段", "options": []} for i in range(1, 7)]
    state = _state(
        story_segments=[h["segment"] for h in history],
        segment_history=history,
        current_segment="第6段",
        current_turn=6,
    )

    updates = supervisor.handle_backtrack(state)

    assert updates["current_turn"] == 5
    assert updates["current_segment"] == "第5段"
    assert len(updates["story_segments"]) == 5


def test_backtrack_stops_after_max_backtracks():
    history = [{"turn": i, "segment": f"第{i}段", "options": []} for i in range(1, 7)]
    state = _state(
        story_segments=[h["segment"] for h in history],
        segment_history=history,
        current_segment="第6段",
        current_turn=6,
        user_choices=[{"turn_id": i, "choice_type": "backtrack",
                       "content": "回到上一步", "selected_option": None} for i in range(5)],
    )

    updates = supervisor.handle_backtrack(state)

    assert updates == {"current_phase": "story_progressing"}   # 已达上限，不回退


# ─── 上传文件名净化 ──────────────────────────────────────────────

def test_safe_upload_name_strips_paths():
    assert server._safe_upload_name("../../evil.txt") == "evil.txt"
    assert server._safe_upload_name("a/b/c.md") == "c.md"
    assert server._safe_upload_name("..\\..\\win.pdf") == "win.pdf"
    assert server._safe_upload_name("..") == ""
    assert server._safe_upload_name("") == ""
    assert server._safe_upload_name("正常文件.txt") == "正常文件.txt"


def test_knowledge_save_path_stays_inside_base():
    import inspect

    path = server._knowledge_save_path("ok.txt")
    assert path.parent == server.KNOWLEDGE_BASE_DIR.resolve()
    # 端到端守卫：上传处理必须用净化后的名字与受控路径
    src = inspect.getsource(server.upload_knowledge_file)
    assert "_safe_upload_name(file.filename" in src
    assert "save_path = _knowledge_save_path(filename)" in src


# ─── 段落计数 ────────────────────────────────────────────────────

def test_response_exposes_segment_count():
    state = _state(story_segments=["第一段", "第二段", "第三段"])
    resp = server._state_to_response(state, "sid")
    assert resp.segment_count == 3


def test_frontend_uses_server_segment_count():
    app = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "src" / "App.vue"
    src = app.read_text(encoding="utf-8")
    assert "typeof data.segment_count === 'number'" in src
    assert "currentSegmentCount.value = data.segment_count" in src

