"""数据库连接管理 - 单一 SQLite 库 (novel.db)

所有持久化存储（LangGraph checkpointer、会话元数据、长期记忆）共用同一个
SQLite 文件，集中管理路径与表初始化，避免多文件分散维护。
"""

import os
import sqlite3

# 单一数据库文件，位于项目根目录下
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "novel.db")


def get_db_path() -> str:
    """获取统一数据库文件路径"""
    return DB_PATH


def get_conn() -> sqlite3.Connection:
    """打开数据库连接（启用外键、行工厂为字典，统一在连接层设置）

    行工厂统一设为 sqlite3.Row，避免各存储模块重复设置；
    既支持字段名访问（row["col"]），也支持下标访问（row[0]）。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    _init_tables(conn)
    return conn


def _init_tables(conn: sqlite3.Connection) -> None:
    """初始化业务表结构（checkpointer 表由 LangGraph 自行管理，不在此创建）"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_metas (
            session_id TEXT PRIMARY KEY,
            title TEXT,
            current_phase TEXT,
            current_turn INTEGER,
            segment_count INTEGER,
            preview TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS long_term_memories (
            memory_id TEXT PRIMARY KEY,
            title TEXT,
            world_setting TEXT,
            characters TEXT,
            rules TEXT,
            story_segments TEXT,
            memory_state TEXT,
            final_output TEXT,
            created_at TEXT,
            completed_at TEXT
        )
        """
    )
    conn.commit()
