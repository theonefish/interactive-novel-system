"""长期记忆存储 - 基于单一 SQLite 库 (novel.db) 的同步存储

当一个会话创作完成（phase == done）时，将其世界观、角色、规则、前情段落、
记忆状态及正文持久化，以便后续「续写」时恢复上下文。使用标准库 sqlite3，
与 checkpointer / 会话元数据同库不同表。
"""

import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict

from src.utils.database import get_conn


def save_long_term_memory(session_id: str, state: Dict) -> None:
    """将已完成会话的完整状态持久化为一条长期记忆。

    session_id 作为记忆主键（memory_id），若已存在则覆盖（续写完成后刷新）。
    """
    now = datetime.utcnow().isoformat()

    record = {
        "memory_id": session_id,
        "title": state.get("user_request", "")[:50],
        "world_setting": state.get("world_setting", ""),
        "characters": json.dumps(state.get("characters", []), ensure_ascii=False),
        "rules": state.get("rules", ""),
        "story_segments": json.dumps(state.get("story_segments", []), ensure_ascii=False),
        "memory_state": json.dumps(state.get("memory", {}), ensure_ascii=False),
        "final_output": state.get("final_output", ""),
        "created_at": state.get("created_at", now),
        "completed_at": now,
    }
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO long_term_memories
            (memory_id, title, world_setting, characters, rules, story_segments, memory_state, final_output, created_at, completed_at)
            VALUES (:memory_id, :title, :world_setting, :characters, :rules, :story_segments, :memory_state, :final_output, :created_at, :completed_at)
            """,
            record,
        )


def get_long_term_memory(memory_id: str) -> Optional[Dict]:
    """按 memory_id 取单条长期记忆，反序列化 JSON 字段后返回；不存在返回 None。"""
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM long_term_memories WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["characters"] = json.loads(data.get("characters") or "[]")
        data["story_segments"] = json.loads(data.get("story_segments") or "[]")
        data["memory_state"] = json.loads(data.get("memory_state") or "{}")
        return data


def list_long_term_memories() -> List[Dict]:
    """列出所有长期记忆摘要（简化字段，便于列表展示）。

    preview 取自 final_output 前 80 字；若为空则取 story_segments 最后一段前 80 字。
    """
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT memory_id, title, final_output, story_segments, created_at, completed_at FROM long_term_memories ORDER BY completed_at DESC"
        ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            preview = (data.get("final_output") or "")[:80]
            if not preview:
                segs = json.loads(data.get("story_segments") or "[]")
                if segs:
                    preview = segs[-1][:80]
            result.append({
                "memory_id": data["memory_id"],
                "title": data.get("title", ""),
                "completed_at": data.get("completed_at", ""),
                "preview": preview,
            })
        return result
