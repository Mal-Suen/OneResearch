# -*- coding: utf-8 -*-
"""搜索引擎抓取与解析：DuckDuckGo HTML（走代理）＋ 百度（直连，首页 cookie 引导）。

Bing 实测弃用（2026-10-22）：cn.bing.com 将 /search 重定向到 www.bing.com 首页，
www.bing.com 对无浏览器指纹的自动化请求返回与查询无关的缓存结果。
"""
import asyncio
import datetime
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

STOPWORDS_EN = {
    "what", "which", "who", "whom", "when", "where", "why", "how",
    "is", "are", "was", "were", "the", "a", "an", "of", "for", "to",
    "in", "on", "at", "and", "or", "vs", "versus", "with", "about",
    "please", "me", "my", "our", "should", "would", "could", "can",
    "do", "does", "did", "i", "we", "you", "it", "its", "there",
    "any", "some",
}
STOPWORDS_ZH = {
    "什么", "怎么", "怎么样", "怎样", "如何", "哪个", "哪些", "为什么",
    "是不是", "有没有", "请问", "一下", "现在", "目前", "应该", "能够",
    "可以", "还是", "的", "了", "吗", "呢", "吧", "啊", "我", "你",
    "他", "她", "它", "我们",
}
_ZH_SUFFIXES = ("怎么样", "怎样", "如何", "为什么", "什么", "吗", "呢", "吧")


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    engine: str = ""
    position: int = 0


def extract_terms(text: str) -> tuple[list[str], list[str]]:
    """抽取检索词：英文词＋数字（年份/版本号）＋中文词组（用于查询扩展与段落打分）。"""
    en = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9_.+\-]{1,40}", text)
          if w.lower() not in STOPWORDS_EN]
    en += re.findall(r"\d+(?:\.\d+)*", text)
    zh: list[str] = []
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        if run in STOPWORDS_ZH:
            continue
        for sw in _ZH_SUFFIXES:
            if run.endswith(sw) and len(run) > len(sw):
                run = run[: -len(sw)]
        if len(run) >= 2 and run not in STOPWORDS_ZH:
            zh.append(run)
    return en, zh


def _product_term(en_terms: list[str]) -> str:
    """挑最可能的产品名（最长的含字母检索词），用于版本保鲜查询。"""
    alpha = [w for w in en_terms if any(c.isalpha() for c in w)]
    return max(alpha, key=len) if alpha else ""


def build_queries(question: str, depth: str, focus: str = "") -> list[str]:
    """本地查询扩展：原问题＋核心词＋聚焦＋版本保鲜查询；deep 追加年份。"""
    q = " ".join(question.split())
    en, zh = extract_terms(q)
    core = " ".join(en + zh)
    queries = [q]
    if depth != "quick" and core and core != q:
        queries.append(core)
    f = " ".join((focus or "").split())
    if f:
        queries.append(f"{core or q} {f}")
    product = _product_term(en)
    if depth != "quick" and product:
        queries.append(f"{product} 最新版本 release notes")
    if depth == "deep":
        year = str(datetime.date.today().year)
        if year not in q:
            queries.append(f"{core or q} {year}")
    seen, out = set(), []
    for x in queries:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out[:4]


CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_TTL_SECONDS = 2 * 3600
CACHE_MAX_ENTRIES = 50


def _cache_key(queries: list[str], engines: list[str], recency: str) -> str:
    blob = json.dumps({"q": queries, "e": sorted(engines), "r": recency},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_load(key: str) -> list[SearchResult] | None:
    try:
        data = json.loads((CACHE_DIR / "search_cache.json").read_text(encoding="utf-8"))
        entry = data.get(key)
        if not entry or time.time() - entry.get("ts", 0) > CACHE_TTL_SECONDS:
            return None
        return [SearchResult(**r) for r in entry.get("results", [])]
    except Exception:
        return None


def _cache_store(key: str, results: list[SearchResult]) -> None:
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
        data[key] = {"ts": now, "results": [asdict(r) for r in results]}
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


_JUNK_HOSTS = re.compile(
    r"^(www\.)?(youtube\.com|facebook\.com|twitter\.com|x\.com|instagram\.com"
    r"|pinterest\.com|tiktok\.com)$", re.I)


def normalize_url(url: str) -> str:
    """去 utm 等跟踪参数、去锚点、统一主机大小写，用于去重。"""
    try:
        p = urlparse(url.strip())
        host = p.netloc.lower()
        path = p.path.rstrip("/")
        keep = [kv for kv in p.query.split("&")
                if kv and not kv.lower().startswith(("utm_", "ref_", "spm", "from=", "share_"))]
        q = "&".join(keep)
        return f"{host}{path}" + (f"?{q}" if q else "")
    except Exception:
        return url.strip().lower()


def is_junk_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return True
    if _JUNK_HOSTS.match(host):
        return True
    low = url.lower()
    return any(x in low for x in ("/login", "signin", "signup", "register",
                                   "accounts.", "passport.", "/auth"))


def _unwrap_ddg(href: str) -> str:
    """还原 DuckDuckGo 的 uddg= 跳转链接。"""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    if "uddg=" in href:
        try:
            qs = parse_qs(urlparse(href).query)
            if "uddg" in qs:
                return unquote(qs["uddg"][0])
        except Exception:
            pass
    return href


def parse_ddg_html(html: str) -> list[SearchResult]:
    soup = BeautifulSoup(html, "lxml")
    out: list[SearchResult] = []
    for div in soup.select("div.result"):
        a = div.select_one("a.result__a")
        if not a:
            continue
        url = _unwrap_ddg(a.get("href", ""))
        if not url.startswith("http"):
            continue
        sn = div.select_one(".result__snippet")
        out.append(SearchResult(
            title=a.get_text(" ", strip=True),
            url=url,
            snippet=sn.get_text(" ", strip=True) if sn else "",
            engine="duckduckgo",
            position=len(out) + 1,
        ))
    return out


def parse_ddg_lite_html(html: str) -> list[SearchResult]:
    """解析 lite.duckduckgo.com 极简结果页（table 布局，html 端点限流时的退路）。"""
    soup = BeautifulSoup(html, "lxml")
    out: list[SearchResult] = []
    for a in soup.select("a.result-link"):
        url = _unwrap_ddg(a.get("href", ""))
        if not url.startswith("http"):
            continue
        snippet = ""
        row = a.find_parent("tr")
        if row is not None:
            nxt = row.find_next_sibling("tr")
            if nxt is not None:
                sn = nxt.select_one("td.result-snippet")
                if sn is not None:
                    snippet = sn.get_text(" ", strip=True)
        out.append(SearchResult(
            title=a.get_text(" ", strip=True),
            url=url,
            snippet=snippet,
            engine="duckduckgo",
            position=len(out) + 1,
        ))
    return out


def parse_baidu_html(html: str) -> list[SearchResult]:
    soup = BeautifulSoup(html, "lxml")
    out: list[SearchResult] = []
    for it in soup.select("div#content_left div.result, div#content_left div.c-container"):
        classes = set(it.get("class") or [])
        if "result-op" in classes or any(c.startswith("ec_") for c in classes):
            continue
        a = it.select_one("h3 a")
        if a is None:
            continue
        url = (a.get("href") or "").strip()
        if not url.startswith("http"):
            continue
        sn = it.select_one(".c-abstract, [class*='content-right'], [class*='c-abstract']")
        snippet = sn.get_text(" ", strip=True) if sn else ""
        if not snippet:
            full = it.get_text(" ", strip=True)
            snippet = full.replace(a.get_text(" ", strip=True), " ", 1).strip()[:160]
        out.append(SearchResult(
            title=a.get_text(" ", strip=True),
            url=url,
            snippet=snippet,
            engine="baidu",
            position=len(out) + 1,
        ))
    return out


async def _resolve_baidu_links(client: httpx.AsyncClient,
                               results: list[SearchResult]) -> None:
    """把 baidu link?url= 跳转并发解析成真实 URL（HEAD 跟随重定向）。
    失败保留原链接——抓取阶段仍会跟随重定向拿到真实页面。"""
    async def one(r: SearchResult) -> None:
        if "baidu.com/link" not in r.url:
            return
        try:
            resp = await client.head(r.url)
            final = str(resp.url)
            if final.startswith("http") and "baidu.com/link" not in final:
                r.url = final
        except Exception:
            pass

    try:
        await asyncio.wait_for(asyncio.gather(*(one(r) for r in results)), timeout=10)
    except asyncio.TimeoutError:
        pass


async def _search_ddg(client: httpx.AsyncClient, query: str,
                      max_results: int, recency: str) -> list[SearchResult]:
    data = {"q": query}
    if recency == "month":
        data["df"] = "m"
    elif recency == "year":
        data["df"] = "y"
    r = await client.post("https://html.duckduckgo.com/html/", data=data)
    r.raise_for_status()
    results = parse_ddg_html(r.text)
    if not results:
        # html 端点被限流（202 异常页）时退到 lite 端点再试一次
        r2 = await client.get("https://lite.duckduckgo.com/lite/", params=data)
        r2.raise_for_status()
        results = parse_ddg_lite_html(r2.text)
    return results[:max_results]


async def _search_baidu(client: httpx.AsyncClient, query: str,
                        max_results: int) -> list[SearchResult]:
    r = await client.get("https://www.baidu.com/s", params={"wd": query, "rn": 15})
    r.raise_for_status()
    return parse_baidu_html(r.text)[:max_results]


async def run_searches(queries: list[str], engines: list[str], max_results: int,
                       proxy: str | None, timeout: float,
                       recency: str = "") -> tuple[list[SearchResult], dict]:
    """双引擎并发搜索，返回（合并去重结果，引擎状态）。2 小时内相同查询直接走缓存。"""
    status: dict[str, str] = {}
    cache_key = None
    if not recency:
        cache_key = _cache_key(queries, engines, recency)
        hit = _cache_load(cache_key)
        if hit is not None:
            return hit, {"缓存": f"命中（{len(hit)} 条，2 小时内）"}
    ddg_client = httpx.AsyncClient(proxy=proxy, timeout=timeout,
                                   follow_redirects=True, headers=HEADERS)
    baidu_client = httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     headers=HEADERS)

    async def ddg_all() -> list[SearchResult]:
        results: list[SearchResult] = []
        for i, q in enumerate(queries):
            if i:
                await asyncio.sleep(0.7)
            try:
                results += await _search_ddg(ddg_client, q, max_results, recency)
            except Exception as e:
                status["duckduckgo"] = f"失败（{type(e).__name__}）"
        if "duckduckgo" not in status:
            status["duckduckgo"] = (f"ok（{len(results)} 条）" if results
                                    else "0 条（html 与 lite 均无结果，疑似限流）")
        return results

    async def baidu_all() -> list[SearchResult]:
        results: list[SearchResult] = []
        try:
            await baidu_client.get("https://www.baidu.com/")  # 首页 cookie 引导
        except Exception:
            pass
        for i, q in enumerate(queries):
            if i:
                await asyncio.sleep(0.8)  # 与 DDG 一致间隔，降低连发触发反爬
            try:
                results += await _search_baidu(baidu_client, q, max_results)
            except Exception as e:
                status["baidu"] = f"失败（{type(e).__name__}）"
        if results:
            await _resolve_baidu_links(baidu_client, results)
        if "baidu" not in status:
            status["baidu"] = (f"ok（{len(results)} 条）" if results
                               else "0 条（可能触发反爬或无结果）")
        return results

    try:
        tasks, names = [], []
        if "duckduckgo" in engines:
            tasks.append(asyncio.create_task(ddg_all()))
            names.append("duckduckgo")
        if "baidu" in engines:
            tasks.append(asyncio.create_task(baidu_all()))
            names.append("baidu")
        gathered = list(await asyncio.gather(*tasks)) if tasks else []
        per_engine = dict(zip(names, gathered))
    finally:
        await ddg_client.aclose()
        await baidu_client.aclose()

    merged: list[SearchResult] = []
    seen: set[str] = set()
    for name in ("duckduckgo", "baidu"):
        for res in per_engine.get(name, []):
            if is_junk_url(res.url):
                continue
            key = normalize_url(res.url)
            if key in seen:
                continue
            seen.add(key)
            merged.append(res)
    if cache_key and merged and not any("失败" in v for v in status.values()):
        _cache_store(cache_key, merged)
    return merged, status
