"""LLM 输出 JSON 解析的回归测试（纯标准库，任何环境都能跑）。"""

from src.utils.json_parse import extract_json, parse_json_response


def test_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    text = '好的，结果如下：\n```json\n{"world_setting": "赛博朋克", "rules": "r"}\n```\n希望有帮助'
    assert extract_json(text)["world_setting"] == "赛博朋克"


def test_prose_with_unrelated_braces():
    text = '说明 {这不是JSON} 后面才是 {"a": {"b": 2}} 完'
    assert extract_json(text) == {"a": {"b": 2}}


def test_truncated_json_is_repaired():
    """max_tokens 截断的中途输出也要能救回来（这是「世界观确认消失」的根因之一）。"""
    text = '{"world_setting": "很长的一段设定", "characters": [{"name": "侦探"'
    data = extract_json(text)
    assert data.get("world_setting") == "很长的一段设定"
    assert data["characters"][0]["name"] == "侦探"


def test_truncation_inside_string_is_repaired():
    text = '{"world_setting": "被截断的设定内容'
    data = extract_json(text)
    assert data.get("world_setting") == "被截断的设定内容"


def test_garbage_and_empty_return_empty_dict():
    assert extract_json("完全不是 json") == {}
    assert extract_json("") == {}
    assert extract_json("{}") == {}


def test_parse_json_response_warns_on_failure():
    class _Logger:
        def __init__(self):
            self.msgs = []

        def warning(self, msg):
            self.msgs.append(msg)

    log = _Logger()
    assert parse_json_response("坏的输出", log) == {}
    assert log.msgs and "无法解析" in log.msgs[0]
