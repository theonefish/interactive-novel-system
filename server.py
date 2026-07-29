"""FastAPI 服务器 - 提供 REST API 和静态文件服务"""

import uuid
import json
import asyncio
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.graph.workflow import build_graph, build_graph_async
from src.graph.state import NovelState
from src.tools.memory import create_initial_memory
from src.utils.database import is_postgres
from src.utils.streaming import transform_graph_events, format_sse_event


# ─── 全局应用实例 ──────────────────────────────────

app_graph = build_graph()
app_graph_async = None  # 按需初始化


# ─── 请求/响应模型 ──────────────────────────────────

class CreateSessionRequest(BaseModel):
    user_request: str


class ActionRequest(BaseModel):
    action: str
    payload: Optional[str] = None


class SessionResponse(BaseModel):
    session_id: str
    phase: str
    turn: int
    segment: str = ""
    options: list = []
    world_setting: str = ""
    characters: list = []
    rules: str = ""
    critique: str = ""
    risk_warnings: list = []
    final_output: str = ""
    human_approval: Optional[str] = None
    error: str = ""


# ─── 生命周期 ──────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    global app_graph_async
    if is_postgres():
        app_graph_async = await build_graph_async()
    yield
    # 关闭时
    if hasattr(app_graph.checkpointer, "conn"):
        app_graph.checkpointer.conn.close()


app = FastAPI(title="交互式小说创作系统", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件（生产环境）
try:
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
except Exception:
    pass  # 开发模式下无前端构建产物


# ─── 辅助函数 ──────────────────────────────────────

def _build_initial_state(user_request: str) -> NovelState:
    """构建初始状态"""
    return {
        "user_request": user_request,
        "world_setting": "",
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
        "current_phase": "init",
        "iteration_count": 0,
        "max_internal_iterations": 3,
    }


def _state_to_response(state: dict, session_id: str) -> SessionResponse:
    """将 LangGraph 状态转换为 API 响应"""
    phase = state.get("current_phase", "init")

    # 判断阶段
    if phase == "world_building":
        display_phase = "world_building"
    elif phase == "story_progressing":
        display_phase = "story_progressing"
    elif phase == "completed":
        display_phase = "completed"
    elif phase == "done":
        display_phase = "done"
    else:
        display_phase = "processing"

    return SessionResponse(
        session_id=session_id,
        phase=display_phase,
        turn=state.get("current_turn", 0),
        segment=state.get("current_segment", ""),
        options=state.get("current_options", []),
        world_setting=state.get("world_setting", ""),
        characters=state.get("characters", []),
        rules=state.get("rules", ""),
        critique=state.get("critique", ""),
        risk_warnings=state.get("risk_warnings", []),
        final_output=state.get("final_output", ""),
        human_approval=state.get("human_approval"),
        error=state.get("error", ""),
    )


# ─── API 路由 ──────────────────────────────────────

@app.post("/api/sessions", response_model=SessionResponse)
def create_session(req: CreateSessionRequest):
    """创建新会话"""
    if not req.user_request.strip():
        raise HTTPException(status_code=400, detail="创作需求不能为空")

    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    initial_state = _build_initial_state(req.user_request)

    try:
        result = app_graph.invoke(initial_state, config)
        return _state_to_response(result, session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动失败：{str(e)}")


@app.post("/api/sessions/{session_id}/action", response_model=SessionResponse)
def send_action(session_id: str, req: ActionRequest):
    """发送用户操作"""
    config = {"configurable": {"thread_id": session_id}}

    try:
        # 将用户操作转换为输入
        user_input = req.action
        if req.payload:
            user_input = req.payload

        from langgraph.types import Command
        result = app_graph.invoke(Command(resume=user_input), config)
        return _state_to_response(result, session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行失败：{str(e)}")


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str):
    """获取会话状态"""
    config = {"configurable": {"thread_id": session_id}}

    try:
        state = app_graph.get_state(config)
        if state is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return _state_to_response(state.values, session_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取状态失败：{str(e)}")


@app.get("/api/sessions/{session_id}/stream")
async def stream_session(session_id: str, request: Request, action: str = Query("")):
    """SSE 流式输出 - 逐节点/逐 token 推送图执行结果

    通过 EventSource 消费，事件类型：
    - node_start: 节点开始
    - node_end: 节点完成（含关键状态字段，如 story_driver 的 current_segment）
    - token: LLM token 片段（附 node 字段标明来源节点）
    - interrupt: 中断等待用户
    - error: 执行错误
    - final: 流结束后的完整状态快照（前端据此一次性渲染选项/世界观等）
    - done: 流结束

    前端在用户做出选择后调用此接口（action=用户输入），后端用
    Command(resume=action) 恢复被中断的图并流式执行。
    """
    config = {"configurable": {"thread_id": session_id}}

    # 获取当前状态
    try:
        current_state = app_graph.get_state(config)
        if current_state is None:
            raise HTTPException(status_code=404, detail="会话不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取状态失败：{str(e)}")

    async def event_generator():
        graph = app_graph_async if app_graph_async else app_graph

        from langgraph.types import Command
        try:
            # 使用 astream_events 流式执行，将用户输入恢复给被中断的图
            async_gen = graph.astream_events(
                Command(resume=action),
                config,
                version="v2",
            )

            async for sse_event in transform_graph_events(async_gen):
                if await request.is_disconnected():
                    break
                yield sse_event

            # 流结束后发送完整状态快照，供前端一次性渲染选项/世界观等
            state = graph.get_state(config)
            final_resp = _state_to_response(state.values, session_id)
            yield format_sse_event("final", final_resp.model_dump())

        except Exception as e:
            yield format_sse_event("error", {"error": str(e)})
        finally:
            yield format_sse_event("done", {"message": "stream complete"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── 启动入口 ──────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)