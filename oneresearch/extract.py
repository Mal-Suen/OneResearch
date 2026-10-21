# -*- coding: utf-8 -*-
"""正文提取：trafilatura 为主，BeautifulSoup 兜底。"""
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    trafilatura = None
    HAS_TRAFILATURA = False


@dataclass
class PageContent:
    url: str
    title: str = ""
    text: str = ""
    date: str = ""
    chars: int = 0
    final_url: str = ""


def _bs4_fallback(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    title = ""
    if soup.title is not None:
        title = soup.title.get_text(" ", strip=True)
    node = soup.find("article") or soup.find("main") or soup.body or soup
    text = node.get_text("\n", strip=True)
    return title, text


def extract_page(url: str, html: str, final_url: str = "") -> PageContent:
    title, text, date = "", "", ""
    if HAS_TRAFILATURA and html:
        try:
            meta = trafilatura.extract_metadata(html)
            if meta is not None:
                title = (getattr(meta, "title", "") or "").strip()
                date = (getattr(meta, "date", "") or "").strip()
        except Exception:
            pass
        try:
            text = trafilatura.extract(
                html, output_format="txt", include_comments=False,
                include_tables=True, favor_recall=True) or ""
        except Exception:
            text = ""
    if len(text) < 200 or not title:
        fb_title, fb_text = _bs4_fallback(html)
        if not title:
            title = fb_title
        if len(fb_text) > len(text):
            text = fb_text
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return PageContent(url=url, title=title, text=text, date=date, chars=len(text),
                       final_url=final_url or url)
