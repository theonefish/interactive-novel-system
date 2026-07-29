"""工具模块测试 - 测试记忆管理、搜索工具、RAG 工具"""

import pytest
import json
from unittest.mock import patch, MagicMock

from src.tools.memory import (
    MemoryState,
    create_initial_memory,
    build_memory_context,
    extract_memory_updates,
    _parse_memory_json,
    _apply_updates,
)


# ─── 记忆管理测试 ───────────────────────────────────

class TestCreateInitialMemory:
    """测试 create_initial_memory"""

    def test_empty_characters_returns_empty_memory(self):
        memory = create_initial_memory([])
        assert memory["characters"] == []
        assert memory["plot_threads"] == []
        assert memory["foreshadowing"] == []
        assert memory["timeline"] == []
        assert memory["world_notes"] == []

    def test_creates_character_memories_from_list(self):
        characters = [
            {"name": "林远", "personality": "坚韧、冷静", "role": "主角"},
            {"name": "小雨", "personality": "好奇、勇敢", "role": "女儿"},
        ]
        memory = create_initial_memory(characters)

        assert len(memory["characters"]) == 2
        assert memory["characters"][0]["name"] == "林远"
        assert "坚韧" in memory["characters"][0]["traits"]
        assert "冷静" in memory["characters"][0]["traits"]
        assert memory["characters"][0]["arc"] == "初登场"
        assert memory["characters"][0]["last_appearance"] == 0

    def test_handles_character_without_personality(self):
        characters = [{"name": "神秘人", "role": "未知"}]
        memory = create_initial_memory(characters)

        assert len(memory["characters"]) == 1
        assert memory["characters"][0]["traits"] == []
        assert memory["characters"][0]["name"] == "神秘人"

    def test_handles_empty_character_list(self):
        memory = create_initial_memory([])
        assert memory["characters"] == []


class TestBuildMemoryContext:
    """测试 build_memory_context"""

    def test_empty_memory_returns_empty_string(self):
        memory = create_initial_memory([])
        context = build_memory_context(memory)
        assert context == ""

    def test_includes_character_info(self):
        memory = create_initial_memory([
            {"name": "林远", "personality": "坚韧、冷静", "role": "主角"},
        ])
        context = build_memory_context(memory)
        assert "林远" in context
        assert "坚韧" in context

    def test_includes_active_plot_threads(self):
        memory: MemoryState = {
            "characters": [],
            "plot_threads": [
                {"description": "寻找绿洲", "status": "active", "created_turn": 1, "last_mentioned": 1},
                {"description": "已解决线索", "status": "resolved", "created_turn": 1, "last_mentioned": 1},
            ],
            "foreshadowing": [],
            "timeline": [],
            "world_notes": [],
        }
        context = build_memory_context(memory)
        assert "寻找绿洲" in context
        assert "已解决线索" not in context

    def test_includes_pending_foreshadowing(self):
        memory: MemoryState = {
            "characters": [],
            "plot_threads": [],
            "foreshadowing": [
                {"description": "神秘钥匙", "planted_turn": 2, "status": "pending"},
                {"description": "已回收伏笔", "planted_turn": 1, "status": "fulfilled"},
            ],
            "timeline": [],
            "world_notes": [],
        }
        context = build_memory_context(memory)
        assert "神秘钥匙" in context
        assert "已回收伏笔" not in context

    def test_includes_timeline_last_5(self):
        memory: MemoryState = {
            "characters": [],
            "plot_threads": [],
            "foreshadowing": [],
            "timeline": ["事件1", "事件2", "事件3", "事件4", "事件5", "事件6"],
            "world_notes": [],
        }
        context = build_memory_context(memory)
        assert "事件6" in context
        assert "事件2" in context
        # 只展示最近5个
        assert "事件1" not in context


class TestParseMemoryJson:
    """测试 _parse_memory_json"""

    def test_valid_json(self):
        text = '一些说明 {"character_updates": [{"name": "张三"}]} 其他内容'
        result = _parse_memory_json(text)
        assert "character_updates" in result
        assert result["character_updates"][0]["name"] == "张三"

    def test_no_json_returns_empty(self):
        text = "这段话没有 JSON"
        result = _parse_memory_json(text)
        assert result == {}

    def test_invalid_json_returns_empty(self):
        text = '{"broken: json}'
        result = _parse_memory_json(text)
        assert result == {}


class TestApplyUpdates:
    """测试 _apply_updates"""

    def test_adds_new_character(self):
        memory = create_initial_memory([])
        updates = {
            "character_updates": [
                {"name": "新角色", "traits": ["神秘"], "relationships": [], "arc": "未知"}
            ]
        }
        new_memory = _apply_updates(memory, updates, turn=1)
        assert len(new_memory["characters"]) == 1
        assert new_memory["characters"][0]["name"] == "新角色"
        assert new_memory["characters"][0]["last_appearance"] == 1

    def test_updates_existing_character(self):
        memory = create_initial_memory([
            {"name": "林远", "personality": "坚韧", "role": "主角"},
        ])
        updates = {
            "character_updates": [
                {"name": "林远", "traits": ["果断"], "relationships": ["与小雨的关系加深"], "arc": "成长为领袖"}
            ]
        }
        new_memory = _apply_updates(memory, updates, turn=2)
        assert "果断" in new_memory["characters"][0]["traits"]
        assert "与小雨的关系加深" in new_memory["characters"][0]["relationships"]
        assert new_memory["characters"][0]["arc"] == "成长为领袖"
        assert new_memory["characters"][0]["last_appearance"] == 2

    def test_adds_new_plot_thread(self):
        memory = create_initial_memory([])
        updates = {
            "new_plot_threads": [
                {"description": "寻找水源", "status": "active"}
            ]
        }
        new_memory = _apply_updates(memory, updates, turn=1)
        assert len(new_memory["plot_threads"]) == 1
        assert new_memory["plot_threads"][0]["description"] == "寻找水源"
        assert new_memory["plot_threads"][0]["status"] == "active"

    def test_resolves_plot_thread(self):
        memory: MemoryState = {
            "characters": [],
            "plot_threads": [
                {"description": "寻找水源", "status": "active", "created_turn": 1, "last_mentioned": 1},
            ],
            "foreshadowing": [],
            "timeline": [],
            "world_notes": [],
        }
        updates = {"resolved_threads": ["寻找水源"]}
        new_memory = _apply_updates(memory, updates, turn=3)
        assert new_memory["plot_threads"][0]["status"] == "resolved"

    def test_adds_foreshadowing(self):
        memory = create_initial_memory([])
        updates = {
            "new_foreshadowing": [
                {"description": "神秘地图", "status": "pending"}
            ]
        }
        new_memory = _apply_updates(memory, updates, turn=2)
        assert len(new_memory["foreshadowing"]) == 1
        assert new_memory["foreshadowing"][0]["description"] == "神秘地图"
        assert new_memory["foreshadowing"][0]["planted_turn"] == 2

    def test_adds_timeline_events(self):
        memory = create_initial_memory([])
        updates = {"timeline_events": ["发现了避难所"]}
        new_memory = _apply_updates(memory, updates, turn=3)
        assert len(new_memory["timeline"]) == 1
        assert "第3轮：发现了避难所" in new_memory["timeline"][0]

    def test_adds_world_notes(self):
        memory = create_initial_memory([])
        updates = {"world_notes": ["这个世界有3个月亮"]}
        new_memory = _apply_updates(memory, updates, turn=1)
        assert "这个世界有3个月亮" in new_memory["world_notes"]

    def test_does_not_duplicate_world_notes(self):
        memory: MemoryState = {
            "characters": [],
            "plot_threads": [],
            "foreshadowing": [],
            "timeline": [],
            "world_notes": ["已有笔记"],
        }
        updates = {"world_notes": ["已有笔记", "新笔记"]}
        new_memory = _apply_updates(memory, updates, turn=1)
        assert len(new_memory["world_notes"]) == 2
        assert "已有笔记" in new_memory["world_notes"]
        assert "新笔记" in new_memory["world_notes"]


class TestExtractMemoryUpdates:
    """测试 extract_memory_updates"""

    @patch("src.tools.memory.llm_call")
    def test_calls_llm_and_applies_updates(self, mock_llm):
        mock_llm.return_value = '{"character_updates": [{"name": "新角色", "traits": ["神秘"], "relationships": [], "arc": "未知"}]}'

        memory = create_initial_memory([])
        result = extract_memory_updates(
            segment="新角色登场了。",
            user_input="继续",
            current_memory=memory,
            current_turn=1,
        )

        assert len(result["characters"]) == 1
        assert result["characters"][0]["name"] == "新角色"

    @patch("src.tools.memory.llm_call")
    def test_empty_segment_returns_original_memory(self, mock_llm):
        memory = create_initial_memory([])
        result = extract_memory_updates(
            segment="",
            user_input="",
            current_memory=memory,
            current_turn=1,
        )
        assert result == memory
        mock_llm.assert_not_called()


# ─── 搜索工具测试 ───────────────────────────────────

class TestSearchTool:
    """测试 search_tool 配置加载"""

    def test_mcp_config_loaded_from_env(self):
        from src.tools.search_tool import MCP_CONFIG, MCP_BING_ENABLED
        # 只要配置能加载，类型正确即可
        if MCP_BING_ENABLED:
            assert "type" in MCP_CONFIG
            assert "url" in MCP_CONFIG or "command" in MCP_CONFIG

    @patch("src.tools.search_tool.MCP_BING_ENABLED", False)
    def test_disabled_returns_empty_string(self):
        from src.tools.search_tool import search_bing, fetch_webpage
        assert search_bing("测试") == ""
        assert fetch_webpage("http://example.com") == ""


# ─── RAG 工具测试 ───────────────────────────────────

class TestRagTool:
    """测试 rag_tool"""

    @patch("src.tools.rag_tool._get_vector_store")
    def test_retrieve_returns_empty_on_connection_failure(self, mock_vs):
        from src.tools.rag_tool import retrieve
        mock_vs.side_effect = Exception("连接失败")
        result = retrieve("测试查询")
        assert result == ""

    @patch("src.tools.rag_tool._get_vector_store")
    @patch("src.tools.rag_tool.rerank_documents")
    def test_retrieve_returns_content_on_success(self, mock_rerank, mock_vs):
        from src.tools.rag_tool import retrieve

        mock_doc = MagicMock()
        mock_doc.page_content = "相关文档内容"
        mock_vs_instance = MagicMock()
        mock_vs_instance.similarity_search.return_value = [mock_doc]
        mock_vs.return_value = mock_vs_instance
        mock_rerank.return_value = [0]

        result = retrieve("测试查询")
        assert "相关文档内容" in result

    def test_retrieve_for_writing_with_empty_query_returns_empty(self):
        from src.tools.rag_tool import retrieve_for_writing
        result = retrieve_for_writing("", "", "", "")
        assert result == ""

    @patch("src.tools.rag_tool.retrieve", return_value="参考素材内容")
    def test_retrieve_for_writing_calls_retrieve(self, mock_retrieve):
        from src.tools.rag_tool import retrieve_for_writing
        result = retrieve_for_writing("世界观", "历史", "上下文", "用户输入")
        assert "参考素材内容" in result
        mock_retrieve.assert_called_once()


# ─── 文档工具测试 ───────────────────────────────────

class TestDocumentUtil:
    """测试 document_util"""

    def test_supported_formats(self):
        from src.tools.document_util import SUPPORTED_FORMATS
        assert ".txt" in SUPPORTED_FORMATS
        assert ".md" in SUPPORTED_FORMATS
        assert ".pdf" in SUPPORTED_FORMATS
        assert ".docx" in SUPPORTED_FORMATS
        assert ".csv" in SUPPORTED_FORMATS

    def test_unsupported_format_raises_error(self):
        from src.tools.document_util import _get_loader
        with pytest.raises(ValueError, match="不支持的文档格式"):
            _get_loader("test.xyz")

    def test_split_documents_returns_chunks(self):
        from src.tools.document_util import split_documents
        from langchain_core.documents import Document

        docs = [Document(page_content="这是第一段。这是第二段。这是第三段。")]
        chunks = split_documents(docs)
        assert len(chunks) >= 1
        assert all(hasattr(c, "page_content") for c in chunks)