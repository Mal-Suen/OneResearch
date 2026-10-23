# -*- coding: utf-8 -*-
"""调研流水线编排：research 一次成型＋fetch_digest 批量阅读。"""
import asyncio
import datetime
import time

from .config import llm_configured, load_config, proxy_alive
from .extract import extract_page
from .fetch import fetch_pages
from .llm import LLMClient
from .rank import (authority_note, authority_of, domain_of, rank_sources,
                   select_sources)
from .search import (_product_term, build_queries, cache_load, cache_store,
                     extract_terms, is_junk_url, make_cache_key, normalize_url,
                     run_searches)

DEPTH_BUDGET = {"quick": 32, "standard": 50, "deep": 80}


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _u(page) -> str:
    """展示用 URL：优先重定向后的最终地址。"""
    return page.final_url or page.url


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


def _material_text(chosen: list[dict]) -> str:
    parts = []
    for i, s in enumerate(chosen, 1):
        page = s["page"]
        parts.append(f"[S{i}] {page.title}（{_u(page)}，{page.date or '日期未知'}）")
        for _score, p in s["kept"]:
            parts.append(p)
        parts.append("")
    return "\n".join(parts)


def _missing_terms(question: str, focus: str,
                   chosen: list[dict]) -> tuple[list[str], list[str]]:
    """问题（＋focus）中未被入选来源覆盖的检索词。"""
    en, zh = extract_terms(question)
    if focus:
        fen, fzh = extract_terms(focus)
        en, zh = en + fen, zh + fzh
    corpus = "\n".join(p for s in chosen for _score, p in s["kept"])
    low = corpus.lower()
    miss_en = [w for w in en if w.lower() not in low]
    miss_zh = [z for z in zh
               if z not in corpus and not any(z[i:i + 2] in corpus for i in range(len(z) - 1))]
    return miss_en, miss_zh


def _gap_analysis(question: str, chosen: list[dict]) -> list[str]:
    miss_en, miss_zh = _missing_terms(question, "", chosen)
    gaps = []
    if miss_en:
        gaps.append(f"关键词未命中：{', '.join(miss_en[:8])}")
    if miss_zh:
        gaps.append(f"中文词未命中：{'、'.join(miss_zh[:8])}")
    if not gaps:
        gaps.append("核心关键词均有来源覆盖")
    return gaps


def _research_report(question, depth, queries, chosen, all_results, engine_status,
                     notes, synthesis, elapsed, max_chars) -> str:
    lines = [
        f"# 调研报告：{question}",
        "",
        f"- 深度 {depth}｜耗时 {elapsed:.0f}s｜生成 {_now()}",
        f"- 查询：{'；'.join(queries)}",
        "- 引擎：" + "、".join(f"{k}：{v}" for k, v in engine_status.items()),
    ]
    if notes:
        lines.append("- 备注：" + "；".join(notes))
    lines.append("")
    if synthesis:
        lines.append("## 综合结论（内部 LLM 合成，[S#] 对应下方来源编号）")
        lines.append("")
        lines.append(synthesis.strip())
        lines.append("")
    lines.append("## 各来源要点")
    lines.append("")
    for i, s in enumerate(chosen, 1):
        page, res = s["page"], s["result"]
        title = page.title or (res.title if res is not None else "") or page.url
        stale = ""
        if page.date:
            try:
                d = datetime.date.fromisoformat(page.date[:10])
                if (datetime.date.today() - d).days > 550:
                    stale = "｜较旧来源，注意时效"
            except ValueError:
                pass
        lines.append(f"### [S{i}] {title}")
        lines.append(f"- URL：{_u(page)}")
        lines.append(f"- 日期：{page.date or '未知'}{stale}｜{authority_note(_u(page))}"
                     f"｜正文 {page.chars} 字，摘录 {s['kept_chars']} 字")
        lines.append("")
        for _score, p in s["kept"]:
            lines.append(f"> {p}")
            lines.append("")
    lines.append("## 来源清单")
    lines.append("")
    lines.append("| # | 标题 | 域名 | 日期 |")
    lines.append("|---|---|---|---|")
    for i, s in enumerate(chosen, 1):
        page = s["page"]
        t = (page.title or "")[:40].replace("|", "／")
        lines.append(f"| S{i} | {t} | {domain_of(_u(page))} | {page.date or '—'} |")
    chosen_urls = {s["page"].url for s in chosen}
    extra = [r for r in all_results if r.url not in chosen_urls][:10]
    if extra:
        lines.append("")
        lines.append("其他候选（未抓取或未入选，可用 fetch_digest 定向阅读）：")
        for r in extra:
            lines.append(f"- {r.title[:50]}：{r.url}")
    lines.append("")
    lines.append("## 覆盖情况与缺口")
    lines.append("")
    for g in _gap_analysis(question, chosen):
        lines.append(f"- {g}")
    lines.append("- 材料不足时：带 focus 参数再调研一次，或用 fetch_digest 直接读上方列出的 URL")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…（已达报告长度上限，截断）"
    return text


def _snippet_report(question, queries, results, engine_status, notes, pages_raw,
                    elapsed) -> str:
    lines = [
        f"# 调研报告（搜索结果摘要模式）：{question}",
        "",
        f"- 耗时 {elapsed:.0f}s｜生成 {_now()}｜正文抓取均失败，以下为搜索结果摘要",
        f"- 查询：{'；'.join(queries)}",
        "- 引擎：" + "、".join(f"{k}：{v}" for k, v in engine_status.items()),
    ]
    if notes:
        lines.append("- 备注：" + "；".join(notes))
    lines.append("")
    for i, r in enumerate(results[:12], 1):
        lines.append(f"### [S{i}] {r.title}")
        lines.append(f"- URL：{r.url}（{r.engine}）")
        if r.snippet:
            lines.append(f"- 摘要：{r.snippet[:300]}")
        lines.append("")
    if pages_raw:
        fails = [f"{p.url}（{p.error}）" for p in pages_raw if p.error]
        if fails:
            lines.append("抓取失败明细：" + "；".join(fails[:6]))
            lines.append("")
    lines.append("可用 fetch_digest 重试关键 URL，或稍后再调研一次。")
    return "\n".join(lines)


def _fail_report(question, queries, engine_status, notes, elapsed) -> str:
    lines = [
        f"# 调研失败：{question}",
        "",
        f"- 耗时 {elapsed:.0f}s｜生成 {_now()}",
        f"- 查询：{'；'.join(queries)}",
    ]
    if engine_status:
        lines.append("- 引擎：" + "、".join(f"{k}：{v}" for k, v in engine_status.items()))
    else:
        lines.append("- 引擎：无可用引擎")
    if notes:
        lines.append("- 备注：" + "；".join(notes))
    lines += [
        "",
        "两个引擎均未返回结果：请检查代理是否在线（DuckDuckGo 依赖代理）、网络是否可用，"
        "或稍后重试；也可改用 fetch_digest 直接读已知 URL。",
    ]
    return "\n".join(lines)


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
            queries, cfg["search"]["engines"],
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

    # 4b) 缺口驱动第二轮搜索（standard/deep，时间允许时自动补盲区）
    if depth in ("standard", "deep") and time.monotonic() - t0 < budget * 0.6:
        miss_en, miss_zh = _missing_terms(question, focus, chosen)
        gap_terms = miss_en[:3] + miss_zh[:2]
        if gap_terms:
            product = _product_term(extract_terms(question)[0])
            gap_query = " ".join(
                ([product] if product and product not in gap_terms else [])
                + gap_terms[:3])
            results2, _st2 = await run_searches(
                [gap_query], cfg["search"]["engines"],
                cfg["search"]["max_results_per_engine"], proxy,
                cfg["search"]["timeout"], recency)
            seen = {normalize_url(r.url) for r in results}
            fresh = [r for r in results2 if normalize_url(r.url) not in seen
                     and not is_junk_url(r.url)]
            if fresh:
                pages2 = await fetch_pages(
                    _pick_fetch_urls(fresh, 4), proxy,
                    max_concurrent=cfg["fetch"]["max_concurrent"],
                    per_page_timeout=cfg["fetch"]["per_page_timeout"],
                    max_bytes=cfg["fetch"]["max_bytes_per_page"], deadline=12.0)
                contents += await _extract_all(
                    [p for p in pages2 if p.status == 200 and p.html])
                scored = rank_sources(contents, results + fresh, question, focus, recency)
                chosen = select_sources(scored, max_sources, per_source, total_budget)
                notes.append(f"检测到覆盖缺口，已自动补充第二轮搜索：{gap_query}")

    # 5) LLM 合成（可选，允许略超预算）
    synthesis = ""
    if llm is not None:
        remain = budget + 25 - (time.monotonic() - t0)
        if remain > 15:
            try:
                synthesis = await asyncio.wait_for(
                    llm.synthesize(question, _material_text(chosen)), timeout=remain)
            except Exception as e:
                notes.append(f"LLM 合成失败（{type(e).__name__}），返回本地材料报告")
        else:
            notes.append("剩余时间不足，跳过 LLM 合成")

    return _research_report(question, depth, queries, chosen, results, engine_status,
                            notes, synthesis, time.monotonic() - t0,
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
    chosen = select_sources(scored, len(contents), cfg["output"]["per_source_chars"],
                            cfg["output"]["max_report_chars"])

    lines = [
        "# 批量页面摘要",
        "",
        f"- 请求 {len(urls)} 个 URL，成功 {len(contents)} 个｜耗时 {time.monotonic() - t0:.0f}s"
        + (f"｜排序问题：{question}" if question else ""),
        "",
    ]
    for i, s in enumerate(chosen, 1):
        page = s["page"]
        lines.append(f"### [P{i}] {page.title or page.url}")
        lines.append(f"- URL：{_u(page)}｜日期：{page.date or '未知'}"
                     f"｜正文 {page.chars} 字，摘录 {s['kept_chars']} 字")
        lines.append("")
        for _score, p in s["kept"]:
            lines.append(f"> {p}")
            lines.append("")
    failed = [p for p in pages_raw if p.status != 200]
    if failed:
        lines.append("失败 URL：" + "；".join(f"{p.url}（{p.error or p.status}）"
                                             for p in failed[:6]))
        lines.append("")
    text = "\n".join(lines)
    if len(text) > cfg["output"]["max_report_chars"]:
        text = text[:cfg["output"]["max_report_chars"]] + "\n…（已达报告长度上限，截断）"
    return text
