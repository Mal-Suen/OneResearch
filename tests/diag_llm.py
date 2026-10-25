# -*- coding: utf-8 -*-
"""诊断脚本（手动运行）：验证内部 LLM 通道连通性与耗时。python tests/diag_llm.py"""
import asyncio
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

from oneresearch.config import llm_configured, load_config, proxy_alive
from oneresearch.llm import LLMClient


async def main() -> None:
    cfg = load_config()
    llm = cfg["llm"]
    print(f"llm_configured={llm_configured(cfg)}")
    print(f"base_url={llm.get('base_url') or '—'}")
    print(f"model={llm.get('model') or '—'}")
    key = llm.get("api_key") or ""
    print(f"api_key={'已配置（' + str(len(key)) + ' 字符）' if key else '未配置'}")
    print(f"proxy_alive={proxy_alive(cfg['proxy'])}")

    if not llm_configured(cfg):
        return
    client = LLMClient(llm["base_url"], llm["api_key"], llm["model"])

    t0 = time.monotonic()
    try:
        queries = await asyncio.wait_for(
            client.gen_queries("FastMCP 2.0 与 mcp python SDK 的关系", 3), timeout=30)
        print(f"\n[gen_queries] OK {time.monotonic() - t0:.1f}s：{queries}")
    except Exception as e:
        print(f"\n[gen_queries] 失败 {time.monotonic() - t0:.1f}s："
              f"{type(e).__name__}: {str(e)[:300]}")

    material = ("[S1] FastMCP 官方文档（https://gofastmcp.com，2026-01-15）\n"
                "FastMCP 2.0 是 MCP Python SDK 的上层框架，提供组件化与部署能力。\n"
                "[S2] modelcontextprotocol python-sdk README（2026-02-01）\n"
                "官方 SDK 从 2.0 起将 FastMCP 实现并入官方维护。")
    t0 = time.monotonic()
    try:
        out = await asyncio.wait_for(
            client.synthesize("FastMCP 2.0 与 mcp python SDK 的关系", material), timeout=60)
        print(f"\n[synthesize] OK {time.monotonic() - t0:.1f}s，前 300 字：\n{out[:300]}")
    except Exception as e:
        print(f"\n[synthesize] 失败 {time.monotonic() - t0:.1f}s："
              f"{type(e).__name__}: {str(e)[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
