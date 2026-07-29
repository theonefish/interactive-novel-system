"""定义聊天智能体（RAG Agent）"""
from langgraph.prebuilt import create_react_agent   # 修正1
from langgraph.checkpoint.memory import MemorySaver

from models.llm import qwen_llm
from .rag_tool import retrieve


def get_rag_agent():
    """创建带 RAG 检索工具的智能体"""
    prompt = ("你是一个知识库助手，请根据检索到的文档内容回答用户问题。"
              "如果文档中没有相关信息，请如实告知用户。"
              "回答时请条理清晰，分点说明。"
              "回答时使用中文，并去掉 Markdown 格式。")

    agent = create_react_agent(                   # 修正1：LangGraph 的正确 API
        model=qwen_llm,
        tools=[retrieve],
        prompt=prompt,
        checkpointer=MemorySaver(),               # 修正2：checkpointer 属于 LangGraph
    )
    return agent


def run_rag_agent(question: str):
    agent_executor = get_rag_agent()
    result = agent_executor.invoke(
        {"messages": [("human", question)]},
        config={"configurable": {"thread_id": "default"}},  # checkpointer 需要 thread_id
    )
    return result["messages"][-1].content
# async def stream_events(question: str):
#     # astream_events 流式输出事件, version="v2" 使用新版事件格式
#     # messages 以角色-内容格式传入用户问题
#     async for event in agent.astream_events(
#         {"messages": [{"role": "user", "content": question}]},
#         version="v2",
#     ):
#         # on_chat_model_stream 事件类型表示大模型正在逐 token 生成
#         kind = event.get("event", "")
#         if kind == "on_chat_model_stream":
#             content = event["data"]["chunk"].content
#             if content:
#                 # SSE 格式: data: {json}\n\n
#                 data = json.dumps({"event": "on_chat_model_stream", "data": {"chunk": {"content": content}}})
#                 yield f"data: {data}\n\n"