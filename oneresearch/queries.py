# -*- coding: utf-8 -*-
"""检索词抽取与本地查询扩展：英文词＋数字（年份/版本号）＋中文词组；保鲜查询；deep 年份。"""
import datetime
import re

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
