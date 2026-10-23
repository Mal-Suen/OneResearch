# -*- coding: utf-8 -*-
"""报告组装：调研报告／搜索摘要／失败报告／批量页面摘要四种形态。"""
import datetime

from .queries import extract_terms
from .rank import authority_note, domain_of


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _u(page) -> str:
    """展示用 URL：优先重定向后的最终地址。"""
    return page.final_url or page.url


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


def digest_report(chosen, pages_raw, urls, ok_count, question, elapsed,
                  max_chars) -> str:
    """批量页面摘要报告（fetch_digest 用）。"""
    lines = [
        "# 批量页面摘要",
        "",
        f"- 请求 {len(urls)} 个 URL，成功 {ok_count} 个｜耗时 {elapsed:.0f}s"
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
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…（已达报告长度上限，截断）"
    return text
