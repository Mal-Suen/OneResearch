# -*- coding: utf-8 -*-
"""调研流水线编排：research 一次成型＋fetch_digest 批量阅读。"""
import asyncio
import datetime
import json
import time
from pathlib import Path

from .cache import cache_load, cache_store, make_cache_key
from .config import llm_configured, load_config, proxy_alive
from .engines import is_junk_url, normalize_url, run_searches
from .extract import extract_page
from .fetch import fetch_pages
from .llm import LLMClient
from .queries import _product_term, build_queries, extract_terms
from .rank import authority_of, domain_of, rank_sources, select_sources
from .report import (_fail_report, _material_text, _missing_terms,
                     _research_report, _snippet_report, digest_report)

DEPTH_BUDGET = {"quick": 32, "standard": 50, "deep": 80}


def _pick_fetch_urls(results, limit: int) -> list[str]:
    """按权威度＋引擎位置挑抓取目标，同域名最多 3 条保证多样性。"""
    ranked = sorted(results,
                    key=lambda r: -(authority_of(r.url) * 2 + 1.5 / max(r.position, 1)))
    urls, seen = [], {}
    for r in ranked:
        d = domain_of(r.url)
        if d == "baidu.com" and "/link" in r.url:
            d = r.url  # 未解析的跳转链接视为独立站点
        if seen.get(d, 0) >= 3:
            continue
        urls.append(r.url)
        seen[d] = seen.get(d, 0) + 1
        if len(urls) >= limit:
            break
    return urls


async def _extract_all(pages, min_chars: int = 120) -> list:
    if not pages:
        return []
    contents = await asyncio.gather(
        *[asyncio.to_thread(extract_page, p.url, p.html, p.final_url)
          for p in pages])
    return [c for c in contents if c.chars >= min_chars]


def _quote_term(term: str) -> str:
    """复合词加引号精准匹配（避免被搜索引擎拆散）。"""
    if len(term) >= 6 and any(c in term for c in "-._"):
        return f'"{term}"'
    return term


def _log_research(question, depth, elapsed, engine_status, results_count,
                  chosen_count, cache_hit, synthesis_ok, llm_used,
                  synthesis_error=""):
    """JSONL 运行日志（追加写入 .cache/research_log.jsonl，失败静默）。"""
    try:
        from .cache import CACHE_DIR
        log_path = CACHE_DIR / "research_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.datetime.now().isoformat()[:19],
            "question": question[:100],
            "depth": depth,
            "elapsed_s": round(elapsed),
            "engines": engine_status,
            "results": results_count,
            "chosen": chosen_count,
            "cache_hit": cache_hit,
            "llm": llm_used,
            "synthesis": synthesis_ok,
        }
        if synthesis_error:
            entry["synthesis_error"] = synthesis_error[:120]
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


async def run_research(question: str, depth: str = "standard", focus: str = "",
                       recency: str = "", max_sources: int | None = None,
                       cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    t0 = time.monotonic()
    question = " ".join((question or "").split())
    if not question:
        return "错误：question 为空"
    depth = depth if depth in DEPTH_BUDGET else "standard"
    budget = DEPTH_BUDGET[depth]
    try:
        max_sources = int(max_sources or cfg["output"]["max_sources"])
    except (TypeError, ValueError):
        max_sources = cfg["output"]["max_sources"]
    max_sources = max(1, min(max_sources, 12))
    notes: list[str] = []

    # 1+2) 查询生成与双引擎搜索（同题 2 小时内直接复用搜索结果，LLM 模式同样命中）
    llm: LLMClient | None = None
    if llm_configured(cfg):
        llm = LLMClient(cfg["llm"]["base_url"], cfg["llm"]["api_key"],
                        cfg["llm"]["model"])
    proxy = cfg["proxy"] if proxy_alive(cfg["proxy"]) else None
    engines = list(cfg["search"]["engines"])
    if proxy is None and "duckduckgo" in engines:
        # DDG 依赖代理：代理离线时直接跳过（直连必超时，白等 15 秒）
        engines.remove("duckduckgo")

    cache_key = make_cache_key({"question": question, "depth": depth,
                                "focus": focus, "recency": recency})
    cached = cache_load(cache_key)
    if cached is not None:
        queries = cached["queries"]
        results = cached["results"]
        engine_status = {"缓存": f"命中（{len(results)} 条，2 小时内）"}
        notes.append("搜索结果命中 2 小时缓存，跳过查询生成与搜索")
    else:
        queries = build_queries(question, depth, focus)
        if llm is not None:
            try:
                gq = await asyncio.wait_for(llm.gen_queries(question, 3), timeout=20)
                if gq:
                    # 保鲜查询始终保留，与 LLM 查询合并（上限 5 条）
                    freshness = [q for q in queries if "release notes" in q]
                    queries = list(dict.fromkeys(
                        [question] + gq[:3] + freshness))[:5]
                    notes.append("查询经内部 LLM 扩展")
            except Exception as e:
                notes.append(f"LLM 查询生成失败（{type(e).__name__}），回退本地查询")
        if proxy is None:
            notes.append("代理不在线，DuckDuckGo 不可用，仅直连引擎")
        results, engine_status = await run_searches(
            queries, engines,
            cfg["search"]["max_results_per_engine"], proxy,
            cfg["search"]["timeout"], recency)
        if results and not any("失败" in v for v in engine_status.values()):
            cache_store(cache_key, queries, results)
    if not results:
        return _fail_report(question, queries, engine_status, notes,
                            time.monotonic() - t0)

    # 3) 抓取
    urls = _pick_fetch_urls(results, min(max_sources + 5, len(results)))
    fetch_deadline = max(5.0, budget - (time.monotonic() - t0) - 12.0)
    pages_raw = await fetch_pages(
        urls, proxy, max_concurrent=cfg["fetch"]["max_concurrent"],
        per_page_timeout=cfg["fetch"]["per_page_timeout"],
        max_bytes=cfg["fetch"]["max_bytes_per_page"], deadline=fetch_deadline)
    ok_pages = [p for p in pages_raw if p.status == 200 and p.html]

    # 4) 提取＋打分浓缩
    contents = await _extract_all(ok_pages)
    per_source = cfg["output"]["per_source_chars"]
    total_budget = max(3000, cfg["output"]["max_report_chars"] - 2600)
    scored = rank_sources(contents, results, question, focus, recency)
    chosen = select_sources(scored, max_sources, per_source, total_budget)
    if not chosen:
        return _snippet_report(question, queries, results, engine_status, notes,
                               pages_raw, time.monotonic() - t0)

    # 4b) 缺口驱动迭代搜索（standard 1 轮，deep 2 轮，时间允许时自动补盲区）
    cache_hit = cached is not None
    gap_added = False
    max_rounds = 2 if depth == "deep" else 1
    for round_num in range(max_rounds):
        if time.monotonic() - t0 >= budget * 0.6:
            break
        miss_en, miss_zh = _missing_terms(question, focus, chosen)
        gap_terms = miss_en[:3] + miss_zh[:2]
        if not gap_terms:
            break  # 无缺口，提前结束
        product = _product_term(extract_terms(question)[0])
        parts = ([_quote_term(product)] if product and product not in gap_terms else [])
        parts += [_quote_term(t) for t in gap_terms[:3]]
        gap_query = " ".join(parts)
        results2, _st2 = await run_searches(
            [gap_query], engines,
            cfg["search"]["max_results_per_engine"], proxy,
            cfg["search"]["timeout"], recency)
        seen = {normalize_url(r.url) for r in results}
        fresh = [r for r in results2 if normalize_url(r.url) not in seen
                 and not is_junk_url(r.url)]
        if not fresh:
            break  # 补搜无新结果，继续也没意义
        results = results + fresh  # 并入总结果：报告「其他候选」与下一轮去重可见
        gap_added = True
        pages2 = await fetch_pages(
            _pick_fetch_urls(fresh, 4), proxy,
            max_concurrent=cfg["fetch"]["max_concurrent"],
            per_page_timeout=cfg["fetch"]["per_page_timeout"],
            max_bytes=cfg["fetch"]["max_bytes_per_page"], deadline=12.0)
        contents += await _extract_all(
            [p for p in pages2 if p.status == 200 and p.html])
        scored = rank_sources(contents, results, question, focus, recency)
        chosen = select_sources(scored, max_sources, per_source, total_budget)
        notes.append(f"第 {round_num + 1} 轮补搜（缺口 {len(gap_terms)} 词）：{gap_query}")
    if gap_added:
        cache_store(cache_key, queries, results)  # 补搜结果入缓存，同题二跑免补搜

    # 5) LLM 合成（可选，允许略超预算）
    synthesis = ""
    synthesis_error = ""
    if llm is not None:
        remain = budget + 25 - (time.monotonic() - t0)
        if remain > 15:
            try:
                synthesis = await asyncio.wait_for(
                    llm.synthesize(question, _material_text(chosen)), timeout=remain)
            except Exception as e:
                synthesis_error = f"{type(e).__name__}: {str(e)[:100]}"
                notes.append(f"LLM 合成失败（{type(e).__name__}），返回本地材料报告")
        else:
            synthesis_error = "剩余时间不足，跳过"
            notes.append("剩余时间不足，跳过 LLM 合成")
    if not synthesis and llm is not None:
        notes.append("报告为原始材料模式（未经 LLM 合成），建议主模型自行综合")

    _log_research(question, depth, time.monotonic() - t0, engine_status,
                  len(results), len(chosen), cache_hit, bool(synthesis),
                  llm is not None, synthesis_error)
    return _research_report(question, depth, focus, queries, chosen, results,
                            engine_status, notes, synthesis,
                            time.monotonic() - t0,
                            cfg["output"]["max_report_chars"])


async def run_fetch_digest(urls: list[str], question: str = "",
                           cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    t0 = time.monotonic()
    urls = [u.strip() for u in (urls or []) if u.strip()][:10]
    if not urls:
        return "错误：urls 为空"
    proxy = cfg["proxy"] if proxy_alive(cfg["proxy"]) else None
    pages_raw = await fetch_pages(
        urls, proxy, max_concurrent=cfg["fetch"]["max_concurrent"],
        per_page_timeout=cfg["fetch"]["per_page_timeout"],
        max_bytes=cfg["fetch"]["max_bytes_per_page"],
        deadline=cfg["fetch"]["deadline_seconds"])
    ok_pages = [p for p in pages_raw if p.status == 200 and p.html]
    contents = await _extract_all(ok_pages, min_chars=60)
    if not contents:
        fails = [f"{p.url}（{p.error or p.status}）" for p in pages_raw]
        return "全部 URL 抓取失败：" + "；".join(fails[:10])

    scored = rank_sources(contents, [], question, "", "")
    # digest 模式不做噪音过滤：URL 是调用方指定的，零命中或同域名也不丢弃
    chosen = select_sources(scored, len(contents), cfg["output"]["per_source_chars"],
                            cfg["output"]["max_report_chars"], filter_noise=False)
    return digest_report(chosen, pages_raw, urls, len(contents), question,
                         time.monotonic() - t0, cfg["output"]["max_report_chars"])
