# -*- coding: utf-8 -*-
import asyncio
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import oneresearch.search as s
from oneresearch.search import SearchResult, _cache_key, _cache_load, _cache_store


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "CACHE_DIR", tmp_path)
    results = [SearchResult(title="t", url="https://a.com/x", snippet="s",
                            engine="baidu", position=1)]
    key = _cache_key(["q"], ["duckduckgo", "baidu"], "")
    assert _cache_load(key) is None
    _cache_store(key, results)
    assert _cache_load(key) == results


def test_cache_ttl_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "CACHE_DIR", tmp_path)
    key = _cache_key(["q"], ["baidu"], "")
    _cache_store(key, [SearchResult(title="t", url="https://a.com/x")])
    f = tmp_path / "search_cache.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data[key]["ts"] = time.time() - s.CACHE_TTL_SECONDS - 10
    f.write_text(json.dumps(data), encoding="utf-8")
    assert _cache_load(key) is None


def test_run_searches_cache_hit_no_network(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "CACHE_DIR", tmp_path)
    queries = ["缓存命中测试"]
    engines = ["duckduckgo", "baidu"]
    seeded = [SearchResult(title="缓存页", url="https://cached.example/x",
                           snippet="snip", engine="baidu", position=1)]
    _cache_store(_cache_key(queries, engines, ""), seeded)
    results, status = asyncio.run(
        s.run_searches(queries, engines, 8, None, 15, ""))
    assert results == seeded
    assert "缓存" in status


def test_run_searches_recency_skips_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "CACHE_DIR", tmp_path)
    queries = ["时效查询"]
    _cache_store(_cache_key(queries, [], "month"),
                 [SearchResult(title="x", url="https://a.com/x")])
    results, _status = asyncio.run(
        s.run_searches(queries, [], 8, None, 15, "month"))
    assert results == []
