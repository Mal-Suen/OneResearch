# -*- coding: utf-8 -*-
import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import oneresearch.fetch as fetch_mod


def test_fetch_timeout_records_error(monkeypatch):
    """wait_for 超时的页面应有 error 记录，不再被静默吞掉。"""
    async def fake_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(fetch_mod.asyncio, "wait_for", fake_wait_for)

    async def main():
        return await fetch_mod.fetch_pages(
            ["https://example.com/slow"], None,
            per_page_timeout=0.5, deadline=5)

    results = asyncio.run(main())
    assert len(results) == 1
    assert results[0].url == "https://example.com/slow"
    assert "超时" in results[0].error
