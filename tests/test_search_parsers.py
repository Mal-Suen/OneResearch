# -*- coding: utf-8 -*-
import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oneresearch.engines import (_search_ddg, parse_baidu_html,
                                 parse_ddg_html, parse_ddg_lite_html)

DDG_HTML = """
<html><body>
<div class="result results_links">
  <h2 class="result__title"><a rel="nofollow" class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2FGuanYixuan%2FpyJianYingDraft&amp;rut=abc">pyJianYingDraft GitHub</a></h2>
  <a class="result__snippet">剪映草稿自动化库 0.3.0</a>
</div>
<div class="result">
  <h2><a class="result__a" href="https://example.com/plain">Plain Example</a></h2>
  <a class="result__snippet">直接链接</a>
</div>
<div class="result">
  <h2><a class="result__a" href="//duckduckgo.com/l/?uddg=not-a-url">Junk</a></h2>
</div>
</body></html>
"""

BAIDU_HTML = """
<html><body><div id="content_left">
<div class="result c-container new-pmd">
  <h3 class="t"><a href="http://www.baidu.com/link?url=abc123">GitHub - GuanYixuan/pyJianYingDraft</a></h3>
  <div class="c-abstract">轻量灵活的 Python 剪映草稿生成工具 0.3.1</div>
</div>
<div class="result c-container">
  <h3><a href="http://www.baidu.com/link?url=def456">剪映官网</a></h3>
  <span class="content-right_8Zs40">剪映视频创作官方页面</span>
</div>
<div class="result-op c-container">
  <h3><a href="http://www.baidu.com/link?url=ghi789">广告位</a></h3>
</div>
<div class="c-container">
  <h3><a href="/relative-nope">坏链接</a></h3>
</div>
</div></body></html>
"""


def test_parse_ddg():
    res = parse_ddg_html(DDG_HTML)
    assert len(res) == 2
    assert res[0].url == "https://github.com/GuanYixuan/pyJianYingDraft"
    assert res[0].engine == "duckduckgo"
    assert "0.3.0" in res[0].snippet
    assert res[1].url == "https://example.com/plain"


def test_parse_baidu():
    res = parse_baidu_html(BAIDU_HTML)
    assert len(res) == 2
    assert res[0].engine == "baidu"
    assert res[0].url == "http://www.baidu.com/link?url=abc123"
    assert "0.3.1" in res[0].snippet
    assert res[1].url == "http://www.baidu.com/link?url=def456"
    assert "官方页面" in res[1].snippet


DDG_LITE_HTML = """
<html><body><table>
<tr><td>1.</td><td><a class="result-link"
  href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2Flibrary%2Fasyncio.html">asyncio documentation</a></td></tr>
<tr><td class="result-snippet">asyncio is a library to write concurrent code.</td></tr>
<tr><td>2.</td><td><a class="result-link" href="https://example.com/direct">Direct Link</a></td></tr>
</table></body></html>
"""


def test_parse_ddg_lite():
    res = parse_ddg_lite_html(DDG_LITE_HTML)
    assert len(res) == 2
    assert res[0].engine == "duckduckgo"
    assert res[0].url == "https://docs.python.org/3/library/asyncio.html"
    assert "concurrent" in res[0].snippet
    assert res[1].url == "https://example.com/direct"
    assert res[1].snippet == ""


def test_search_ddg_403_falls_back_to_lite():
    """html 端点 403（限流）时退到 lite 端点，而不是让引擎整体失败。"""
    calls = []

    class FakeResp:
        def __init__(self, status_code, text=""):
            self.status_code = status_code
            self.text = text

        def raise_for_status(self):
            assert self.status_code < 400, f"unexpected HTTP {self.status_code}"

    class FakeClient:
        async def post(self, url, data=None):
            calls.append("html")
            return FakeResp(403)

        async def get(self, url, params=None):
            calls.append("lite")
            return FakeResp(200, DDG_LITE_HTML)

    results = asyncio.run(_search_ddg(FakeClient(), "asyncio", 8, ""))
    assert calls == ["html", "lite"]
    assert len(results) == 2
    assert results[0].url == "https://docs.python.org/3/library/asyncio.html"
