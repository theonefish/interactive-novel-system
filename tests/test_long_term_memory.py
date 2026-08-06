"""long_term_memory 单元测试 - 覆盖长期记忆增删改查与序列化"""

import time

import pytest
from src.tools import long_term_memory
from src.utils import database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """使用临时目录的数据库路径，避免污染真实数据库"""
    db_path = str(tmp_path / "test_novel.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)
    return db_path


# ─── save_long_term_memory 测试 ──────────────────

class TestSaveLongTermMemory:
    """测试 save_long_term_memory"""

    def test_save_new_memory(self, temp_db):
        state = {
            "user_request": "末日废土",
            "world_setting": "废土世界",
            "characters": [{"name": "主角", "role": "主角"}],
            "rules": "规则1",
            "story_segments": ["第一段", "第二段"],
            "memory": {"characters": [], "plot_threads": []},
            "final_output": "完整小说",
        }
        long_term_memory.save_long_term_memory("m1", state)
        result = long_term_memory.get_long_term_memory("m1")
        assert result is not None
        assert result["memory_id"] == "m1"
        assert result["title"] == "末日废土"
        assert result["world_setting"] == "废土世界"
        assert result["rules"] == "规则1"
        assert result["final_output"] == "完整小说"
        assert result["created_at"]
        assert result["completed_at"]

    def test_save_serializes_json_fields(self, temp_db):
        state = {
            "user_request": "测试",
            "characters": [{"name": "角色A"}, {"name": "角色B"}],
            "story_segments": ["s1", "s2", "s3"],
            "memory": {"plot_threads": [{"description": "线索"}]},
        }
        long_term_memory.save_long_term_memory("m2", state)
        result = long_term_memory.get_long_term_memory("m2")
        # characters 反序列化为 list
        assert isinstance(result["characters"], list)
        assert len(result["characters"]) == 2
        assert result["characters"][0]["name"] == "角色A"
        # story_segments 反序列化为 list
        assert isinstance(result["story_segments"], list)
        assert result["story_segments"] == ["s1", "s2", "s3"]
        # memory_state 反序列化为 dict
        assert isinstance(result["memory_state"], dict)
        assert result["memory_state"]["plot_threads"][0]["description"] == "线索"

    def test_save_preserves_created_at_on_resave(self, temp_db):
        long_term_memory.save_long_term_memory("m3", {"user_request": "原标题"})
        first = long_term_memory.get_long_term_memory("m3")
        # 等待一小段时间确保 completed_at 不同
        time.sleep(0.01)
        # 再次保存（不同内容），created_at 应保留
        long_term_memory.save_long_term_memory(
            "m3", {"user_request": "新标题", "final_output": "新成稿"}
        )
        second = long_term_memory.get_long_term_memory("m3")
        assert second["title"] == "新标题"
        assert second["final_output"] == "新成稿"
        assert second["created_at"] == first["created_at"]
        # completed_at 应被刷新
        assert second["completed_at"] >= first["completed_at"]

    def test_save_title_falls_back_to_user_request(self, temp_db):
        long_term_memory.save_long_term_memory(
            "m4", {"user_request": "来自请求的标题", "world_setting": "w"}
        )
        result = long_term_memory.get_long_term_memory("m4")
        assert result["title"] == "来自请求的标题"

    def test_save_with_empty_state_uses_defaults(self, temp_db):
        long_term_memory.save_long_term_memory("m5", {})
        result = long_term_memory.get_long_term_memory("m5")
        assert result["title"] == ""
        assert result["world_setting"] == ""
        assert result["characters"] == []
        assert result["story_segments"] == []
        assert result["memory_state"] == {}
        assert result["final_output"] == ""


# ─── get_long_term_memory 测试 ───────────────────

class TestGetLongTermMemory:
    """测试 get_long_term_memory"""

    def test_get_existing(self, temp_db):
        long_term_memory.save_long_term_memory(
            "g1", {"user_request": "T1", "world_setting": "W1"}
        )
        result = long_term_memory.get_long_term_memory("g1")
        assert result["memory_id"] == "g1"
        assert result["title"] == "T1"
        assert result["world_setting"] == "W1"

    def test_get_nonexistent_returns_none(self, temp_db):
        assert long_term_memory.get_long_term_memory("nonexistent") is None


# ─── list_long_term_memories 测试 ─────────────────

class TestListLongTermMemories:
    """测试 list_long_term_memories"""

    def test_empty_list(self, temp_db):
        assert long_term_memory.list_long_term_memories() == []

    def test_list_returns_multiple_memories(self, temp_db):
        long_term_memory.save_long_term_memory("a", {"user_request": "A"})
        long_term_memory.save_long_term_memory("b", {"user_request": "B"})
        long_term_memory.save_long_term_memory("c", {"user_request": "C"})
        result = long_term_memory.list_long_term_memories()
        assert len(result) == 3
        assert {r["memory_id"] for r in result} == {"a", "b", "c"}

    def test_list_sorted_by_completed_at_desc(self, temp_db):
        long_term_memory.save_long_term_memory("old", {"user_request": "旧"})
        time.sleep(0.01)
        long_term_memory.save_long_term_memory("mid", {"user_request": "中"})
        time.sleep(0.01)
        long_term_memory.save_long_term_memory("new", {"user_request": "新"})
        result = long_term_memory.list_long_term_memories()
        # 最新完成的排首位
        assert result[0]["memory_id"] == "new"
        assert result[1]["memory_id"] == "mid"
        assert result[2]["memory_id"] == "old"

    def test_list_preview_from_final_output(self, temp_db):
        long_text = "这是最终成稿的很长的一段文本" * 10
        long_term_memory.save_long_term_memory(
            "p1", {"user_request": "P1", "final_output": long_text}
        )
        result = long_term_memory.list_long_term_memories()
        assert len(result) == 1
        # preview 取 final_output 前 80 字
        assert result[0]["preview"] == long_text[:80]

    def test_list_preview_falls_back_to_last_segment(self, temp_db):
        long_term_memory.save_long_term_memory(
            "p2",
            {
                "user_request": "P2",
                "final_output": "",
                "story_segments": ["段一", "段二这段比较长需要截断" * 5],
            },
        )
        result = long_term_memory.list_long_term_memories()
        assert len(result) == 1
        # preview 取 story_segments 最后一段前 80 字
        expected = ("段二这段比较长需要截断" * 5)[:80]
        assert result[0]["preview"] == expected

    def test_list_preview_empty_when_no_content(self, temp_db):
        long_term_memory.save_long_term_memory("p3", {"user_request": "P3"})
        result = long_term_memory.list_long_term_memories()
        assert result[0]["preview"] == ""

    def test_list_item_contains_simplified_fields(self, temp_db):
        long_term_memory.save_long_term_memory(
            "p4",
            {
                "user_request": "标题",
                "world_setting": "不应出现在列表",
                "characters": [{"name": "不应出现"}],
            },
        )
        result = long_term_memory.list_long_term_memories()
        item = result[0]
        # 列表项仅含简化字段
        assert set(item.keys()) == {"memory_id", "title", "completed_at", "preview"}
        assert item["title"] == "标题"


# ─── delete_long_term_memory 测试 ─────────────────

class TestDeleteLongTermMemory:
    """测试 delete_long_term_memory"""

    def test_delete_existing(self, temp_db):
        long_term_memory.save_long_term_memory("d1", {"user_request": "T"})
        assert long_term_memory.get_long_term_memory("d1") is not None
        long_term_memory.delete_long_term_memory("d1")
        assert long_term_memory.get_long_term_memory("d1") is None

    def test_delete_nonexistent_does_not_error(self, temp_db):
        long_term_memory.delete_long_term_memory("nonexistent")
        assert long_term_memory.list_long_term_memories() == []

    def test_delete_does_not_affect_others(self, temp_db):
        long_term_memory.save_long_term_memory("d2", {"user_request": "T2"})
        long_term_memory.save_long_term_memory("d3", {"user_request": "T3"})
        long_term_memory.delete_long_term_memory("d2")
        remaining = long_term_memory.list_long_term_memories()
        assert len(remaining) == 1
        assert remaining[0]["memory_id"] == "d3"


# ─── JSON 序列化/反序列化往返测试 ─────────────────

class TestJsonRoundTrip:
    """测试 JSON 序列化/反序列化的往返一致性"""

    def test_roundtrip_complex_characters(self, temp_db):
        characters = [
            {"name": "主角", "role": "主角", "personality": "勇敢、机智"},
            {"name": "反派", "role": "反派", "personality": "阴险"},
        ]
        long_term_memory.save_long_term_memory(
            "rt1", {"user_request": "rt", "characters": characters}
        )
        result = long_term_memory.get_long_term_memory("rt1")
        assert result["characters"] == characters

    def test_roundtrip_memory_state(self, temp_db):
        memory_state = {
            "characters": [{"name": "A", "traits": ["勇敢"]}],
            "plot_threads": [{"description": "线索", "status": "active"}],
            "foreshadowing": [{"description": "伏笔", "status": "pending"}],
            "timeline": ["事件1"],
            "world_notes": ["笔记1"],
        }
        long_term_memory.save_long_term_memory(
            "rt2", {"user_request": "rt", "memory": memory_state}
        )
        result = long_term_memory.get_long_term_memory("rt2")
        assert result["memory_state"] == memory_state

    def test_roundtrip_empty_collections(self, temp_db):
        long_term_memory.save_long_term_memory(
            "rt3",
            {"user_request": "rt", "characters": [], "story_segments": [], "memory": {}},
        )
        result = long_term_memory.get_long_term_memory("rt3")
        assert result["characters"] == []
        assert result["story_segments"] == []
        assert result["memory_state"] == {}
