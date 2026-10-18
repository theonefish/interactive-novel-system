"""SSE 事件归属的回归测试（纯标准库）。"""

import asyncio

from src.utils.streaming import _graph_node, transform_graph_events


def _collect(events):
    async def gen():
        for event in events:
            yield event

    async def run():
        return [chunk async for chunk in transform_graph_events(gen())]

    return asyncio.run(run())


def _event_kind(chunk):
    return chunk.split("\n", 1)[0].replace("event: ", "")


def test_graph_node_resolution():
    assert _graph_node({"name": "critic"}) == "critic"                      # 兜底：已知节点名
    assert _graph_node({"name": "RunnableSequence"}) == ""                  # 嵌套 runnable 不算节点
    assert _graph_node({"name": "LangGraph"}) == ""
    assert _graph_node({"name": "x", "metadata": {"langgraph_node": "review_gate"}}) == "review_gate"
    assert _graph_node({}) == ""


def test_nested_runnables_do_not_produce_node_events():
    class _Chunk:
        content = "字"

    events = [
        {"event": "on_chain_start", "name": "LangGraph", "data": {}},
        {"event": "on_chain_start", "name": "RunnableSequence", "data": {}},
        {"event": "on_chain_start", "name": "story_driver",
         "metadata": {"langgraph_node": "story_driver"}, "data": {"input": {}}},
        {"event": "on_chat_model_stream", "name": "ChatOpenAI",
         "metadata": {"langgraph_node": "story_driver"}, "data": {"chunk": _Chunk()}},
        {"event": "on_chain_end", "name": "story_driver",
         "metadata": {"langgraph_node": "story_driver"},
         "data": {"output": {"current_segment": "正文内容", "current_turn": 1}}},
    ]

    out = _collect(events)

    assert [_event_kind(c) for c in out] == ["node_start", "token", "node_end"]
    assert '"node": "story_driver"' in out[0]
    assert '"node": "story_driver"' in out[1]      # token 归属到图节点，而不是 ChatOpenAI
    assert "正文内容" in out[2]
    assert "ChatOpenAI" not in "".join(out)
