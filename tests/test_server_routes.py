"""回归测试：server.py 的重复定义与续写路由被遮蔽问题。

只做静态（AST/文本）检查，不导入后端依赖，因此在任何环境都能跑。
"""

import ast
import pathlib
from collections import Counter

SERVER = pathlib.Path(__file__).resolve().parent.parent / "server.py"

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _source() -> str:
    return SERVER.read_text(encoding="utf-8")


def _tree() -> ast.Module:
    return ast.parse(_source())


def _routes() -> list:
    routes = []
    for node in _tree().body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            func = dec.func if isinstance(dec, ast.Call) else dec
            if not (isinstance(func, ast.Attribute) and func.attr in HTTP_METHODS):
                continue
            path = None
            if isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Constant):
                path = dec.args[0].value
            routes.append((func.attr.upper(), path, node.name))
    return routes


def test_no_duplicate_top_level_definitions():
    """合并残留导致 lifespan/app/_build_initial_state/resume_session 各定义两次。"""
    tree = _tree()
    names = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    dupes = [name for name, count in Counter(names).items() if count > 1]
    assert dupes == [], f"重复的顶层定义: {dupes}"


def test_single_fastapi_app_and_lifespan():
    src = _source()
    assert src.count("app = FastAPI(") == 1
    assert src.count("async def lifespan(") == 1


def test_resume_route_registered_exactly_once():
    """同名路由注册两次时，先注册的空壳会遮蔽真实实现。"""
    resume = [r for r in _routes() if r[:2] == ("POST", "/api/sessions/{session_id}/resume")]
    assert len(resume) == 1, f"resume 路由注册了 {len(resume)} 次: {resume}"


def test_all_routes_are_unique():
    seen = Counter((method, path) for method, path, _ in _routes())
    dupes = [key for key, count in seen.items() if count > 1]
    assert dupes == [], f"重复路由: {dupes}"


def test_resume_handler_is_the_real_implementation():
    """续写接口必须是带完整实现的那个函数，而不是只剩 docstring 的空壳。"""
    src = _source()
    tree = ast.parse(src)
    handlers = [
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "resume_session"
    ]
    assert len(handlers) == 1
    body = ast.get_source_segment(src, handlers[0])
    assert "long_term_memory.get_long_term_memory" in body
    assert "uuid.uuid4()" in body


def test_review_kinds_declared():
    src = _source()
    assert 'REVIEW_KINDS = ("setting_confirm", "setting_review", "segment_review")' in src
