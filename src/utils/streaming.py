"""流式事件转换工具 - 将 LangGraph astream_events 输出转为 SSE 格式"""

import json
from typing import AsyncGenerator, Dict, Any


def format_sse_event(event_type: str, data: Dict[str, Any]) -> str:
    """格式化 SSE 事件"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def transform_graph_events(
    async_gen: AsyncGenerator[Dict[str, Any], None],
) -> AsyncGenerator[str, None]:
    """将 LangGraph astream_events 转换为 SSE 事件流

    支持的事件类型：
    - on_chain_start: 节点开始执行
    - on_chain_end: 节点执行完成
    - on_chat_model_stream: LLM token 片段（附带来源节点名）
    - on_chain_error: 节点执行错误
    - on_custom_event: 自定义事件（如 interrupt）

    注意：token 事件会附带 current_node（最近一次 on_chain_start 的节点名），
    前端可据此判断 token 来自哪个节点（例如 story_driver 产出正文）。
    """
    current_node = None
    async for event in async_gen:
        event_kind = event.get("event", "")
        name = event.get("name", "")
        data = event.get("data", {})

        if event_kind == "on_chain_start":
            current_node = name
            yield format_sse_event("node_start", {
                "node": name,
                "input": data.get("input"),
            })

        elif event_kind == "on_chain_end":
            output = data.get("output", {})
            # 过滤掉中间状态，只保留关键字段
            filtered = {
                k: output.get(k)
                for k in ("current_segment", "current_options", "current_phase",
                          "current_turn", "critique", "critique_score",
                          "final_output", "world_setting", "characters", "rules")
                if k in output
            }
            yield format_sse_event("node_end", {
                "node": name,
                "output": filtered,
            })

        elif event_kind == "on_chat_model_stream":
            chunk = data.get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                yield format_sse_event("token", {
                    "node": current_node,
                    "content": chunk.content,
                })

        elif event_kind == "on_chain_error":
            yield format_sse_event("error", {
                "node": name,
                "error": str(data.get("error", "")),
            })

        elif event_kind == "on_custom_event":
            # 自定义事件（如 interrupt）
            yield format_sse_event("interrupt", {
                "data": data,
            })