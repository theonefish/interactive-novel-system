"""LLM token 计量：让「省 token」这件事可以量化、可以对比。

每次 llm_call 都会调用 record_usage 记一条，汇总结果供 /api/usage 查看。
"""

import json
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "tokens.log"
_RECENT_LIMIT = 200

_lock = threading.Lock()
_totals = defaultdict(lambda: {"calls": 0, "input": 0, "output": 0,
                               "cached_input": 0, "reasoning": 0, "total": 0})
_recent = []


def extract_usage(response) -> dict:
    """从 LangChain 的 AIMessage 里取出 token 用量（不同供应商字段不同，缺失按 0 处理）。"""
    usage = {"input": 0, "output": 0, "total": 0, "cached_input": 0, "reasoning": 0}

    meta = getattr(response, "usage_metadata", None) or {}
    if isinstance(meta, dict):
        usage["input"] = int(meta.get("input_tokens") or 0)
        usage["output"] = int(meta.get("output_tokens") or 0)
        usage["total"] = int(meta.get("total_tokens") or (usage["input"] + usage["output"]))

    raw = (getattr(response, "response_metadata", None) or {}).get("token_usage") or {}
    if isinstance(raw, dict):
        usage["cached_input"] = int(raw.get("prompt_cache_hit_tokens") or 0)
        details = raw.get("completion_tokens_details") or {}
        usage["reasoning"] = int(details.get("reasoning_tokens") or 0)
        usage["input"] = usage["input"] or int(raw.get("prompt_tokens") or 0)
        usage["output"] = usage["output"] or int(raw.get("completion_tokens") or 0)

    usage["total"] = usage["total"] or (usage["input"] + usage["output"])
    return usage


def _append_log_line(line: str) -> None:
    """把一行用量写进 src/logs/tokens.log（写不了就算了，不影响主流程）。"""
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def record_usage(node: str, model: str, usage: dict) -> None:
    """记录一次调用的用量（内存汇总 + 明细日志）。"""
    node = node or "llm"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "node": node,
        "model": model or "",
        **usage,
    }
    with _lock:
        bucket = _totals[node]
        bucket["calls"] += 1
        for key in ("input", "output", "cached_input", "reasoning", "total"):
            bucket[key] += int(usage.get(key) or 0)
        _recent.append(record)
        del _recent[:-_RECENT_LIMIT]
    _append_log_line(json.dumps(record, ensure_ascii=False))


def summarize_usage() -> dict:
    """按节点汇总用量 + 最近调用明细。"""
    with _lock:
        totals = {node: dict(v) for node, v in _totals.items()}
        recent = list(_recent)
    overall = {"calls": 0, "input": 0, "output": 0, "cached_input": 0, "reasoning": 0, "total": 0}
    for bucket in totals.values():
        for key in overall:
            overall[key] += bucket[key]
    return {"overall": overall, "by_node": totals, "recent": recent[-50:]}


def reset_usage() -> None:
    """清空统计（测试与手动对账用）。"""
    with _lock:
        _totals.clear()
        _recent.clear()


def last_calls(limit: int = 20) -> list:
    """最近若干次调用明细（测试/排查用）。"""
    with _lock:
        return list(_recent[-limit:])
