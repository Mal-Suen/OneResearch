# -*- coding: utf-8 -*-
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oneresearch.extract import PageContent
from oneresearch.rank import (_term_hits, authority_note, authority_of,
                              domain_of, rank_sources, select_sources,
                              split_passages)
from oneresearch.search import (SearchResult, build_queries, extract_terms,
                                is_junk_url, normalize_url)


def test_extract_terms_mixed():
    en, zh = extract_terms("pyJianYingDraft 最新版本和剪映 11 兼容性怎么样")
    assert "pyJianYingDraft" in en
    assert "11" in en
    assert any("剪映" in z for z in zh)
    assert all(z != "怎么样" for z in zh)


def test_extract_terms_numbers():
    q = "2026 年个人博客静态站点生成器选型：Astro、Hugo、Next.js 的现状与对比"
    en, zh = extract_terms(q)
    assert "2026" in en
    assert "Astro" in en and "Hugo" in en
    queries = build_queries(q, "standard")
    assert any("2026" in x for x in queries)
    assert any("release notes" in x for x in queries)
    deep = build_queries(q, "deep")
    assert all(x.count("2026") <= 1 for x in deep)
    assert any("2026" in x for x in deep)


def test_build_queries_depths():
    q = "pyJianYingDraft 最新版本和剪映兼容性怎么样"
    assert len(build_queries(q, "quick")) == 1
    assert len(build_queries(q, "standard")) >= 2
    assert len(build_queries(q, "deep")) >= 2
    focused = build_queries(q, "standard", focus="草稿目录")
    assert any("草稿目录" in x for x in focused)


def test_authority_and_note():
    assert authority_of("https://github.com/a/b") >= 3
    assert authority_of("https://someone.github.io/x") >= 3
    assert authority_of("https://weibo.com/x") < 1
    assert authority_of("https://example.unknown.org/") == 1.0
    assert "官方" in authority_note("https://github.com/a")
    assert domain_of("https://www.github.com/a/b") == "github.com"


def test_normalize_and_junk():
    assert normalize_url("https://GitHub.com/a/b/?utm_source=x&id=1") == "github.com/a/b?id=1"
    assert is_junk_url("https://www.youtube.com/watch?v=1")
    assert is_junk_url("https://example.com/login?next=/")
    assert not is_junk_url("https://github.com/a")


def test_split_passages_caps():
    text = "\n".join(["这是用于测试的长段落。" * 40] * 3)
    ps = split_passages(text, max_chars=200)
    assert ps and all(len(p) <= 210 for p in ps)


def test_term_hits():
    h1 = _term_hits("pyJianYingDraft 0.3.0 支持剪映 11 草稿生成",
                    ["pyJianYingDraft"], ["剪映"])
    h2 = _term_hits("完全无关的段落内容，不包含任何检索词",
                    ["pyJianYingDraft"], ["剪映"])
    assert h1 > 0
    assert h2 == 0


def test_rank_and_select_budget():
    pages = [PageContent(url=f"https://site{i}.com/a", title=f"T{i}",
                         text="pyJianYingDraft 剪映 兼容性 " + "正文内容。" * 120,
                         date="2026-09-01", chars=800)
             for i in range(6)]
    results = [SearchResult(title=f"T{i}", url=f"https://site{i}.com/a",
                            snippet="pyJianYingDraft 剪映", engine="bing",
                            position=i + 1)
               for i in range(6)]
    scored = rank_sources(pages, results, "pyJianYingDraft 剪映兼容性", "", "")
    assert len(scored) == 6
    chosen = select_sources(scored, 4, 300, 1200)
    assert 1 <= len(chosen) <= 4
    assert sum(s["kept_chars"] for s in chosen) <= 1200 + 350
    # 域名多样性：6 个不同域名时不应因同域被限流
    assert len({domain_of(s["page"].url) for s in chosen}) == len(chosen)


def test_select_sources_content_dedup():
    pages = [PageContent(url=f"https://mirror{i}.com/a", title=f"M{i}",
                         text="完全相同的首段内容，用于指纹去重测试。" + "补充" * 100,
                         date="2026-09-01", chars=700)
             for i in range(3)]
    results = [SearchResult(title=f"M{i}", url=f"https://mirror{i}.com/a",
                            engine="bing", position=i + 1)
               for i in range(3)]
    scored = rank_sources(pages, results, "指纹去重", "", "")
    chosen = select_sources(scored, 3, 500, 3000)
    assert len(chosen) == 1


def test_challenge_page_filtered():
    pages = [PageContent(url="https://a.com/x", title="Client Challenge",
                         text="A required part of this site couldn't load. "
                              "This may be due to a browser extension, network issues, "
                              "or browser settings. Please check your connection, "
                              "disable any ad blockers, or try using a different browser.",
                         date="", chars=286),
             PageContent(url="https://b.com/y", title="正常文章",
                         text="pyJianYingDraft 剪映 兼容性 正常内容。" * 40,
                         date="", chars=1000)]
    results = [SearchResult(title="a", url="https://a.com/x", engine="baidu", position=1),
               SearchResult(title="b", url="https://b.com/y", engine="baidu", position=2)]
    scored = rank_sources(pages, results, "pyJianYingDraft 兼容性", "", "")
    assert len(scored) == 1
    assert scored[0]["page"].url == "https://b.com/y"
