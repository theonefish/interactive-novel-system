"""会话元数据存储 - 基于单一 SQLite 库 (novel.db) 的同步存储

提供会话进度摘要（标题、当前阶段、轮次、片段数、预览等）的增删改查。
使用标准库 sqlite3，与 checkpointer 同库不同表。
"""

import sqlite3
from datetime import datetime
from typing import Optional, List

from src.utils.database import get_conn


def save_session_meta(meta: dict) -> None:
    """保存（或替换）一条会话元数据。

    若 session_id 已存在则更新（保留 created_at），否则插入新记录。
    """
    now = datetime.utcnow().isoformat()
    session_id = meta["session_id"]

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT created_at FROM session_metas WHERE session_id = ?", (session_id,)
        ).fetchone()
        created_at = existing[0] if existing else meta.get("created_at", now)

        record = {
            "session_id": session_id,
            "title": meta.get("title", ""),
            "current_phase": meta.get("current_phase", ""),
            "current_turn": meta.get("current_turn", 0),
            "segment_count": meta.get("segment_count", 0),
            "preview": meta.get("preview", ""),
            "created_at": created_at,
            "updated_at": meta.get("updated_at", now),
        }
        conn.execute(
            """
            INSERT OR REPLACE INTO session_metas
            (session_id, title, current_phase, current_turn, segment_count, preview, created_at, updated_at)
            VALUES (:session_id, :title, :current_phase, :current_turn, :segment_count, :preview, :created_at, :updated_at)
            """,
            record,
        )


def get_session_meta(session_id: str) -> Optional[dict]:
    """按 session_id 获取单条会话元数据，不存在返回 None。"""
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM session_metas WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def list_session_metas() -> List[dict]:
    """获取所有会话元数据，按 updated_at DESC 排序。"""
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM session_metas ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def update_session_meta(session_id: str, updates: dict) -> None:
    """按 session_id 更新指定字段，并自动刷新 updated_at。"""
    now = datetime.utcnow().isoformat()
    updates_with_ts = {**updates, "updated_at": now}

    with get_conn() as conn:
        set_clauses = []
        values = []
        for key, value in updates_with_ts.items():
            set_clauses.append(f"{key} = ?")
            values.append(value)
        values.append(session_id)
        conn.execute(
            f"UPDATE session_metas SET {', '.join(set_clauses)} WHERE session_id = ?",
            values,
        )


def delete_session_meta(session_id: str) -> None:
    """按 session_id 删除一条会话元数据。"""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM session_metas WHERE session_id = ?", (session_id,)
        )
