"""Bing 搜索工具 - 基于魔搭社区 bing-cn-mcp-enhanced MCP 服务

支持两种连接方式：
- streamable_http: 魔搭社区云端部署（推荐）
- stdio: 本地 npx 运行

配置在 .env 中的 mcp_bing_config 字段，JSON 格式：
    mcp_bing_config={"type": "streamable_http", "url": "https://..."}
    或
    mcp_bing_config={"type": "stdio", "command": "npx", "args": ["bing-cn-mcp-enhanced"]}
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# 同时加载根目录 .env 和 configs/.env
load_dotenv()
load_dotenv(Path(__file__).resolve().parent.parent.parent / "configs" / ".env")


def _load_mcp_config() -> dict:
    """从环境变量加载 MCP 配置"""
    raw = os.getenv("mcp_bing_config", "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


MCP_CONFIG = _load_mcp_config()
MCP_BING_ENABLED = bool(MCP_CONFIG)


def _run_async(coro):
    """在同步环境中运行异步协程"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import threading
            result = []
            def run():
                new_loop = asyncio.new_event_loop()
                result.append(new_loop.run_until_complete(coro))
                new_loop.close()
            t = threading.Thread(target=run)
            t.start()
            t.join()
            return result[0] if result else None
    except RuntimeError:
        pass
    return asyncio.run(coro)


async def _call_mcp_tool_http(tool_name: str, arguments: dict) -> Optional[str]:
    """通过 streamable_http 调用 MCP 工具"""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    url = MCP_CONFIG.get("url", "")
    if not url:
        print("[search_tool] MCP 配置缺少 url")
        return None

    try:
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)

                if result and result.content:
                    texts = []
                    for item in result.content:
                        if hasattr(item, "text"):
                            texts.append(item.text)
                        elif isinstance(item, dict) and "text" in item:
                            texts.append(item["text"])
                    return "\n".join(texts) if texts else str(result)
                return None
    except Exception as e:
        print(f"[search_tool] MCP HTTP 调用失败: {e}")
        return None


async def _call_mcp_tool_stdio(tool_name: str, arguments: dict) -> Optional[str]:
    """通过 stdio 调用 MCP 工具"""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    command = MCP_CONFIG.get("command", "npx")
    args = MCP_CONFIG.get("args", ["bing-cn-mcp-enhanced"])

    server_params = StdioServerParameters(command=command, args=args)

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)

                if result and result.content:
                    texts = []
                    for item in result.content:
                        if hasattr(item, "text"):
                            texts.append(item.text)
                        elif isinstance(item, dict) and "text" in item:
                            texts.append(item["text"])
                    return "\n".join(texts) if texts else str(result)
                return None
    except Exception as e:
        print(f"[search_tool] MCP stdio 调用失败: {e}")
        return None


async def _call_mcp_tool(tool_name: str, arguments: dict) -> Optional[str]:
    """根据配置自动选择连接方式调用 MCP 工具"""
    conn_type = MCP_CONFIG.get("type", "streamable_http")
    if conn_type == "streamable_http":
        return await _call_mcp_tool_http(tool_name, arguments)
    else:
        return await _call_mcp_tool_stdio(tool_name, arguments)


def search_bing(query: str) -> str:
    """调用 Bing 搜索

    Args:
        query: 搜索关键词

    Returns:
        搜索结果文本，失败时返回空字符串
    """
    if not MCP_BING_ENABLED:
        return ""
    return _run_async(_call_mcp_tool("bing_search", {"query": query})) or ""


def fetch_webpage(url: str) -> str:
    """获取网页内容

    Args:
        url: 网页 URL

    Returns:
        网页文本内容，失败时返回空字符串
    """
    if not MCP_BING_ENABLED:
        return ""
    return _run_async(_call_mcp_tool("fetch_webpage", {"url": url})) or ""


def search_for_world_building(user_request: str) -> str:
    """为世界观构建执行搜索

    Args:
        user_request: 用户的创作需求

    Returns:
        搜索结果摘要文本，失败时返回空字符串
    """
    if not MCP_BING_ENABLED:
        return ""
    return search_bing(user_request)