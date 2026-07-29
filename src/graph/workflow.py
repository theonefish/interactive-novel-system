"""LangGraph 图定义 - 编排多 Agent 协作流程"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

from src.graph.state import NovelState
from src.agents.supervisor import supervisor_node, supervisor_route
from src.agents.researcher import world_builder_node
from src.agents.writer import story_driver_node
from src.agents.reviewer import critic_node
from src.agents.integrator import integrator_node
from src.utils.database import get_checkpointer, is_postgres


def _build_workflow():
    """构建图结构（不含 checkpointer）"""
    workflow = StateGraph(NovelState)

    # 添加节点
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("world_builder", world_builder_node)
    workflow.add_node("story_driver", story_driver_node)
    workflow.add_node("critic", critic_node)
    workflow.add_node("integrator", integrator_node)

    # 设置入口
    workflow.set_entry_point("supervisor")

    # 条件边 - 从 supervisor 路由
    workflow.add_conditional_edges(
        "supervisor",
        supervisor_route,
        {
            "world_builder": "world_builder",
            "story_driver": "story_driver",
            "integrator": "integrator",
            "supervisor": "supervisor",
            END: END,
        }
    )

    # 固定边
    workflow.add_edge("world_builder", "supervisor")
    workflow.add_edge("story_driver", "critic")
    workflow.add_edge("critic", "supervisor")
    workflow.add_edge("integrator", "supervisor")

    return workflow


def build_graph():
    """构建 LangGraph 图（同步版本，SqliteSaver）"""
    workflow = _build_workflow()
    checkpointer = get_checkpointer()
    return workflow.compile(checkpointer=checkpointer)


async def build_graph_async():
    """构建 LangGraph 图（异步版本，支持 SSE 流式输出）"""
    workflow = _build_workflow()

    if is_postgres():
        from langgraph.checkpoint.postgres import PostgresSaver
        from src.utils.database import DATABASE_URL

        checkpointer = PostgresSaver.from_conn_string(DATABASE_URL)
        await checkpointer.setup()
    else:
        # 异步环境下用 SqliteSaver 同步兼容
        checkpointer = get_checkpointer()

    return workflow.compile(checkpointer=checkpointer)