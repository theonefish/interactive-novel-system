"""Bing 搜索工具 - 基于魔搭社区 bing-cn-mcp-enhanced MCP 服务（云端 streamable_http）

通过 streamable_http 连接云端 MCP，提供搜索与网页抓取两类能力。
配置在 .env 中的 mcp_bing_config 字段，JSON 格式（只需 type + url）：
    mcp_bing_config={"type": "streamable_http", "url": "https://..."}
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


# 统一加载 configs/.env（单一配置来源）
load_dotenv(Path(__file__).resolve().parent.parent.parent / "configs" / ".env")


def _load_mcp_config() -> dict:
    """从环境变量加载 MCP 配置"""
    raw = os.getenv("mcp_bing_config", "").strip()  # 读取并去掉首尾空白
    if not raw:  # 未配置则使用空字典
        return {}
    try:
        return json.loads(raw)  # 解析 JSON 字符串为字典
    except json.JSONDecodeError:  # 解析失败时回退为空字典
        return {}


MCP_CONFIG = _load_mcp_config()  # 全局 MCP 配置字典
MCP_BING_ENABLED = bool(MCP_CONFIG)  # 有配置即视为启用


def _run_async(coro):
    """在同步环境中运行异步协程（）"""
    try:
        loop = asyncio.get_event_loop()  # 获取当前事件循环
        if loop.is_running():  # 若已在运行中（如 LangGraph 节点内）
            import threading  # 用新线程避免 "loop already running"
            result = []  # 线程间传递返回值

            def run():  # 新线程中创建独立事件循环
                new_loop = asyncio.new_event_loop()
                result.append(new_loop.run_until_complete(coro))
                new_loop.close()

            t = threading.Thread(target=run)  # 启动子线程执行协程
            t.start()
            t.join()  # 等待子线程结束
            return result[0] if result else None  # 取回返回值
    except RuntimeError:  # 无可用事件循环时走下面兜底
        pass
    return asyncio.run(coro)  # 无运行中的循环，直接 run


async def _call_mcp_tool(tool_name: str, arguments: dict) -> Optional[str]:
    """通过 streamable_http 调用 MCP 工具（核心实现）"""
    url = MCP_CONFIG.get("url", "")
    if not url:
        print("[search_tool] MCP 配置缺少 url")
        return None

    try:
        async with streamable_http_client(url) as (read, write, *_):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return _extract_text(await session.call_tool(tool_name, arguments))
    except Exception as e:
        print(f"[search_tool] MCP 调用失败: {e}")
        return None

#
def _extract_text(result) -> Optional[str]:
    """从 MCP 返回结果中抽取文本内容"""
    if result and result.content:  # 结果存在且含 content 列表
        texts = []  # 收集各分段的文本
        for item in result.content:  # 遍历 content 中的每一项
            if hasattr(item, "text"):  # 对象形式：取 .text 属性
                texts.append(item.text)
            elif isinstance(item, dict) and "text" in item:  # 字典形式：取 "text" 键
                texts.append(item["text"])
        return "\n".join(texts) if texts else str(result)  # 拼接或直接转字符串
    return None  # 无内容可抽取


def search_bing(query: str) -> str:
    """调用 Bing 搜索，失败返回空字符串"""
    if not MCP_BING_ENABLED:  # 未启用时直接返回空，避免无谓连接
        return ""
    return _run_async(_call_mcp_tool("bing_search", {"query": query})) or ""


def search_for_world_building(user_request: str) -> str:
    """为世界观构建执行搜索（对外的统一入口）"""
    if not MCP_BING_ENABLED:  # 未启用时返回空，不影响后续流程
        return ""
    return search_bing(user_request)  # 复用搜索能力
