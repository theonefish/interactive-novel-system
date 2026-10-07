"""LLM 输出的 JSON 抽取工具

模型经常把 JSON 包在 ```json 代码块里、前后带解释文字，或者因为 max_tokens
被中途截断。原来各节点都用贪婪正则 ``re.search(r"\\{.*\\}")`` 抓取，
遇到代码围栏/截断/多段输出就会解析失败并**静默返回空 dict**，
最典型的表现是：世界观构建失败 → world_setting 为空 → 直接跳过「世界观确认」进入剧情。

这里按「整段解析 → 去代码围栏 → 平衡括号扫描 → 截断补齐」逐级降级，
全部失败才返回 {}，并把原始输出写进日志，方便排查。
"""

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _close_truncated(chunk: str) -> str:
    """把被 max_tokens 截断的 JSON 补成可解析的形态（补引号 / 补括号 / 去尾逗号）。"""
    out = []
    stack = []
    in_str = False
    escaped = False

    for ch in chunk:
        out.append(ch)
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()

    if in_str:
        out.append('"')
    while out and out[-1] in ", \t\r\n":
        out.pop()
    out.extend(reversed(stack))
    return "".join(out)


def _loads(chunk: str):
    """尝试解析；失败则尝试补齐截断后再解析。"""
    for candidate in (chunk, _close_truncated(chunk)):
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict) and obj:
            return obj
    return None


def _candidates(text: str):
    """按可靠性从高到低产出候选片段（最多 12 个，避免病态输入反复扫描）。"""
    stripped = text.strip()
    if not stripped:
        return

    fenced = _FENCE_RE.search(stripped)
    if fenced and fenced.group(1).strip():
        yield fenced.group(1).strip()

    yield stripped

    produced = 0
    start = stripped.find("{")
    while start != -1 and produced < 12:
        depth = 0
        in_str = False
        escaped = False
        for i in range(start, len(stripped)):
            ch = stripped[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield stripped[start:i + 1]
                    produced += 1
                    break
        start = stripped.find("{", start + 1)


def extract_json(text: str) -> dict:
    """从模型输出里抽出第一个可解析的 JSON 对象，失败返回 {}。"""
    if not text:
        return {}
    for candidate in _candidates(str(text)):
        obj = _loads(candidate)
        if obj is not None:
            return obj
    return {}


def parse_json_response(text: str, logger=None, raw_limit: int = 600) -> dict:
    """extract_json + 失败告警：解析不出来时把原始输出写进日志。"""
    data = extract_json(text)
    if not data and logger is not None:
        preview = " ".join((text or "").split())[:raw_limit]
        logger.warning(f"LLM 输出无法解析为 JSON（前 {raw_limit} 字）：{preview!r}")
    return data
