"""LangGraph 图定义 - 编排多 Agent 协作流程"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.graph.state import NovelState
from src.agents.supervisor import supervisor_node, supervisor_route, critic_route
from src.agents.researcher import world_builder_node
from src.agents.writer import story_driver_node
from src.agents.reviewer import critic_node
from src.agents.integrator import integrator_node
from src.utils.database import get_db_path
from src.utils.logger import setup_logger

logger = setup_logger("workflow")

def _build_workflow():
    """构建图结构"""
    workflow = StateGraph(NovelState)

    # 添加节点
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("world_builder", world_builder_node)
    workflow.add_node("story_driver", story_driver_node)
    workflow.add_node("critic", critic_node)
    workflow.add_node("integrator", integrator_node)

    # 设置入口
    workflow.set_entry_point("supervisor")

    # 条件边 - 从 supervisor 路由, 根据当前阶段决定下一个节点
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

    # 背景设定与剧情生成后都进入审查
    workflow.add_edge("world_builder", "critic")
    workflow.add_edge("story_driver", "critic")

    # 审查节点条件边：违规打回重写/重生成，通过返回 supervisor
    workflow.add_conditional_edges(
        "critic",
        critic_route,
        {
            "world_builder": "world_builder",
            "story_driver": "story_driver",
            "supervisor": "supervisor",
        }
    )
    # 审查通过后进入整合节点
    workflow.add_edge("integrator", "supervisor")

    return workflow


async def build_graph_async():
    """构建 LangGraph 图（异步版本，支持 SSE 流式输出）

    使用单一 SQLite 库 (novel.db) 作为 checkpointer。
    注意：AsyncSqliteSaver 需手动持有连接，使其在应用生命周期内保持存活。
    """
    import aiosqlite

    conn = await aiosqlite.connect(get_db_path())
    checkpointer = AsyncSqliteSaver(conn)

    workflow = _build_workflow()
    return workflow.compile(checkpointer=checkpointer)