"""省 token 相关工具的回归测试（纯标准库，任何环境都能跑）。"""

from src.utils.prompt_utils import format_characters, take_recent_segments, truncate_text
from src.utils.ttl_cache import TTLCache
from src.utils.usage import (extract_usage, last_calls, normalize_usage, record_usage,
                             reset_usage, summarize_usage)
from src.prompts.writer_prompt import STORY_DRIVER_PROMPT
from src.prompts.reviewer_prompt import CRITIC_PROMPT


# ─── 提示词瘦身 ────────────────────────────────────────────────

def test_truncate_text():
    assert truncate_text("abcdef", 3) == "abc…"
    assert truncate_text("abc", 10) == "abc"
    assert truncate_text("abc", 0) == "abc"
    assert truncate_text("", 5) == ""


def test_format_characters_limits_count():
    chars = [{"name": f"角色{i}", "role": "配角", "personality": "性格"} for i in range(10)]
    text = format_characters(chars, 3)
    assert text.count("\n") == 2
    assert "角色0" in text and "角色2" in text and "角色3" not in text
    assert format_characters([], 3) == "无"


def test_take_recent_segments():
    assert take_recent_segments(["a", "b", "c"], 2) == ["b", "c"]
    assert take_recent_segments(["a"], 5) == ["a"]
    assert take_recent_segments([], 2) == []


def test_prompts_put_fixed_part_first_for_prefix_cache():
    """固定说明要在变量之前 → 平台前缀缓存才能命中更长前缀。"""
    assert STORY_DRIVER_PROMPT.index("输出 JSON") < STORY_DRIVER_PROMPT.index("{world_setting}")
    assert CRITIC_PROMPT.index("输出 JSON") < CRITIC_PROMPT.index("{world_setting}")
    # 逐轮变化的阈值放最后，避免打断可缓存前缀
    assert CRITIC_PROMPT.rstrip().endswith("{pass_threshold}分")
    # 段落长度写成硬上限，抑制超长输出
    assert "不要超过" in STORY_DRIVER_PROMPT


# ─── TTL 缓存 ──────────────────────────────────────────────────

def test_ttl_cache_basic():
    cache = TTLCache(ttl=60)
    assert cache.get("k") is None
    cache.set("k", "v")
    assert cache.get("k") == "v"
    cache.clear()
    assert cache.get("k") is None


def test_ttl_cache_expires():
    cache = TTLCache(ttl=0)   # 立刻过期
    cache.set("k", "v")
    assert cache.get("k") is None


def test_ttl_cache_evicts_when_full():
    cache = TTLCache(ttl=60, maxsize=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("c") == 3
    assert cache.get("a") is None   # 最早写入的被淘汰


# ─── token 计量 ────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, usage_metadata=None, response_metadata=None):
        self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata


def test_extract_usage_prefers_langchain_metadata():
    resp = _FakeResponse(
        usage_metadata={"input_tokens": 100, "output_tokens": 40, "total_tokens": 140,
                        "input_token_details": {"cache_read": 64},
                        "output_token_details": {"reasoning": 12}},
    )
    usage = extract_usage(resp)
    assert usage["input"] == 100 and usage["output"] == 40 and usage["total"] == 140
    assert usage["cached_input"] == 64 and usage["reasoning"] == 12


def test_normalize_usage_reads_cache_and_reasoning_details():
    """缓存命中/推理 token 的正确来源是 input/output_token_details（以前读错字段，永远是 0）。"""
    usage = normalize_usage({"input_tokens": 900, "output_tokens": 300, "total_tokens": 1200,
                             "input_token_details": {"cache_read": 768},
                             "output_token_details": {"reasoning": 128}})
    assert (usage["input"], usage["output"], usage["cached_input"], usage["reasoning"]) == (900, 300, 768, 128)


def test_normalize_usage_falls_back_to_raw_provider_fields():
    usage = normalize_usage(None, {"prompt_tokens": 30, "completion_tokens": 10,
                                   "prompt_cache_hit_tokens": 16,
                                   "completion_tokens_details": {"reasoning_tokens": 4}})
    assert (usage["input"], usage["output"], usage["total"]) == (30, 10, 40)
    assert usage["cached_input"] == 16 and usage["reasoning"] == 4


def test_extract_usage_falls_back_to_raw_fields():
    resp = _FakeResponse(response_metadata={"token_usage": {"prompt_tokens": 30, "completion_tokens": 10}})
    usage = extract_usage(resp)
    assert usage["input"] == 30 and usage["output"] == 10 and usage["total"] == 40


def test_extract_usage_handles_missing_fields():
    assert extract_usage(_FakeResponse())["total"] == 0


def test_record_and_summarize_usage():
    reset_usage()
    record_usage("critic", "m1", {"input": 10, "output": 5, "total": 15, "cached_input": 4, "reasoning": 1})
    record_usage("critic", "m1", {"input": 20, "output": 6, "total": 26, "cached_input": 0, "reasoning": 2})
    record_usage("story_driver", "m1", {"input": 30, "output": 40, "total": 70})

    summary = summarize_usage()
    assert summary["by_node"]["critic"]["calls"] == 2
    assert summary["by_node"]["critic"]["total"] == 41
    assert summary["overall"]["calls"] == 3
    assert summary["overall"]["total"] == 111
    assert len(last_calls()) == 3
    reset_usage()
    assert summarize_usage()["overall"]["calls"] == 0

