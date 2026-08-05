"""FastAPI 服务�?- 提供 REST API 和静态文件服�?""

import uuid

from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.graph.workflow import build_graph_async
from src.graph.state import NovelState
from src.tools import long_term_memory
from src.tools.memory import create_initial_memory
from src.utils import session_store

from src.utils.streaming import transform_graph_events, format_sse_event
from src.utils.logger import setup_logger
from langgraph.types import Command
from langgraph.errors import GraphInterrupt

logger = setup_logger("server")


# ─── 全局应用实例 ──────────────────────────────────

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

    # 修正：无�?SQLite 还是 Postgres，都初始化异步图
    app_graph_async = await build_graph_async()
    logger.info("[lifespan] 异步图初始化完成")

    yield

    # ── 关闭时清�?──
    # 异步�?
    if app_graph_async and hasattr(app_graph_async, "checkpointer"):
        cp = app_graph_async.checkpointer
        if hasattr(cp, "conn") and hasattr(cp.conn, "close"):
            await cp.conn.close()  # aiosqlite 连接需�?await close
            logger.info("[lifespan] 异步 checkpointer 连接已关�?)



app = FastAPI(title="交互式小说创作系�?, lifespan=lifespan)

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
    """构建初始状�?""
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
    """�?LangGraph 状态转换为 API 响应"""
    phase = state.get("current_phase", "init")

    # 阶段到展示名的映射（其余统一视为处理中）
    phase_map = {
        "world_building": "world_building",
        "story_progressing": "story_progressing",
        "completed": "completed",
        "done": "done",
    }
    display_phase = phase_map.get(phase, "processing")

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


async def _run_graph(graph, graph_input, config) -> dict:
    """执行图并返回最终状态（兼容 interrupt 暂停兜底�?""
    try:
        return await graph.ainvoke(graph_input, config)  # 正常跑完
    except GraphInterrupt:
        # 图在中断处暂停，读取�?checkpoint 的状态返�?
        snap = await graph.aget_state(config)
        return snap.values


def _save_meta(session_id: str, state: dict, title: Optional[str] = None):
    """根据图状态写�?更新会话元数�?""
    meta = {
        "session_id": session_id,
        "current_phase": state.get("current_phase", ""),
        "current_turn": state.get("current_turn", 0),
        "segment_count": len(state.get("story_segments", [])),  # 已生成的剧情段数
        "preview": state.get("current_segment", "")[:80],  # 当前段前 80 字作预览
    }
    if title is not None:  # 新建时带 title，更新时忽略
        meta["title"] = title
    if state.get("current_phase") == "done":  # 会话完成：持久化长期记忆供续�?
        long_term_memory.save_long_term_memory(session_id, state)
    session_store.save_session_meta(meta) if title is not None else session_store.update_session_meta(session_id, meta)


# ─── API 路由 ──────────────────────────────────────

@app.post("/api/sessions", response_model=SessionResponse)
async def create_session(req: CreateSessionRequest):
    """创建新会�?""
    if not req.user_request.strip():
        raise HTTPException(status_code=400, detail="创作需求不能为�?)

    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    initial_state = _build_initial_state(req.user_request)
    graph = app_graph_async

    try:
        logger.info(f"[create_session] 新建会话 {session_id}，user_request={req.user_request!r}")
        result = await _run_graph(graph, initial_state, config)
        logger.info(f"[create_session] 会话 {session_id} 启动完成，phase={result.get('current_phase')}")
        _save_meta(session_id, result, title=req.user_request[:20])  # 第一条记录带 title
        return _state_to_response(result, session_id)
    except Exception as e:
        logger.exception(f"[create_session] 会话 {session_id} 启动失败：{e}")
        raise HTTPException(status_code=500, detail=f"启动失败：{str(e)}")


@app.post("/api/sessions/{session_id}/action", response_model=SessionResponse)
async def send_action(session_id: str, req: ActionRequest):
    """发送用户操�?""
    config = {"configurable": {"thread_id": session_id}}
    graph = app_graph_async

    try:
        # 将用户操作转换为输入
        user_input = req.action
        if req.payload:
            user_input = req.payload

        logger.info(f"[send_action] 会话 {session_id} 收到操作 action={req.action!r} payload={req.payload!r} -> user_input={user_input!r}")

        # �?Command(resume=...) 恢复被中断的图并继续执行
        result = await _run_graph(graph, Command(resume=user_input), config)
        logger.info(f"[send_action] 会话 {session_id} 执行完成，phase={result.get('current_phase')}")
        _save_meta(session_id, result)  # 更新进度快照（done 时自动存长期记忆�?
        return _state_to_response(result, session_id)
    except Exception as e:
        logger.exception(f"[send_action] 会话 {session_id} 执行失败：{e}")
        raise HTTPException(status_code=500, detail=f"执行失败：{str(e)}")


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """获取会话状�?""
    config = {"configurable": {"thread_id": session_id}}
    graph = app_graph_async

    try:
        state = await graph.aget_state(config)
        if state is None:
            logger.warning(f"[get_session] 会话 {session_id} 不存�?)
            raise HTTPException(status_code=404, detail="会话不存�?)
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
        raise HTTPException(status_code=404, detail="会话不存�?)
    session_store.update_session_meta(session_id, {"title": req.title})
    return session_store.get_session_meta(session_id)


@app.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    """删除会话元数�?""
    session_store.delete_session_meta(session_id)
    return None


@app.get("/api/sessions/{session_id}/stream")
async def stream_session(session_id: str, request: Request, action: str = Query("")):
    """SSE 流式输出 - 逐节�?�?token 推送图执行结果

    通过 EventSource 消费，事件类型：
    - node_start: 节点开�?
    - node_end: 节点完成（含关键状态字段，�?story_driver �?current_segment�?
    - token: LLM token 片段（附 node 字段标明来源节点�?
    - interrupt: 中断等待用户
    - error: 执行错误
    - final: 流结束后的完整状态快照（前端据此一次性渲染选项/世界观等�?
    - done: 流结�?

    前端在用户做出选择后调用此接口（action=用户输入），后端�?
    Command(resume=action) 恢复被中断的图并流式执行�?
    """
    config = {"configurable": {"thread_id": session_id}}

    graph = app_graph_async

    # 获取当前状态（异步�?
    try:
        current_state = await graph.aget_state(config)
        if current_state is None:
            raise HTTPException(status_code=404, detail="会话不存�?)
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

            # 流结束后发送完整状态快照（异步获取�?
            state = await graph.aget_state(config)
            _save_meta(session_id, state.values)  # 复用同一套进�?记忆写入
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
    """基于已完成的长期记忆续写新会�?

    从长期记忆恢复世界观、角色、规则、记忆状态，清空剧情进度�?
    生成�?session_id 并以 story_progressing 阶段启动图�?
    """
    memory = long_term_memory.get_long_term_memory(session_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="长期记忆不存�?)

    new_session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": new_session_id}}

    # 保留原剧情作为上下文，story_driver 会基于此续写而非重写
    prev_segments = memory.get("story_segments", []) or []
    prev_turn = len(prev_segments)
    user_request = f"【续写】{memory['title']}：请基于已有世界观和已有剧情继续推进故事，不要重复已有内�?
    initial_state = _build_initial_state(user_request)
    # 从长期记忆恢复世界观、角色、规则、记忆状�?
    initial_state["world_setting"] = memory.get("world_setting", "")
    initial_state["characters"] = memory.get("characters", [])
    initial_state["rules"] = memory.get("rules", "")
    initial_state["memory"] = memory.get("memory_state", {})
    # 保留原有剧情片段作为上下文，续写新内容会追加到其�?
    initial_state["story_segments"] = list(prev_segments)
    initial_state["current_segment"] = prev_segments[-1] if prev_segments else ""
    # 重置交互状态：turn 接续原进度，清空用户选择与选项历史
    initial_state["current_options"] = []
    initial_state["user_choices"] = []
    initial_state["segment_history"] = []
    initial_state["current_turn"] = prev_turn
    initial_state["setting_confirmed"] = True
    initial_state["current_phase"] = "story_progressing"
    initial_state["awaiting_user"] = False

    graph = app_graph_async

    try:
        logger.info(f"[resume_session] 从记�?{session_id} 续写为新会话 {new_session_id}")
        result = await _run_graph(graph, initial_state, config)
        logger.info(f"[resume_session] 会话 {new_session_id} 启动完成，phase={result.get('current_phase')}")
        _save_meta(new_session_id, result, title=memory.get("title", ""))  # 续写记录带原标题
        return _state_to_response(result, new_session_id)
    except Exception as e:
        logger.exception(f"[resume_session] 会话 {new_session_id} 启动失败：{e}")
        raise HTTPException(status_code=500, detail=f"续写失败：{str(e)}")


@app.get("/api/memories")
async def list_memories():
    """获取所有长期记忆列�?""
    return long_term_memory.list_long_term_memories()


@app.get("/api/memories/{memory_id}")
async def get_memory(memory_id: str):
    """获取单条长期记忆详情"""
    memory = long_term_memory.get_long_term_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="长期记忆不存�?)
    return memory


# ─── 静态文件（生产环境，作�?SPA fallback，需�?API 路由之后挂载）──

try:
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
except Exception:
    pass  # 开发模式下无前端构建产�?


# ─── 启动入口 ──────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
