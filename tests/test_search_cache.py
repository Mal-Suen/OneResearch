# -*- coding: utf-8 -*-
"""搜索缓存：参数级键（question/depth/focus/recency）＋TTL＋流水线集成。"""
import asyncio
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import oneresearch.pipeline as pl
import oneresearch.search as s
from oneresearch.extract import PageContent
from oneresearch.fetch import PageFetch
from oneresearch.search import (SearchResult, cache_load, cache_store,
                                make_cache_key)


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "CACHE_DIR", tmp_path)
    key = make_cache_key({"question": "缓存测试", "depth": "standard",
                          "focus": "", "recency": ""})
    assert cache_load(key) is None
    cache_store(key, ["查询一"],
                [SearchResult(title="t", url="https://a.com/x", snippet="s",
                              engine="baidu", position=1)])
    entry = cache_load(key)
    assert entry["queries"] == ["查询一"]
    assert entry["results"][0].url == "https://a.com/x"
    assert entry["results"][0].engine == "baidu"


def test_cache_ttl_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "CACHE_DIR", tmp_path)
    key = make_cache_key({"question": "q"})
    cache_store(key, ["q"], [SearchResult(title="t", url="https://a.com/x")])
    f = tmp_path / "search_cache.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data[key]["ts"] = time.time() - s.CACHE_TTL_SECONDS - 10
    f.write_text(json.dumps(data), encoding="utf-8")
    assert cache_load(key) is None


def test_cache_key_separates_params():
    base = make_cache_key({"question": "q", "depth": "standard",
                           "focus": "", "recency": ""})
    variants = [
        make_cache_key({"question": "q", "depth": "standard",
                        "focus": "", "recency": "month"}),
        make_cache_key({"question": "q", "depth": "standard",
                        "focus": "价格", "recency": ""}),
        make_cache_key({"question": "q", "depth": "deep",
                        "focus": "", "recency": ""}),
    ]
    assert len({base, *variants}) == 4


CFG = {
    "proxy": "http://127.0.0.1:1",
    "search": {"engines": ["duckduckgo", "baidu"], "max_results_per_engine": 8,
               "timeout": 15},
    "fetch": {"max_concurrent": 6, "per_page_timeout": 12,
              "max_bytes_per_page": 2000000, "deadline_seconds": 55},
    "output": {"max_report_chars": 14000, "per_source_chars": 1800,
               "max_sources": 8},
    "llm": {"enabled": False, "base_url": "", "api_key": "", "model": ""},
    "doubao": {"api_key": "", "version": "global"},
}


def test_run_research_pipeline_cache_hit(tmp_path, monkeypatch):
    """同题二跑：第二次跳过查询生成与搜索（LLM 模式缓存失效问题由此修复）。"""
    monkeypatch.setattr(s, "CACHE_DIR", tmp_path)
    calls = {"search": 0, "fetch": 0}

    async def fake_search(queries, engines, max_results, proxy, timeout,
                          recency=""):
        calls["search"] += 1
        return ([SearchResult(title="缓存测试页", url="https://example.com/a",
                             snippet="缓存测试", engine="baidu", position=1)],
                {"baidu": "ok（1 条）"})

    async def fake_fetch(urls, proxy, **kw):
        calls["fetch"] += 1
        return [PageFetch(url=u, status=200, html="<html></html>")
                for u in urls]

    async def fake_extract(pages, min_chars=120):
        return [PageContent(url="https://example.com/a", title="缓存测试页",
                            text="缓存测试 相关正文内容。" * 60,
                            date="2026-10-01", chars=660)]

    monkeypatch.setattr(pl, "run_searches", fake_search)
    monkeypatch.setattr(pl, "fetch_pages", fake_fetch)
    monkeypatch.setattr(pl, "_extract_all", fake_extract)

    q = "缓存测试"
    r1 = asyncio.run(pl.run_research(q, depth="standard", cfg=CFG))
    assert calls["search"] == 1
    assert "缓存：命中" not in r1

    r2 = asyncio.run(pl.run_research(q, depth="standard", cfg=CFG))
    assert calls["search"] == 1
    assert calls["fetch"] == 2
    assert "缓存：命中" in r2
