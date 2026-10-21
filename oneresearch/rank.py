# -*- coding: utf-8 -*-
"""相关性打分与浓缩：关键词覆盖＋来源权威度＋时效。"""
import datetime
import re
from urllib.parse import urlparse

from .extract import PageContent
from .search import SearchResult, extract_terms

AUTHORITY = {
    "github.com": 3.0, "gitlab.com": 2.5, "stackoverflow.com": 2.5,
    "docs.python.org": 3.0, "developer.mozilla.org": 3.0, "readthedocs.io": 3.0,
    "npmjs.com": 2.5, "pypi.org": 2.5, "modelcontextprotocol.io": 3.0,
    "openai.com": 3.0, "anthropic.com": 3.0, "qwen.ai": 3.0, "zhipu.ai": 3.0,
    "bigmodel.cn": 3.0, "deepseek.com": 3.0, "volcengine.com": 3.0,
    "bytedance.com": 2.5, "mcpworld.com": 2.0, "smithery.ai": 2.0, "glama.ai": 2.0,
    "juejin.cn": 2.0, "zhihu.com": 2.0, "zhuanlan.zhihu.com": 2.0,
    "cnblogs.com": 2.0, "segmentfault.com": 2.0, "infoq.cn": 2.0,
    "v2ex.com": 2.0, "sspai.com": 2.0, "ruanyifeng.com": 2.5,
    "medium.com": 1.5, "dev.to": 2.0, "news.ycombinator.com": 2.0,
    "reddit.com": 1.5, "csdn.net": 1.5, "blog.csdn.net": 1.5, "51cto.com": 1.5,
}
PENALTY_HOSTS = {
    "weibo.com": 0.5, "tieba.baidu.com": 0.5, "baijiahao.baidu.com": 0.6,
    "wenku.baidu.com": 0.6,
}


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def authority_of(url: str) -> float:
    d = domain_of(url)
    if d in AUTHORITY:
        return AUTHORITY[d]
    if d in PENALTY_HOSTS:
        return PENALTY_HOSTS[d]
    if d.endswith(".github.io"):
        return 3.0
    if d.endswith(".gov.cn") or d.endswith(".edu.cn"):
        return 2.5
    return 1.0


def authority_note(url: str) -> str:
    a = authority_of(url)
    if a >= 3:
        return "官方/源码级"
    if a >= 2:
        return "知名技术社区"
    if a < 1:
        return "低可信度来源"
    return "普通来源"


_CHALLENGE_MARKERS = (
    "client challenge", "just a moment", "enable javascript and cookies",
    "verify you are human", "access denied", "请完成安全验证",
    "百度安全验证", "请求被拦截",
)


def _is_challenge_page(page: PageContent) -> bool:
    """短页且命中反爬/验证特征词的按挑战页丢弃。"""
    if page.chars >= 800:
        return False
    head = page.text[:300].lower()
    return any(m in head for m in _CHALLENGE_MARKERS)


def split_passages(text: str, min_chars: int = 40, max_chars: int = 700) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n+", text) if len(p.strip()) >= min_chars]
    out: list[str] = []
    for p in paras:
        if len(p) <= max_chars:
            out.append(p)
            continue
        buf = ""
        for s in re.split(r"(?<=[。！？.!?])", p):
            if buf and len(buf) + len(s) > max_chars:
                out.append(buf.strip())
                buf = s
            else:
                buf += s
        if buf.strip():
            out.append(buf.strip())
    return out


def _term_hits(passage: str, en_terms: list[str], zh_terms: list[str]) -> float:
    low = passage.lower()
    hits = 0.0
    for w in en_terms:
        if w.lower() in low:
            hits += 2.0
    for z in zh_terms:
        if z in passage:
            hits += 2.0 + min(len(z), 4) * 0.25
        elif len(z) > 2:
            grams = [z[i:i + 2] for i in range(len(z) - 1)]
            got = sum(1 for g in grams if g in passage)
            if got:
                hits += 1.0 * got / len(grams)
    return hits


def recency_bonus(date_str: str, recency: str) -> float:
    if not date_str:
        return 0.0
    try:
        d = datetime.date.fromisoformat(date_str[:10])
        days = (datetime.date.today() - d).days
    except Exception:
        return 0.0
    if recency == "month":
        return 3.0 if days <= 35 else (-1.0 if days > 400 else 0.0)
    if recency == "year":
        return 2.0 if days <= 400 else -1.0
    return 1.0 if days <= 400 else 0.0


def rank_sources(pages: list[PageContent], results: list[SearchResult],
                 question: str, focus: str, recency: str) -> list[dict]:
    """对每个抓到的页面切段打分。返回按来源总分降序的列表。"""
    en, zh = extract_terms(question)
    if focus:
        fen, fzh = extract_terms(focus)
        en, zh = en + fen, zh + fzh
    result_by_url: dict[str, SearchResult] = {}
    for r in results:
        result_by_url.setdefault(r.url, r)

    scored: list[dict] = []
    for page in pages:
        if page.chars < 120 or _is_challenge_page(page):
            continue
        res = result_by_url.get(page.url)
        auth = authority_of(page.final_url or page.url)
        rec = recency_bonus(page.date, recency)
        passages = split_passages(page.text)
        ranked: list[tuple[float, int, str]] = []
        for idx, p in enumerate(passages):
            score = _term_hits(p, en, zh)
            score += max(0.0, 1.0 - idx / max(len(passages), 1)) * 0.8
            score += auth * 1.5 + rec
            if res is not None and res.snippet:
                score += min(_term_hits(res.snippet, en, zh) * 0.25, 1.0)
            ranked.append((score, idx, p))
        if not ranked:
            continue
        ranked.sort(key=lambda x: (-x[0], x[1]))
        total = ranked[0][0]
        if res is not None:
            total += 1.5 / max(res.position, 1)
        scored.append({"page": page, "result": res, "authority": auth,
                       "recency": rec, "passages": ranked, "total": total})
    scored.sort(key=lambda s: -s["total"])
    return scored


def select_sources(scored: list[dict], max_sources: int, per_source_chars: int,
                   max_total_chars: int) -> list[dict]:
    """选来源：域名多样性＋内容指纹去重＋每源段数与字数上限＋全局字数预算。"""
    chosen: list[dict] = []
    used_domains: dict[str, int] = {}
    seen_fingerprints: set[str] = set()
    total = 0
    for s in scored:
        if len(chosen) >= max_sources:
            break
        d = domain_of(s["page"].final_url or s["page"].url)
        if used_domains.get(d, 0) >= 2:
            continue
        kept: list[tuple[float, str]] = []
        used = 0
        seen_passages: set[str] = set()
        for score, _idx, p in s["passages"]:
            if len(kept) >= 3 or used >= per_source_chars:
                break
            if p[:60] in seen_passages:
                continue
            seen_passages.add(p[:60])
            piece = p if used + len(p) <= per_source_chars else p[:per_source_chars - used]
            if not piece.strip():
                continue
            kept.append((score, piece))
            used += len(piece)
        if not kept:
            continue
        fingerprint = kept[0][1][:80]
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        s = dict(s)
        s["kept"] = kept
        s["kept_chars"] = sum(len(p) for _, p in kept)
        chosen.append(s)
        used_domains[d] = used_domains.get(d, 0) + 1
        total += s["kept_chars"]
    while total > max_total_chars and len(chosen) > 1:
        last = chosen[-1]
        if len(last["kept"]) > 1:
            _, p = last["kept"].pop()
            last["kept_chars"] -= len(p)
            total -= len(p)
        else:
            removed = chosen.pop()
            total -= removed["kept_chars"]
    return chosen
