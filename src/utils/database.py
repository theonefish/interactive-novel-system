"""数据库连接管理 - 支持 PostgreSQL 和 SQLite 切换"""

import os

from dotenv import load_dotenv

load_dotenv()

# 环境变量
DATABASE_URL = os.getenv("DATABASE_URL", "")


def _get_postgres_checkpointer():
    """创建 PostgreSQL checkpointer"""
    from langgraph.checkpoint.postgres import PostgresSaver

    checkpointer = PostgresSaver.from_conn_string(DATABASE_URL)
    return checkpointer


async def setup_postgres():
    """初始化 PostgreSQL 数据库表（首次使用时调用）"""
    if not DATABASE_URL:
        return

    from langgraph.checkpoint.postgres import PostgresSaver

    checkpointer = PostgresSaver.from_conn_string(DATABASE_URL)
    await checkpointer.setup()
    return checkpointer


def get_database_url() -> str:
    """获取当前数据库 URL"""
    return DATABASE_URL or "sqlite:///novel_sessions.db"


def get_session_db_path() -> str:
    """获取会话元数据存储的 SQLite 路径（与 checkpointer 数据库同目录，独立文件）"""
    checkpointer_db = "novel_sessions.db"
    db_dir = os.path.dirname(os.path.abspath(checkpointer_db))
    return os.path.join(db_dir, "novel_sessions_meta.db")


def get_long_term_memory_db_path() -> str:
    """获取长期记忆存储的 SQLite 路径（与会话元数据库同目录，独立文件）"""
    checkpointer_db = "novel_sessions.db"
    db_dir = os.path.dirname(os.path.abspath(checkpointer_db))
    return os.path.join(db_dir, "novel_long_term_memories.db")


def is_postgres() -> bool:
    """判断是否使用 PostgreSQL"""
    return bool(DATABASE_URL)