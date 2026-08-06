"""session_store 单元测试 - 覆盖会话元数据增删改查"""

import pytest
from src.utils import session_store, database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """使用临时目录的数据库路径，避免污染真实数据库"""
    db_path = str(tmp_path / "test_novel.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)
    return db_path


# ─── save_session_meta 测试 ───────────────────────

class TestSaveSessionMeta:
    """测试 save_session_meta"""

    def test_save_new_session(self, temp_db):
        meta = {
            "session_id": "s1",
            "title": "末日废土",
            "current_phase": "story_progressing",
            "current_turn": 1,
            "segment_count": 0,
            "preview": "片段预览",
        }
        session_store.save_session_meta(meta)
        result = session_store.get_session_meta("s1")
        assert result is not None
        assert result["session_id"] == "s1"
        assert result["title"] == "末日废土"
        assert result["current_phase"] == "story_progressing"
        assert result["current_turn"] == 1
        assert result["segment_count"] == 0
        assert result["preview"] == "片段预览"
        assert result["created_at"]  # 自动填充
        assert result["updated_at"]  # 自动填充

    def test_save_with_defaults_for_missing_fields(self, temp_db):
        session_store.save_session_meta({"session_id": "s2"})
        result = session_store.get_session_meta("s2")
        assert result["title"] == ""
        assert result["current_phase"] == ""
        assert result["current_turn"] == 0
        assert result["segment_count"] == 0
        assert result["preview"] == ""

    def test_save_preserves_created_at_on_resave(self, temp_db):
        session_store.save_session_meta({
            "session_id": "s3",
            "title": "初始标题",
        })
        first = session_store.get_session_meta("s3")
        # 再次保存（不同内容），created_at 应保留
        session_store.save_session_meta({
            "session_id": "s3",
            "title": "更新标题",
            "current_turn": 3,
        })
        second = session_store.get_session_meta("s3")
        assert second["title"] == "更新标题"
        assert second["current_turn"] == 3
        assert second["created_at"] == first["created_at"]


# ─── get_session_meta 测试 ───────────────────────

class TestGetSessionMeta:
    """测试 get_session_meta"""

    def test_get_existing(self, temp_db):
        session_store.save_session_meta({"session_id": "g1", "title": "T1"})
        result = session_store.get_session_meta("g1")
        assert result["session_id"] == "g1"
        assert result["title"] == "T1"

    def test_get_nonexistent_returns_none(self, temp_db):
        assert session_store.get_session_meta("nonexistent") is None


# ─── list_session_metas 测试 ──────────────────────

class TestListSessionMetas:
    """测试 list_session_metas"""

    def test_empty_list(self, temp_db):
        assert session_store.list_session_metas() == []

    def test_list_returns_all_sessions(self, temp_db):
        session_store.save_session_meta({"session_id": "a", "title": "A"})
        session_store.save_session_meta({"session_id": "b", "title": "B"})
        session_store.save_session_meta({"session_id": "c", "title": "C"})
        result = session_store.list_session_metas()
        assert len(result) == 3
        assert {r["session_id"] for r in result} == {"a", "b", "c"}

    def test_list_sorted_by_updated_at_desc(self, temp_db):
        session_store.save_session_meta({"session_id": "a", "title": "A"})
        session_store.save_session_meta({"session_id": "b", "title": "B"})
        # 更新 a，使其 updated_at 最新
        session_store.update_session_meta("a", {"title": "A2"})
        result = session_store.list_session_metas()
        assert result[0]["session_id"] == "a"  # a 最新更新，排首位
        assert result[0]["title"] == "A2"


# ─── update_session_meta 测试 ─────────────────────

class TestUpdateSessionMeta:
    """测试 update_session_meta"""

    def test_update_fields(self, temp_db):
        session_store.save_session_meta({"session_id": "u1", "title": "T", "current_turn": 0})
        session_store.update_session_meta("u1", {"current_turn": 5, "preview": "新预览"})
        result = session_store.get_session_meta("u1")
        assert result["current_turn"] == 5
        assert result["preview"] == "新预览"
        assert result["title"] == "T"  # 未更新字段保留

    def test_update_refreshes_updated_at(self, temp_db):
        session_store.save_session_meta({"session_id": "u2", "title": "T"})
        first = session_store.get_session_meta("u2")
        session_store.update_session_meta("u2", {"title": "T2"})
        second = session_store.get_session_meta("u2")
        assert second["updated_at"] >= first["updated_at"]
        assert second["created_at"] == first["created_at"]
        assert second["title"] == "T2"

    def test_update_nonexistent_does_not_error(self, temp_db):
        # 对不存在的会话更新不报错（影响 0 行）
        session_store.update_session_meta("nonexistent", {"title": "X"})
        assert session_store.get_session_meta("nonexistent") is None


# ─── delete_session_meta 测试 ─────────────────────

class TestDeleteSessionMeta:
    """测试 delete_session_meta"""

    def test_delete_existing(self, temp_db):
        session_store.save_session_meta({"session_id": "d1", "title": "T"})
        assert session_store.get_session_meta("d1") is not None
        session_store.delete_session_meta("d1")
        assert session_store.get_session_meta("d1") is None

    def test_delete_nonexistent_does_not_error(self, temp_db):
        session_store.delete_session_meta("nonexistent")
        assert session_store.list_session_metas() == []

    def test_delete_does_not_affect_others(self, temp_db):
        session_store.save_session_meta({"session_id": "d2", "title": "T2"})
        session_store.save_session_meta({"session_id": "d3", "title": "T3"})
        session_store.delete_session_meta("d2")
        remaining = session_store.list_session_metas()
        assert len(remaining) == 1
        assert remaining[0]["session_id"] == "d3"
