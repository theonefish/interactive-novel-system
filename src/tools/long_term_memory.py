"""长期记忆存储 - 基于 SQLite 的同步存储

保存已完成创作的完整上下文（世界观、角色、规则、剧情片段、记忆状态、
最终成稿等），用于"续写已完成对话创作"功能。
使用标准库 sqlite3，与 session_store 保持同步语义。
"""

import json
import sqlite3
from datetime import datetime
from typing import Optional, List

from src.utils.database import get_long_term_memory_db_path


def _init_db(conn: sqlite3.Connection) -> None:
    """初始化表结构（如不存在则创建）"""
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


def save_long_term_memory(session_id: str, state: dict) -> None:
    """保存（或替换）一条长期记忆。

    从 state 字典提取字段，JSON 序列化 characters/story_segments/memory_state。
    使用 INSERT OR REPLACE，若 memory_id 已存在则保留原 created_at，
    completed_at 设为当前时间。
    """
    now = datetime.utcnow().isoformat()

    # 提取字段，title 优先取 title，回退到 user_request
    title = state.get("title") or state.get("user_request", "")
    characters = state.get("characters", [])
    story_segments = state.get("story_segments", [])
    memory_state = state.get("memory", {}) or {}

    with sqlite3.connect(get_long_term_memory_db_path()) as conn:
        _init_db(conn)
        existing = conn.execute(
            "SELECT created_at FROM long_term_memories WHERE memory_id = ?",
            (session_id,),
        ).fetchone()
        created_at = existing[0] if existing else now

        record = {
            "memory_id": session_id,
            "title": title,
            "world_setting": state.get("world_setting", ""),
            "characters": json.dumps(characters, ensure_ascii=False),
            "rules": state.get("rules", ""),
            "story_segments": json.dumps(story_segments, ensure_ascii=False),
            "memory_state": json.dumps(memory_state, ensure_ascii=False),
            "final_output": state.get("final_output", ""),
            "created_at": created_at,
            "completed_at": now,
        }
        conn.execute(
            """
            INSERT OR REPLACE INTO long_term_memories
            (memory_id, title, world_setting, characters, rules,
             story_segments, memory_state, final_output, created_at, completed_at)
            VALUES (:memory_id, :title, :world_setting, :characters, :rules,
                    :story_segments, :memory_state, :final_output,
                    :created_at, :completed_at)
            """,
            record,
        )
        conn.commit()


def get_long_term_memory(memory_id: str) -> Optional[dict]:
    """按 memory_id 获取单条长期记忆，不存在返回 None。

    返回字典中将 characters/story_segments/memory_state 反序列化为 Python 对象。
    """
    with sqlite3.connect(get_long_term_memory_db_path()) as conn:
        _init_db(conn)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM long_term_memories WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["characters"] = json.loads(data.get("characters") or "[]")
        data["story_segments"] = json.loads(data.get("story_segments") or "[]")
        data["memory_state"] = json.loads(data.get("memory_state") or "{}")
        return data


def list_long_term_memories() -> List[dict]:
    """获取所有长期记忆的简化列表，按 completed_at DESC 排序。

    每条包含 memory_id、title、completed_at、preview（取 final_output 或
    story_segments 最后一段的前 80 字）。
    """
    with sqlite3.connect(get_long_term_memory_db_path()) as conn:
        _init_db(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT memory_id, title, story_segments, final_output, completed_at "
            "FROM long_term_memories ORDER BY completed_at DESC"
        ).fetchall()

        result = []
        for row in rows:
            final_output = row["final_output"] or ""
            if final_output:
                preview = final_output[:80]
            else:
                try:
                    segments = json.loads(row["story_segments"] or "[]")
                except (json.JSONDecodeError, TypeError):
                    segments = []
                preview = (segments[-1] if segments else "")[:80]
            result.append({
                "memory_id": row["memory_id"],
                "title": row["title"],
                "completed_at": row["completed_at"],
                "preview": preview,
            })
        return result


def delete_long_term_memory(memory_id: str) -> None:
    """按 memory_id 删除一条长期记忆。"""
    with sqlite3.connect(get_long_term_memory_db_path()) as conn:
        _init_db(conn)
        conn.execute(
            "DELETE FROM long_term_memories WHERE memory_id = ?", (memory_id,)
        )
        conn.commit()
