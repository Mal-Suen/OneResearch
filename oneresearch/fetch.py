# -*- coding: utf-8 -*-
"""并发网页抓取：单页超时＋体积上限＋整体 deadline，到点返回已完成部分。"""
import asyncio
import re
import time
from dataclasses import dataclass

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

NON_TEXT = ("image/", "video/", "audio/", "application/pdf", "application/zip",
            "application/octet-stream")


@dataclass
class PageFetch:
    url: str
    status: int = 0
    html: str = ""
    error: str = ""
    elapsed: float = 0.0
    final_url: str = ""


def decode_body(body: bytes, content_type: str) -> str:
    """按 content-type charset／meta charset／utf-8／gb18030 顺序解码页面。"""
    enc = ""
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    if m:
        enc = m.group(1)
    if not enc:
        head = body[:2048].decode("ascii", "replace")
        m = re.search(r'charset=["\']?([\w\-]+)', head, re.I)
        if m:
            enc = m.group(1)
    for candidate in (enc, "utf-8", "gb18030"):
        if not candidate:
            continue
        try:
            return body.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", "replace")


async def _fetch_one(client: httpx.AsyncClient, url: str, max_bytes: int) -> PageFetch:
    t0 = time.monotonic()
    try:
        async with client.stream("GET", url) as r:
            ctype = (r.headers.get("content-type") or "").lower()
            if any(x in ctype for x in NON_TEXT):
                return PageFetch(url, r.status_code, error="非文本内容")
            if r.status_code != 200:
                return PageFetch(url, r.status_code, error=f"HTTP {r.status_code}")
            chunks, total = [], 0
            async for chunk in r.aiter_bytes(65536):
                chunks.append(chunk)
                total += len(chunk)
                if total >= max_bytes:
                    break
            html = decode_body(b"".join(chunks), ctype)
            return PageFetch(url, 200, html=html, elapsed=time.monotonic() - t0,
                             final_url=str(r.url))
    except Exception as e:
        return PageFetch(url, error=f"{type(e).__name__}: {str(e)[:80]}")


async def fetch_pages(urls: list[str], proxy: str | None, max_concurrent: int = 6,
                      per_page_timeout: float = 12, max_bytes: int = 2000000,
                      deadline: float = 45.0) -> list[PageFetch]:
    """并发抓取一批 URL；deadline 到点取消未完成任务，返回已完成部分。"""
    if not urls:
        return []
    sem = asyncio.Semaphore(max_concurrent)
    # trust_env=False：代理显式传入（在线时走 Clash，离线时直连），不读环境变量
    client = httpx.AsyncClient(
        proxy=proxy, timeout=per_page_timeout, follow_redirects=True,
        headers={"User-Agent": UA, "Accept-Language": "zh-CN,en;q=0.8"},
        trust_env=False)

    async def guarded(u: str) -> PageFetch:
        async with sem:
            return await asyncio.wait_for(_fetch_one(client, u, max_bytes),
                                          timeout=per_page_timeout + 3)

    task_urls: dict[asyncio.Task, str] = {}
    tasks = []
    for u in urls:
        t = asyncio.create_task(guarded(u))
        task_urls[t] = u
        tasks.append(t)
    try:
        done, pending = await asyncio.wait(tasks, timeout=max(deadline, 1.0))
        for t in pending:
            t.cancel()
        results = []
        for t in done:
            try:
                results.append(t.result())
            except Exception:
                results.append(PageFetch(url=task_urls[t], error="抓取超时跳过"))
        return results
    finally:
        await client.aclose()
