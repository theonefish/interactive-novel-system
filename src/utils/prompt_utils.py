"""提示词瘦身工具：截断、角色列表格式化、历史段落选取。

一个功能一个函数，所有节点共用，避免各处自己写一套截断逻辑。
"""

from typing import List

ELLIPSIS = "…"


def truncate_text(text: str, limit: int) -> str:
    """按字符数截断文本（限长为 0 或负数时表示不截断）。"""
    if not text or not limit or limit <= 0:
        return text or ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + ELLIPSIS


def format_characters(characters: List[dict], limit: int = 0) -> str:
    """把角色列表格式化成一行一个角色，最多取前 limit 个。"""
    if not characters:
        return "无"
    picked = characters[:limit] if limit and limit > 0 else characters
    return "\n".join(
        f"{c.get('name', '?')}（{c.get('role', '')}）：{c.get('personality', '')}"
        for c in picked
    ) or "无"


def take_recent_segments(segments: List[str], limit: int) -> List[str]:
    """只取最近 limit 段历史（limit<=0 表示全取）。"""
    if not segments:
        return []
    if not limit or limit <= 0:
        return list(segments)
    return list(segments[-limit:])
