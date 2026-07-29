"""数据库连接管理 - 支持 PostgreSQL 和 SQLite 切换"""

import os
import sqlite3
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# 环境变量
DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_checkpointer():
    """获取 checkpointer 实例，根据环境变量自动切换

    - 如果设置了 DATABASE_URL，使用 PostgresSaver
    - 否则使用 SqliteSaver（开发环境 fallback）
    """
    if DATABASE_URL:
        return _get_postgres_checkpointer()
    return _get_sqlite_checkpointer()


def _get_sqlite_checkpointer():
    """创建 SQLite checkpointer"""
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect("novel_sessions.db", check_same_thread=False)
    return SqliteSaver(conn)


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


def is_postgres() -> bool:
    """判断是否使用 PostgreSQL"""
    return bool(DATABASE_URL)