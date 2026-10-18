"""FastAPI 服务层 - 提供 REST API 和静态文件服务"""

import uuid
import asyncio
from pathlib import Path

from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.graph.workflow import build_graph_async
from src.graph.state import NovelState
from src.tools import long_term_memory
from src.tools.memory import create_initial_memory
from src.utils import session_store, usage

from src.utils.streaming import transform_graph_events, format_sse_event
from src.utils.logger import setup_logger
from langgraph.types import Command
from langgraph.errors import GraphInterrupt

logger = setup_logger("server")


# 全局持有已编译的 LangGraph 异步图（在 lifespan 启动时构建，生命周期内复用）。
# 所有接口都从这个单例取图执行，避免每次请求重新编译图。
app_graph_async = None

# 正在执行的会话（同一会话同时只允许一个执行中的请求）。
# 前端已做了按钮防抖，这里是服务端兜底：重复点击/并发 resume 会把同一个
# thread 的 checkpoint 写乱，所以直接拒绝第二个请求。
# 单事件循环内「判断 + 加入」之间没有 await，因此用普通 set 即可。
_running_sessions: set = set()

# 正在续写的「来源记忆」：同一份长期记忆同时只允许一次续写。
# 连点「续写」会各自生成新的 session_id，按 session_id 挡不住，必须按来源记忆挡。
_resuming_memories: set = set()


# 请求/响应模型（Pydantic，用于接口入参校验与出参序列化）

class CreateSessionRequest(BaseModel):
    user_request: str  # 用户的创作需求（小说主题/世界观设定要求等）


class ActionRequest(BaseModel):
    action: str  # 用户操作类型（也作为默认输入文本）
    payload: Optional[str] = None  # 可选：具体的用户输入内容（选 A/B/C 或自由文本），优先级高于 action


class UpdateTitleRequest(BaseModel):
    title: str  # 会话标题


class SessionResponse(BaseModel):
    # 返回给前端的完整状态快照：当前阶段、轮次、剧情片段、选项、世界观、审查结果、最终正文等
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
    segment_count: int = 0  # 已生成的剧情段数（前端顶部计数用，刷新后也能对上）
    human_approval: Optional[str] = None
    review: Optional[dict] = None
    error: str = ""


# 辅助函数


# 人工审核相关的 interrupt 类型：只有这些才会驱动前端弹出审核面板
REVIEW_KINDS = ("setting_confirm", "setting_review", "segment_review")


def _interrupt_payload(value):
    """把单个 interrupt 条目转成 dict 载荷（拿不到 dict 时返回 None）。"""
    if isinstance(value, dict):
        return value
    inner = getattr(value, "value", None)
    return inner if isinstance(inner, dict) else None


def _first_interrupt(interrupts):
    """从 interrupt 集合里取第一个 dict 载荷。"""
    if interrupts is None:
        return None
    if not isinstance(interrupts, (list, tuple)):
        interrupts = [interrupts]
    for item in interrupts:
        payload = _interrupt_payload(item)
        if payload is not None:
            return payload
    return None


def _extract_interrupt(snapshot):
    """从 LangGraph 状态快照 / ainvoke 结果中取出 interrupt 载荷。

    兼容三种形态：
    1. snapshot.interrupts（新版直接暴露）
    2. snapshot.tasks[*].interrupts[*]（Interrupt 对象用 .value 取载荷）
    3. ainvoke 返回的 state dict 里的 "__interrupt__"
    取不到时返回 None，不抛异常。
    """
    if snapshot is None:
        return None
    if isinstance(snapshot, dict):
        return _first_interrupt(snapshot.get("__interrupt__"))

    found = _first_interrupt(getattr(snapshot, "interrupts", None))
    if found is not None:
        return found

    task_interrupts = [
        item
        for task in (getattr(snapshot, "tasks", None) or ())
        for item in (getattr(task, "interrupts", None) or ())
    ]
    return _first_interrupt(task_interrupts)


def _state_to_response(
    state: dict,
    session_id: str,
    interrupt: dict = None,
) -> SessionResponse:
    """将 LangGraph 返回的内部状态（dict）裁剪/映射为对外暴露的 SessionResponse。
    只挑选前端需要的字段，避免把 messages 等大对象直接吐给前端。

    当图暂停在人工审核（世界观确认 / 设定审核 / 剧情审核）时，由 interrupt
    载荷额外输出 human_approval="pending" 与 review，驱动前端弹出审核面板。
    """
    phase = state.get("current_phase", "init")

    # 阶段到展示名的映射（其余统一视为处理中）
    phase_map = {
        "world_building": "world_building",
        "story_progressing": "story_progressing",
        "completed": "completed",
        "done": "done",
        "review_pending": "story_progressing",  # 等审核时仍属剧情推进
    }
    display_phase = phase_map.get(phase, "processing")

    human_approval = state.get("human_approval")
    review = None
    # interrupt 是最新一次的挂起载荷；state["pending_review"] 用于刷新页面后的兜底
    if isinstance(interrupt, dict) and interrupt.get("kind") in REVIEW_KINDS:
        review = interrupt
    elif isinstance(state.get("pending_review"), dict) and state["pending_review"].get("kind") in REVIEW_KINDS:
        review = state["pending_review"]
    if review is not None:
        human_approval = "pending"

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
        segment_count=len(state.get("story_segments") or []),
        human_approval=human_approval,
        review=review,
        error=state.get("error", ""),
    )


async def _run_graph(graph, graph_input, config):
    """执行图并返回 (状态值, interrupt 载荷)。

    当图中调用 interrupt()（等待用户选择 / 人工审核）时 LangGraph 会暂停：
    - 部分版本直接抛 GraphInterrupt，此时状态已 checkpoint，读取快照返回；
    - 部分版本不抛异常，而是把 __interrupt__ 放进返回的 state 里。
    两条路径都解析出 interrupt 载荷，交给上层渲染审核面板。
    """
    try:
        result = await graph.ainvoke(graph_input, config)
    except GraphInterrupt:
        # 图在中断处暂停，读取已 checkpoint 的状态返回
        snap = await graph.aget_state(config)
        return snap.values, _extract_interrupt(snap)

    return result, _extract_interrupt(result)


def _save_meta(session_id: str, state: dict, title: Optional[str] = None):
    """根据图状态写入/更新会话元数据（session_metas 表）。
    - 新建会话时带 title 用 save_session_meta；
    - 后续更新用 update_session_meta；
    - 会话进入 done 时额外持久化长期记忆（long_term_memories 表），供续写接口恢复。"""
    meta = {
        "session_id": session_id,
        "current_phase": state.get("current_phase", ""),
        "current_turn": state.get("current_turn", 0),
        "segment_count": len(state.get("story_segments", [])),  # 已生成的前情段落数
        "preview": state.get("current_segment", "")[:80],  # 当前段前 80 字作预览
    }
    if title is not None:  # 新建时带 title，更新时忽略
        meta["title"] = title
    if state.get("current_phase") == "done":  # 会话完成：持久化长期记忆供续写
        long_term_memory.save_long_term_memory(session_id, state)
    session_store.save_session_meta(meta) if title is not None else session_store.update_session_meta(session_id, meta)


# API 路由


# 生命周期管理：应用启动时构建图、关闭时释放 checkpointer 连接
@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_graph_async

    # 初始化异步图
    app_graph_async = await build_graph_async()  # 编译 LangGraph 并挂载 SQLite checkpointer
    logger.info("[lifespan] 异步图初始化完成")

    yield

    # ─── 关闭时清理 ───
    # 异步图
    if app_graph_async and hasattr(app_graph_async, "checkpointer"):
        cp = app_graph_async.checkpointer
        if hasattr(cp, "conn") and hasattr(cp.conn, "close"):
            await cp.conn.close()  # aiosqlite 连接需要 await close
            logger.info("[lifespan] 异步 checkpointer 连接已关闭")


app = FastAPI(title="交互式小说创作系统", lifespan=lifespan)

# CORS：允许前端跨域调用（开发期放开全部来源，生产应收紧 allow_origins）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 辅助函数

def _build_initial_state(user_request: str) -> NovelState:
    """构建初始状态：把所有 NovelState 字段初始化为空白/起始值，current_phase=init 让图从 world_builder 起步。"""
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
        "error": "",
        "memory": create_initial_memory([]),
        "messages": [],
        "human_approval": None,
        "pending_review": None,
        "current_phase": "init",
        "iteration_count": 0,
        "max_internal_iterations": 3,
    }


@app.post("/api/sessions", response_model=SessionResponse)
async def create_session(req: CreateSessionRequest):
    """创建新会话：构建初始状态 → 跑图（生成世界观/角色/规则并审查、等待用户确认）→ 返回首屏状态。
    用 session_id 作为 LangGraph 的 thread_id，使该会话后续的 action/stream 能复用同一份 checkpoint。"""
    if not req.user_request.strip():
        raise HTTPException(status_code=400, detail="创作需求不能为空")

    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    initial_state = _build_initial_state(req.user_request)
    graph = app_graph_async

    try:
        logger.info(f"[create_session] 新建会话 {session_id}，user_request={req.user_request!r}")
        result, interrupt_payload = await _run_graph(graph, initial_state, config)
        logger.info(f"[create_session] 会话 {session_id} 启动完成，phase={result.get('current_phase')}")
        _save_meta(session_id, result, title=req.user_request[:20])  # 第一条记录带 title
        return _state_to_response(result, session_id, interrupt_payload)
    except Exception as e:
        logger.exception(f"[create_session] 会话 {session_id} 启动失败：{e}")
        raise HTTPException(status_code=500, detail=f"启动失败：{str(e)}")


@app.post("/api/sessions/{session_id}/action", response_model=SessionResponse)
async def send_action(session_id: str, req: ActionRequest):
    """发送用户操作（非流式）：接收用户在选项面板上的选择/自由输入。
    用 Command(resume=...) 恢复被 interrupt 暂停的图，让 supervisor 从 _get_resume_input 取到输入并继续推进。"""
    config = {"configurable": {"thread_id": session_id}}
    graph = app_graph_async

    if session_id in _running_sessions:
        logger.warning(f"[send_action] 会话 {session_id} 正在执行中，拒绝重复请求")
        raise HTTPException(status_code=409, detail="该会话正在生成中，请稍候再试")

    _running_sessions.add(session_id)
    try:
        # 将用户操作转换为输入
        user_input = req.action
        if req.payload:
            user_input = req.payload

        logger.info(f"[send_action] 会话 {session_id} 收到操作 action={req.action!r} payload={req.payload!r} -> user_input={user_input!r}")

        # 用 Command(resume=...) 恢复被中断的图并继续执行
        result, interrupt_payload = await _run_graph(graph, Command(resume=user_input), config)
        logger.info(f"[send_action] 会话 {session_id} 执行完成，phase={result.get('current_phase')}")
        _save_meta(session_id, result)  # 更新进度快照（done 时自动存长期记忆）
        return _state_to_response(result, session_id, interrupt_payload)
    except Exception as e:
        logger.exception(f"[send_action] 会话 {session_id} 执行失败：{e}")
        raise HTTPException(status_code=500, detail=f"执行失败：{str(e)}")
    finally:
        _running_sessions.discard(session_id)


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """获取会话状态：从 checkpointer 直接读取某 thread 的最新状态快照，不做图执行。用于刷新/恢复页面。"""
    config = {"configurable": {"thread_id": session_id}}
    graph = app_graph_async

    try:
        state = await graph.aget_state(config)
        if state is None:
            logger.warning(f"[get_session] 会话 {session_id} 不存在")
            raise HTTPException(status_code=404, detail="会话不存在")
        return _state_to_response(state.values, session_id, _extract_interrupt(state))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[get_session] 会话 {session_id} 获取状态失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取状态失败：{str(e)}")


@app.get("/api/sessions")
async def list_sessions():
    """获取所有会话及进度摘要（会话列表页用），直接读 session_metas 表。"""
    return session_store.list_session_metas()


@app.patch("/api/sessions/{session_id}")
async def update_session_title(session_id: str, req: UpdateTitleRequest):
    """更新会话标题：仅在会话已存在时允许修改 session_metas 表的 title 字段。"""
    existing = session_store.get_session_meta(session_id)
    if not existing:
        raise HTTPException(status_code=404, detail="会话不存在")
    session_store.update_session_meta(session_id, {"title": req.title})
    return session_store.get_session_meta(session_id)


@app.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    """删除会话元数据：仅删 session_metas 记录（长期记忆与 checkpoint 不在此清理）。"""
    session_store.delete_session_meta(session_id)
    return None


@app.get("/api/sessions/{session_id}/stream")
async def stream_session(session_id: str, request: Request, action: str = Query("")):
    """SSE 流式输出 - 逐节点/逐 token 推进图执行结果

    通过 EventSource 消费，事件类型：
    - node_start: 节点开始
    - node_end: 节点完成（含关键状态字段，如 story_driver 的 current_segment）
    - token: LLM token 片段（附 node 字段标明来源节点）
    - interrupt: 中断等待用户
    - error: 执行错误
    - final: 流结束后完整状态快照（前端据此一次性刷新选项/世界观等）
    - done: 流结束

    前端在用户做出选择后调用此接口（action=用户输入），后端用
    Command(resume=action) 恢复被中断的图并流式执行。
    """
    config = {"configurable": {"thread_id": session_id}}

    graph = app_graph_async

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

        if session_id in _running_sessions:
            logger.warning(f"[stream_session] 会话 {session_id} 正在执行中，拒绝并发流")
            yield format_sse_event("error", {"error": "该会话正在生成中，请稍候再试"})
            yield format_sse_event("done", {"message": "stream complete"})
            return

        _running_sessions.add(session_id)
        try:
            # 使用 astream_events 流式执行，将用户输入恢复给被中断的图
            # （action 经 Command(resume=action) 传入，supervisor 的 interrupt 处即可取到）
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
            _save_meta(session_id, state.values)  # 复用同一套进度记录写入
            # 停在人工审核时，先补发 interrupt 事件，再发最终快照
            interrupt_payload = _extract_interrupt(state)
            if interrupt_payload and interrupt_payload.get("kind") in REVIEW_KINDS:
                yield format_sse_event("interrupt", interrupt_payload)
            final_resp = _state_to_response(state.values, session_id, interrupt_payload)
            yield format_sse_event("final", final_resp.model_dump())

        except Exception as e:
            logger.exception(f"[stream_session] 会话 {session_id} 流式执行失败：{e}")
            yield format_sse_event("error", {"error": str(e)})
        finally:
            _running_sessions.discard(session_id)
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

    从长期记忆恢复世界观、角色、规则、记忆状态，清空前情进度，
    生成新 session_id 并以 story_progressing 阶段启动图。
    """
    # 并发闸门放在最前：同一份记忆同时在续写时直接拒绝（连点会造出多个重复会话）
    if session_id in _resuming_memories:
        logger.warning(f"[resume_session] 记忆 {session_id} 正在续写中，拒绝重复请求")
        raise HTTPException(status_code=409, detail="该会话正在续写中，请稍候再试")

    memory = long_term_memory.get_long_term_memory(session_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="长期记忆不存在")

    _resuming_memories.add(session_id)

    new_session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": new_session_id}}

    # 保留原剧情作为上下文，story_driver 会基于此续写而非重写
    prev_segments = memory.get("story_segments", []) or []
    prev_turn = len(prev_segments)
    # 构造续写提示：带上原标题，并要求 LLM 基于已有世界观/前情推进、避免重复
    user_request = f"【续写】{memory['title']}：请基于已有世界观和已有前情继续推进故事，不要重复已存在内容"
    initial_state = _build_initial_state(user_request)
    # 从长期记忆恢复世界观、角色、规则、记忆状态（跳过 world_builder，直接进入剧情推进）
    initial_state["world_setting"] = memory.get("world_setting", "")
    initial_state["characters"] = memory.get("characters", [])
    initial_state["rules"] = memory.get("rules", "")
    initial_state["memory"] = memory.get("memory_state", {})
    # 保留原前情片段作为上下文，续写新内容会追加到其后
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
        logger.info(f"[resume_session] 从记忆 {session_id} 续写为新会话 {new_session_id}")
        result, interrupt_payload = await _run_graph(graph, initial_state, config)
        logger.info(f"[resume_session] 会话 {new_session_id} 启动完成，phase={result.get('current_phase')}")
        _save_meta(new_session_id, result, title=memory.get("title", ""))  # 续写记录带原标题
        return _state_to_response(result, new_session_id, interrupt_payload)
    except Exception as e:
        logger.exception(f"[resume_session] 会话 {new_session_id} 启动失败：{e}")
        raise HTTPException(status_code=500, detail=f"续写失败：{str(e)}")
    finally:
        _resuming_memories.discard(session_id)


@app.get("/api/usage")
async def get_usage():
    """查看 LLM token 用量（按节点汇总 + 最近调用明细），用于对账与优化。"""
    return usage.summarize_usage()


@app.get("/api/memories")
async def list_memories():
    """获取所有长期记忆列表（续写入口页用），读 long_term_memories 表。"""
    return long_term_memory.list_long_term_memories()


@app.get("/api/memories/{memory_id}")
async def get_memory(memory_id: str):
    """获取单条长期记忆详情（debug/预览用）。"""
    memory = long_term_memory.get_long_term_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="长期记忆不存在")
    return memory


# ─── 参考文件上传（知识库入库） ───────────────────────────
# 上传的参考文件保存到项目根目录的 knowledge_base/，
# 与 document_util.create_index_from_dir 的批量入库目录保持一致。

KNOWLEDGE_BASE_DIR = Path(__file__).resolve().parent / "knowledge_base"


def _safe_upload_name(filename: str) -> str:
    """把上传文件名净化成纯文件名（丢掉任何目录部分）。

    浏览器/脚本可能传来 "../../evil.txt" 这类名字，直接拼路径会写到
    knowledge_base/ 之外，甚至覆盖项目文件。
    """
    name = Path(str(filename or "").replace("\\", "/")).name.strip()
    return "" if name in ("", ".", "..") else name


def _knowledge_save_path(filename: str) -> Path:
    """把净化后的文件名映射到 knowledge_base 内的路径；越界直接 400。"""
    base = KNOWLEDGE_BASE_DIR.resolve()
    save_path = (base / filename).resolve()
    if not save_path.is_relative_to(base):
        raise HTTPException(status_code=400, detail="文件名不合法")
    return save_path


def _normalize_text_bytes(content: bytes) -> bytes:
    """把文本文件内容统一转成 UTF-8 编码。

    白话：中文 Windows 下保存的 txt/md 常见是 GBK 编码，
    而后续 TextLoader 固定按 UTF-8 读取会直接报错。
    这里先按 UTF-8 试解码，失败就按 GBK 解码再重新编码为 UTF-8，
    保证落盘的文件一定能被正确解析。"""
    try:
        content.decode("utf-8")
        return content  # 本来就是 UTF-8，原样返回
    except UnicodeDecodeError:
        try:
            return content.decode("gbk").encode("utf-8")
        except UnicodeDecodeError:
            return content  # 两种编码都解不了，原样返回，交给 Loader 去报错


def _ingest_file_to_chroma(save_path: Path):
    """把单个文件入库到 Chroma：加载 → 分割 → 向量化写入。

    注意：这是一个耗时的同步操作（每个片段都要调 embedding API），
    调用方必须用 asyncio.to_thread 放到线程池里跑，避免阻塞事件循环。

    返回 (原始文档数, 分割后的片段数)。"""
    from src.tools.document_util import load_documents, split_documents
    from src.tools.rag_tool import _get_vector_store

    docs = load_documents(str(save_path))
    chunks = split_documents(docs)
    if chunks:
        vector_store = _get_vector_store()
        vector_store.add_documents(chunks)
    return len(docs), len(chunks)


@app.post("/api/knowledge/upload")
async def upload_knowledge_file(file: UploadFile = File(...)):
    """上传参考文件：保存到 knowledge_base/ → 解析分割 → 入库 Chroma 向量库。

    入库后，写作 Agent 创作剧情时会通过 RAG 检索自动引用这些内容作为参考。
    支持 txt / md / pdf / docx / csv 五种格式。
    """
    from src.tools.document_util import SUPPORTED_FORMATS

    # 1. 校验文件名与格式（文件名先净化，去掉任何路径部分）
    filename = _safe_upload_name(file.filename or "")
    if not filename:
        raise HTTPException(status_code=400, detail="文件名不合法")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的格式 {suffix or '(无后缀)'}，仅支持 txt/md/pdf/docx/csv",
        )

    # 2. 读取内容；文本类文件做编码规范化，避免 GBK 文件解析失败
    content = await file.read()
    if suffix in (".txt", ".md", ".csv"):
        content = _normalize_text_bytes(content)

    # 3. 保存到知识库目录
    KNOWLEDGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    save_path = _knowledge_save_path(filename)
    save_path.write_bytes(content)

    # 4. 解析 + 入库（丢线程池执行，不阻塞服务）
    try:
        docs_count, chunk_count = await asyncio.to_thread(
            _ingest_file_to_chroma, save_path
        )
    except Exception as e:
        # 入库失败时删掉已保存的文件，保持知识库目录干净
        save_path.unlink(missing_ok=True)
        logger.exception(f"[upload] 文件 {filename} 入库失败：{e}")
        raise HTTPException(status_code=500, detail=f"入库失败：{str(e)}")

    if chunk_count == 0:
        save_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="文件解析后没有有效内容，请检查文件")

    logger.info(f"[upload] 文件 {filename} 入库完成：{docs_count} 个文档 / {chunk_count} 个片段")
    return {
        "filename": filename,
        "documents": docs_count,
        "chunks": chunk_count,
        "message": f"已入库 {chunk_count} 个片段，AI 创作时将自动作为参考",
    }

@app.get("/api/knowledge/files")
async def list_knowledge_files():
    """列出知识库目录中已上传的参考文件（前端上传区展示用）。"""
    from src.tools.document_util import SUPPORTED_FORMATS

    if not KNOWLEDGE_BASE_DIR.exists():
        return []
    files = []
    for p in sorted(KNOWLEDGE_BASE_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in SUPPORTED_FORMATS:
            files.append({"filename": p.name, "size": p.stat().st_size})
    return files


# 静态文件（生产环境）：在所有 API 路由之后挂载，作为 SPA fallback 提供前端构建产物。
# 开发模式下 frontend/dist 不存在则静默跳过（直接调 API 即可）。
try:
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
except Exception:
    pass  # 开发模式下无前端构建产物


# 启动入口：直接用 uvicorn 拉起 FastAPI（生产可改用 gunicorn + uvicorn worker）。
# 端口 8001 需与前端 API 基址一致。


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)