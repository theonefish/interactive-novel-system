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
from src.tools import long_term_memory
from src.tools.memory import create_initial_memory
from src.utils import session_store
from src.utils.database import is_postgres
from src.utils.streaming import transform_graph_events, format_sse_event
from src.utils.logger import setup_logger
from langgraph.types import Command
from langgraph.errors import GraphInterrupt

logger = setup_logger("server")


# ─── 全局应用实例 ──────────────────────────────────

app_graph = build_graph()
app_graph_async = None


# ─── 请求/响应模型 ──────────────────────────────────

class CreateSessionRequest(BaseModel):
    user_request: str


class ActionRequest(BaseModel):
    action: str
    payload: Optional[str] = None


class UpdateTitleRequest(BaseModel):
    title: str


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
    global app_graph_async

    # ✅ 修正：无论 SQLite 还是 Postgres，都初始化异步图
    app_graph_async = await build_graph_async()
    logger.info("[lifespan] 异步图初始化完成")

    yield

    # ── 关闭时清理 ──
    # 同步图
    if hasattr(app_graph, "checkpointer") and hasattr(app_graph.checkpointer, "conn"):
        app_graph.checkpointer.conn.close()

    # 异步图
    if app_graph_async and hasattr(app_graph_async, "checkpointer"):
        cp = app_graph_async.checkpointer
        if hasattr(cp, "conn") and hasattr(cp.conn, "close"):
            await cp.conn.close()  # aiosqlite 连接需要 await close
            logger.info("[lifespan] 异步 checkpointer 连接已关闭")



app = FastAPI(title="交互式小说创作系统", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
async def create_session(req: CreateSessionRequest):
    """创建新会话"""
    if not req.user_request.strip():
        raise HTTPException(status_code=400, detail="创作需求不能为空")

    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    initial_state = _build_initial_state(req.user_request)
    graph = app_graph_async or app_graph

    try:
        logger.info(f"[create_session] 新建会话 {session_id}，user_request={req.user_request!r}")
        try:
            result = await graph.ainvoke(initial_state, config)
        except GraphInterrupt:
            # 图在 interrupt（等待用户）处暂停，读取已 checkpoint 的状态返回
            logger.info(f"[create_session] 图在中断处暂停，读取当前状态返回")
            snap = await graph.aget_state(config)
            result = snap.values
        logger.info(f"[create_session] 会话 {session_id} 启动完成，phase={result.get('current_phase')}")
        # 写入会话元数据（title 取 user_request 前 20 字，preview 取 current_segment 前 80 字）
        session_store.save_session_meta({
            "session_id": session_id,
            "title": req.user_request[:20],
            "current_phase": result.get("current_phase", ""),
            "current_turn": result.get("current_turn", 0),
            "segment_count": len(result.get("story_segments", [])),
            "preview": result.get("current_segment", "")[:80],
        })
        return _state_to_response(result, session_id)
    except Exception as e:
        logger.exception(f"[create_session] 会话 {session_id} 启动失败：{e}")
        raise HTTPException(status_code=500, detail=f"启动失败：{str(e)}")


@app.post("/api/sessions/{session_id}/action", response_model=SessionResponse)
async def send_action(session_id: str, req: ActionRequest):
    """发送用户操作"""
    config = {"configurable": {"thread_id": session_id}}
    graph = app_graph_async or app_graph

    try:
        # 将用户操作转换为输入
        user_input = req.action
        if req.payload:
            user_input = req.payload

        logger.info(f"[send_action] 会话 {session_id} 收到操作 action={req.action!r} payload={req.payload!r} -> user_input={user_input!r}")

        # 先记录当前图状态，确认是否处于 interrupt 等待
        try:
            snap = await graph.aget_state(config)
            logger.info(f"[send_action] 当前状态 phase={snap.values.get('current_phase')} "
                        f"awaiting_user={snap.values.get('awaiting_user')} "
                        f"next={snap.next} tasks={snap.tasks}")
        except Exception as se:
            logger.warning(f"[send_action] 读取当前状态失败：{se}")

        try:
            result = await graph.ainvoke(Command(resume=user_input), config)
        except GraphInterrupt:
            # 图在下一轮中断处暂停，读取已 checkpoint 的状态返回
            logger.info(f"[send_action] 图在中断处暂停，读取当前状态返回")
            snap = await graph.aget_state(config)
            result = snap.values
        logger.info(f"[send_action] 会话 {session_id} 执行完成，phase={result.get('current_phase')}")
        # 更新会话元数据进度快照
        session_store.update_session_meta(session_id, {
            "current_phase": result.get("current_phase", ""),
            "current_turn": result.get("current_turn", 0),
            "segment_count": len(result.get("story_segments", [])),
            "preview": result.get("current_segment", "")[:80],
        })
        # 会话完成时保存长期记忆，用于后续续写
        if result.get("current_phase") == "done":
            long_term_memory.save_long_term_memory(session_id, result)
        return _state_to_response(result, session_id)
    except Exception as e:
        logger.exception(f"[send_action] 会话 {session_id} 执行失败：{e}")
        raise HTTPException(status_code=500, detail=f"执行失败：{str(e)}")


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """获取会话状态"""
    config = {"configurable": {"thread_id": session_id}}
    graph = app_graph_async or app_graph

    try:
        state = await graph.aget_state(config)
        if state is None:
            logger.warning(f"[get_session] 会话 {session_id} 不存在")
            raise HTTPException(status_code=404, detail="会话不存在")
        return _state_to_response(state.values, session_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[get_session] 会话 {session_id} 获取状态失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取状态失败：{str(e)}")


@app.get("/api/sessions")
async def list_sessions():
    """获取所有会话及进度摘要"""
    return session_store.list_session_metas()


@app.patch("/api/sessions/{session_id}")
async def update_session_title(session_id: str, req: UpdateTitleRequest):
    """更新会话标题"""
    existing = session_store.get_session_meta(session_id)
    if not existing:
        raise HTTPException(status_code=404, detail="会话不存在")
    session_store.update_session_meta(session_id, {"title": req.title})
    return session_store.get_session_meta(session_id)


@app.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    """删除会话元数据"""
    session_store.delete_session_meta(session_id)
    return None


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

    graph = app_graph_async if app_graph_async else app_graph

    # 获取当前状态（异步）
    try:
        current_state = await graph.aget_state(config)
        if current_state is None:
            raise HTTPException(status_code=404, detail="会话不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取状态失败：{str(e)}")

    async def event_generator():
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

            # 流结束后发送完整状态快照（异步获取）
            state = await graph.aget_state(config)
            # 更新会话元数据进度快照
            session_store.update_session_meta(session_id, {
                "current_phase": state.values.get("current_phase", ""),
                "current_turn": state.values.get("current_turn", 0),
                "segment_count": len(state.values.get("story_segments", [])),
                "preview": state.values.get("current_segment", "")[:80],
            })
            # 会话完成时保存长期记忆，用于后续续写
            if state.values.get("current_phase") == "done":
                long_term_memory.save_long_term_memory(session_id, state.values)
            final_resp = _state_to_response(state.values, session_id)
            yield format_sse_event("final", final_resp.model_dump())

        except Exception as e:
            logger.exception(f"[stream_session] 会话 {session_id} 流式执行失败：{e}")
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


@app.post("/api/sessions/{session_id}/resume", response_model=SessionResponse)
async def resume_session(session_id: str):
    """基于已完成的长期记忆续写新会话

    从长期记忆恢复世界观、角色、规则、记忆状态，清空剧情进度，
    生成新 session_id 并以 story_progressing 阶段启动图。
    """
    memory = long_term_memory.get_long_term_memory(session_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="长期记忆不存在")

    new_session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": new_session_id}}

    user_request = f"【续写】{memory['title']}：请基于已有世界观和剧情继续推进故事"
    initial_state = _build_initial_state(user_request)
    # 从长期记忆恢复世界观、角色、规则、记忆状态
    initial_state["world_setting"] = memory.get("world_setting", "")
    initial_state["characters"] = memory.get("characters", [])
    initial_state["rules"] = memory.get("rules", "")
    initial_state["memory"] = memory.get("memory_state", {})
    # 清空剧情相关字段，重新开始
    initial_state["story_segments"] = []
    initial_state["current_segment"] = ""
    initial_state["current_options"] = []
    initial_state["user_choices"] = []
    initial_state["segment_history"] = []
    initial_state["current_turn"] = 0
    initial_state["setting_confirmed"] = True
    initial_state["current_phase"] = "story_progressing"
    initial_state["awaiting_user"] = False

    graph = app_graph_async or app_graph

    try:
        logger.info(f"[resume_session] 从记忆 {session_id} 续写为新会话 {new_session_id}")
        try:
            result = await graph.ainvoke(initial_state, config)
        except GraphInterrupt:
            logger.info(f"[resume_session] 图在中断处暂停，读取当前状态返回")
            snap = await graph.aget_state(config)
            result = snap.values
        logger.info(f"[resume_session] 会话 {new_session_id} 启动完成，phase={result.get('current_phase')}")
        session_store.save_session_meta({
            "session_id": new_session_id,
            "title": memory.get("title", ""),
            "current_phase": result.get("current_phase", ""),
            "current_turn": result.get("current_turn", 0),
            "segment_count": len(result.get("story_segments", [])),
            "preview": result.get("current_segment", "")[:80],
        })
        return _state_to_response(result, new_session_id)
    except Exception as e:
        logger.exception(f"[resume_session] 会话 {new_session_id} 启动失败：{e}")
        raise HTTPException(status_code=500, detail=f"续写失败：{str(e)}")


@app.get("/api/memories")
async def list_memories():
    """获取所有长期记忆列表"""
    return long_term_memory.list_long_term_memories()


@app.get("/api/memories/{memory_id}")
async def get_memory(memory_id: str):
    """获取单条长期记忆详情"""
    memory = long_term_memory.get_long_term_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="长期记忆不存在")
    return memory


# ─── 静态文件（生产环境，作为 SPA fallback，需在 API 路由之后挂载）──

try:
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
except Exception:
    pass  # 开发模式下无前端构建产物


# ─── 启动入口 ──────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)