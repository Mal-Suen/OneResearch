# -*- coding: utf-8 -*-
"""同题 2 小时参数级搜索缓存：键＝(question/depth/focus/recency)，存查询＋搜索结果。"""
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from .engines import SearchResult

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_TTL_SECONDS = 2 * 3600
CACHE_MAX_ENTRIES = 50


def make_cache_key(parts: dict) -> str:
    """由调研参数（问题/深度/聚焦/时效）构造缓存键。"""
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cache_load(key: str) -> dict | None:
    """读取缓存条目 {"queries": [...], "results": [SearchResult...]}；不存在或过期返回 None。"""
    try:
        data = json.loads((CACHE_DIR / "search_cache.json").read_text(encoding="utf-8"))
        entry = data.get(key)
        if not entry or time.time() - entry.get("ts", 0) > CACHE_TTL_SECONDS:
            return None
        return {
            "queries": [q for q in entry.get("queries", []) if isinstance(q, str)],
            "results": [SearchResult(**r) for r in entry.get("results", [])],
        }
    except Exception:
        return None


def cache_store(key: str, queries: list[str], results: list[SearchResult]) -> None:
    """写入缓存条目，顺带清理过期与超量条目；失败静默（缓存不可用不影响调研）。"""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        f = CACHE_DIR / "search_cache.json"
        data = {}
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        now = time.time()
        data = {k: v for k, v in data.items()
                if now - (v.get("ts") or 0) <= CACHE_TTL_SECONDS}
        while len(data) >= CACHE_MAX_ENTRIES:
            oldest = min(data, key=lambda k: (data[k].get("ts") or 0))
            del data[oldest]
        data[key] = {"ts": now, "queries": list(queries),
                     "results": [asdict(r) for r in results]}
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
