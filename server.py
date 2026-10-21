# -*- coding: utf-8 -*-
"""OneResearch（一次调研）MCP 服务器：把联网调研的多轮「搜索→阅读」循环折叠为一次工具调用。"""
from mcp.server.fastmcp import FastMCP

from oneresearch.pipeline import run_fetch_digest, run_research

mcp = FastMCP("OneResearch")


@mcp.tool()
async def research(question: str, depth: str = "standard", focus: str = "",
                   recency: str = "", max_sources: int = 8) -> str:
    """一次性完成联网调研：内部自动双引擎搜索（DuckDuckGo＋Bing）、并发抓取网页、提取正文、
    按相关性排序浓缩，返回一份可直接用于作答的调研报告（含各来源要点摘录、来源清单、覆盖缺口）。

    做任何联网调研／技术选型／方案对比／查资料时，优先调用本工具一次完成，
    不要自己反复 web_search＋逐页阅读（那样会消耗大量请求轮次）。

    Args:
        question: 调研问题（中英文均可，尽量具体）
        depth: quick（1 组查询，约 30 秒）／standard（默认，2 组查询，约 50 秒）／deep（更多查询与来源，约 80 秒）
        focus: 可选，聚焦方向关键词（并入查询与排序权重）
        recency: 可选时效要求：month（近一月加权）／year（近一年加权）／留空不限制
        max_sources: 报告最多纳入的来源数（默认 8，上限 12）
    """
    return await run_research(question, depth=depth, focus=focus, recency=recency,
                              max_sources=max_sources)


@mcp.tool()
async def fetch_digest(urls: list[str], question: str = "") -> str:
    """批量抓取指定网页并返回浓缩摘要：一次调用读回多个页面（自动提取正文，按 question 相关性排序段落）。
    已经知道要读哪些页面时用这个工具，不要逐个 fetch（省请求轮次）。

    Args:
        urls: 要读取的网页 URL 列表（最多 10 个）
        question: 可选，用于段落相关性排序的问题
    """
    return await run_fetch_digest(urls, question=question)


if __name__ == "__main__":
    mcp.run()
