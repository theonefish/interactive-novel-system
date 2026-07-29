"""记忆管理器 - 为 Agent 提供故事记忆能力"""

from typing import TypedDict, List, Optional
from src.utils.llm import llm_call
from src.utils.config import TEMPERATURE_CRITIC


# ─── 记忆类型定义 ───────────────────────────────────


class CharacterMemory(TypedDict):
    name: str
    traits: List[str]            # 性格特征
    relationships: List[str]     # 关系描述
    arc: str                     # 当前成长弧线
    last_appearance: int         # 最后出现轮次


class PlotThread(TypedDict):
    description: str             # 线索描述
    status: str                  # active / resolved / abandoned
    created_turn: int
    last_mentioned: int


class Foreshadowing(TypedDict):
    description: str
    planted_turn: int
    status: str                  # pending / fulfilled


class MemoryState(TypedDict):
    characters: List[CharacterMemory]
    plot_threads: List[PlotThread]
    foreshadowing: List[Foreshadowing]
    timeline: List[str]          # 关键事件摘要
    world_notes: List[str]       # 世界观细节笔记


# ─── 记忆提取提示词 ─────────────────────────────────

MEMORY_EXTRACT_PROMPT = """你是一位故事分析师，负责从最新的剧情片段中提取记忆信息。

根据最新剧情片段，更新以下记忆内容：

【已有记忆】
角色档案：{characters}
剧情线索：{plot_threads}
伏笔：{foreshadowing}
时间线事件：{timeline}
世界观笔记：{world_notes}

【最新剧情片段】
{segment}

【用户输入】
{user_input}

请分析片段，输出 JSON 格式的记忆更新（只输出有变化的部分，没有变化就留空数组）：

{{
  "character_updates": [
    {{
      "name": "角色名",
      "traits": ["新增的性格特征"],
      "relationships": ["新增的关系描述"],
      "arc": "角色成长弧线变化"
    }}
  ],
  "new_plot_threads": [
    {{"description": "新线索描述", "status": "active"}}
  ],
  "resolved_threads": ["已解决线索的描述"],
  "new_foreshadowing": [
    {{"description": "伏笔描述", "status": "pending"}}
  ],
  "fulfilled_foreshadowing": ["已回收的伏笔描述"],
  "timeline_events": ["关键事件摘要"],
  "world_notes": ["新的世界观细节"]
}}"""


# ─── 记忆管理函数 ───────────────────────────────────


def build_memory_context(memory: MemoryState) -> str:
    """构建记忆摘要文本，用于注入 Agent 的 Prompt"""
    parts = []

    # 角色
    chars = memory.get("characters", [])
    if chars:
        char_lines = []
        for c in chars:
            traits = "、".join(c.get("traits", []))
            rels = "；".join(c.get("relationships", []))
            arc = c.get("arc", "")
            parts.append(f"【{c['name']}】性格：{traits}；关系：{rels}；弧线：{arc}")
        parts.append("")

    # 活跃线索
    threads = [t for t in memory.get("plot_threads", []) if t.get("status") == "active"]
    if threads:
        parts.append("【活跃剧情线索】")
        for t in threads:
            parts.append(f"  - {t['description']}")
        parts.append("")

    # 待回收伏笔
    pending = [f for f in memory.get("foreshadowing", []) if f.get("status") == "pending"]
    if pending:
        parts.append("【待回收伏笔】")
        for f in pending:
            parts.append(f"  - {f['description']}（埋于第 {f.get('planted_turn', '?')} 轮）")
        parts.append("")

    # 时间线
    timeline = memory.get("timeline", [])
    if timeline:
        parts.append("【时间线】")
        for i, event in enumerate(timeline[-5:], 1):  # 只展示最近 5 个
            parts.append(f"  {i}. {event}")
        parts.append("")

    return "\n".join(parts)


def extract_memory_updates(
    segment: str,
    user_input: str,
    current_memory: MemoryState,
    current_turn: int,
) -> MemoryState:
    """从新剧情片段中提取记忆更新"""
    if not segment:
        return current_memory

    # 构建当前记忆的文本表示
    chars = current_memory.get("characters", [])
    char_text = "\n".join(
        f"{c.get('name', '?')}: 性格={'、'.join(c.get('traits', []))}, "
        f"关系={'；'.join(c.get('relationships', []))}, 弧线={c.get('arc', '')}"
        for c in chars
    ) or "无"

    plot_text = "\n".join(
        f"{t['description']}（{t['status']}）"
        for t in current_memory.get("plot_threads", [])
    ) or "无"

    fore_text = "\n".join(
        f"{f['description']}（{f['status']}）"
        for f in current_memory.get("foreshadowing", [])
    ) or "无"

    timeline_text = "\n".join(current_memory.get("timeline", [])) or "无"
    notes_text = "\n".join(current_memory.get("world_notes", [])) or "无"

    prompt = MEMORY_EXTRACT_PROMPT.format(
        characters=char_text,
        plot_threads=plot_text,
        foreshadowing=fore_text,
        timeline=timeline_text,
        world_notes=notes_text,
        segment=segment,
        user_input=user_input,
    )

    response = llm_call(
        system_prompt=prompt,
        user_prompt="请分析并提取记忆更新。",
        temperature=TEMPERATURE_CRITIC,
        max_tokens=1024,
    )

    # 解析 JSON 更新
    updates = _parse_memory_json(response)

    # 合并到当前记忆
    new_memory = _apply_updates(current_memory, updates, current_turn)
    return new_memory


def _parse_memory_json(text: str) -> dict:
    """从 LLM 响应中提取 JSON"""
    import json
    import re

    # 尝试提取 JSON 块
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def _apply_updates(memory: MemoryState, updates: dict, turn: int) -> MemoryState:
    """将提取的更新合并到记忆状态"""
    new_memory = dict(memory)

    # 更新角色
    for cu in updates.get("character_updates", []):
        name = cu.get("name", "")
        found = False
        for c in new_memory.get("characters", []):
            if c.get("name") == name:
                found = True
                if cu.get("traits"):
                    c["traits"] = list(set(c.get("traits", []) + cu["traits"]))
                if cu.get("relationships"):
                    c["relationships"] = list(set(c.get("relationships", []) + cu["relationships"]))
                if cu.get("arc"):
                    c["arc"] = cu["arc"]
                c["last_appearance"] = turn
                break
        if not found:
            new_memory.setdefault("characters", []).append({
                "name": name,
                "traits": cu.get("traits", []),
                "relationships": cu.get("relationships", []),
                "arc": cu.get("arc", ""),
                "last_appearance": turn,
            })

    # 新增剧情线索
    for nt in updates.get("new_plot_threads", []):
        new_memory.setdefault("plot_threads", []).append({
            "description": nt.get("description", ""),
            "status": "active",
            "created_turn": turn,
            "last_mentioned": turn,
        })

    # 解决线索
    for desc in updates.get("resolved_threads", []):
        for t in new_memory.get("plot_threads", []):
            if t.get("description") == desc:
                t["status"] = "resolved"

    # 新增伏笔
    for nf in updates.get("new_foreshadowing", []):
        new_memory.setdefault("foreshadowing", []).append({
            "description": nf.get("description", ""),
            "planted_turn": turn,
            "status": "pending",
        })

    # 回收伏笔
    for desc in updates.get("fulfilled_foreshadowing", []):
        for f in new_memory.get("foreshadowing", []):
            if f.get("description") == desc:
                f["status"] = "fulfilled"

    # 时间线事件
    for event in updates.get("timeline_events", []):
        new_memory.setdefault("timeline", []).append(f"第{turn}轮：{event}")

    # 世界观笔记
    for note in updates.get("world_notes", []):
        if note not in new_memory.get("world_notes", []):
            new_memory.setdefault("world_notes", []).append(note)

    return new_memory


def create_initial_memory(characters: List[dict]) -> MemoryState:
    """根据 WorldBuilder 生成的初始设定创建初始记忆"""
    char_memories = []
    for c in characters:
        traits = []
        if c.get("personality"):
            traits = [t.strip() for t in c["personality"].split("、") if t.strip()]
        char_memories.append({
            "name": c.get("name", "主角"),
            "traits": traits,
            "relationships": [],
            "arc": "初登场",
            "last_appearance": 0,
        })

    return {
        "characters": char_memories,
        "plot_threads": [],
        "foreshadowing": [],
        "timeline": [],
        "world_notes": [],
    }