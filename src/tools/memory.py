"""
记忆管理器 - 为 Agent 提供故事记忆能力
记录剧情发展状态,人物的性格特点,关系,成长弧线,以及剧情线索和伏笔点
有效避免挖坑不填
"""

from typing import TypedDict, List


# ─── 记忆类型定义 ───────────────────────────────────
# 角色记忆
class CharacterMemory(TypedDict):
    name: str
    traits: List[str]            # 性格特征
    relationships: List[str]     # 关系描述
    arc: str                     # 当前成长弧线
    last_appearance: int         # 最后出现轮次

# 剧情线索
class PlotThread(TypedDict):
    description: str             # 线索描述
    status: str                  # active / resolved / abandoned
    created_turn: int
    last_mentioned: int

# 伏笔点
class Foreshadowing(TypedDict):
    description: str
    planted_turn: int
    status: str                  # pending / fulfilled

# 整体记忆状态
class MemoryState(TypedDict):
    characters: List[CharacterMemory]
    plot_threads: List[PlotThread]
    foreshadowing: List[Foreshadowing]
    timeline: List[str]          # 关键事件摘要
    world_notes: List[str]       # 世界观细节笔记


# ─── 记忆管理函数 ───────────────────────────────────
def build_memory_context(memory: MemoryState, current_turn: int = None) -> str:
    """构建记忆摘要文本，用于注入 Agent 的 Prompt

    当提供 current_turn 时，启用滑动窗口裁剪：
    - 角色：仅保留最近 5 轮内出现过的
    - 伏笔：仅保留最近 10 条待回收伏笔
    """
    MEMORY_WINDOW = 5
    MAX_FORES = 10

    parts = []

    # 角色（滑动窗口裁剪：仅保留最近 MEMORY_WINDOW 轮内有活动的角色）
    chars = memory.get("characters", [])
    if current_turn is not None:
        chars = [c for c in chars if c.get("last_appearance", 0) >= current_turn - MEMORY_WINDOW]
    if chars:
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

    # 待回收伏笔（仅保留最近 MAX_FORES 条）
    pending = [f for f in memory.get("foreshadowing", []) if f.get("status") == "pending"]
    pending = pending[-MAX_FORES:] if current_turn is not None else pending
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


def apply_updates(memory: MemoryState, updates: dict, turn: int) -> MemoryState:
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