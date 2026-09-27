"""Convert Zendesk article HTML into clean Markdown.

The help-center HTML is WYSIWYG output, so a plain html->md pass gives noisy results.
Before handing it to markdownify we normalise a few patterns found across the corpus:

* One-column tables (~330 of them) are "IMPORTANT"/"NOTE" callout boxes -> blockquotes.
* Multi-column tables holding images/lists are side-by-side layouts -> flattened.
* Only real data tables stay as Markdown tables.
* <iframe> embeds (YouTube, Canva) -> plain links, which a text-only bot can still cite.
* Protocol-relative / root-relative URLs -> absolute, so links work outside the site.
* Named anchors are kept as <a id> so in-page "#section" links keep working.
* Inline base64 images and styling wrappers (<span>, <u>, <font>) are dropped.
"""

import html
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from markdownify import MarkdownConverter

from scraper import Article

BLOCK_TAGS = ["p", "ul", "ol", "img", "h1", "h2", "h3", "h4", "pre", "figure", "div", "table"]

# Anchor names contain "_", "&", "%"... which markdownify would escape, so anchors are
# replaced by a numbered placeholder and swapped back for raw HTML after conversion.
_ANCHOR_TOKEN = "ANCHORREF{}END"
_ANCHOR_RE = re.compile(r"ANCHORREF(\d+)END")


def article_to_markdown(article: Article, base_url: str) -> str:
    body = html_to_markdown(article.body_html, base_url)
    return f"# {article.title}\n\nArticle URL: {article.url}\n\n{body}\n"


def html_to_markdown(source: str, base_url: str) -> str:
    soup = BeautifulSoup(source, "html.parser")
    anchors = _clean(soup, base_url)
    md = _Converter(
        heading_style="ATX",
        bullets="-",
        strip=["span", "u", "font"],
        code_language_callback=_code_language,
        table_infer_header=True,
    ).convert_soup(soup)
    md = _ANCHOR_RE.sub(lambda m: f'<a id="{html.escape(anchors[int(m.group(1))])}"></a>', md)
    return _tidy(md)


def _clean(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Normalise the soup in place; returns the anchor names referenced by placeholders."""
    for tag in soup(["script", "style", "noscript", "button", "form"]):
        tag.decompose()

    # Inline base64 images (one article carries 125 KB of them) are pure noise for retrieval.
    for img in soup.find_all("img", src=re.compile(r"^data:")):
        img.decompose()

    # <a name="X"></a> are targets of the in-page "#X" links; keep them as bare anchors
    # so relative links still resolve when the Markdown is rendered.
    anchors: list[str] = []
    for a in soup.find_all("a"):
        if a.get("href") or a.get_text(strip=True):
            continue
        target = a.get("name") or a.get("id")
        if target:
            a.replace_with(_ANCHOR_TOKEN.format(len(anchors)))
            anchors.append(target)
        else:
            a.decompose()

    for tag in soup.find_all(["a", "img", "iframe"]):
        for attr in ("href", "src"):
            if tag.get(attr):
                tag[attr] = _absolute_url(tag[attr], base_url)

    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        link = soup.new_tag("a", href=src)
        link.string = "Embedded video" if "youtube" in src else "Embedded content"
        wrapper = soup.new_tag("p")
        wrapper.append(link)
        iframe.replace_with(wrapper)

    # Innermost tables first, so nested layout tables are unwrapped bottom-up.
    for table in reversed(soup.find_all("table")):
        _normalise_table(soup, table)

    return anchors


def _normalise_table(soup: BeautifulSoup, table: Tag) -> None:
    rows = table.find_all("tr")
    cells = [row.find_all(["td", "th"], recursive=False) for row in rows]
    max_cols = max((len(c) for c in cells), default=0)

    if max_cols <= 1:
        quote = soup.new_tag("blockquote")
        for row_cells in cells:
            for cell in row_cells:
                _move_children(soup, cell, quote)
        table.replace_with(quote)
    elif table.find(BLOCK_TAGS):
        # With a header row the table is a side-by-side comparison ("English | Japanese"),
        # so read it column by column to keep each header next to its content.
        if table.find("th"):
            cells = [[row[i] for row in cells if i < len(row)] for i in range(max_cols)]
        container = soup.new_tag("div")
        for group in cells:
            for cell in group:
                _move_children(soup, cell, container)
        table.replace_with(container)
    # else: a genuine data table, left for markdownify's table support.


def _move_children(soup: BeautifulSoup, cell: Tag, target: Tag) -> None:
    """Move a cell's content into target, wrapping bare inline content in a <p>."""
    if not cell.get_text(strip=True) and not cell.find("img"):
        return
    if cell.find(BLOCK_TAGS, recursive=False):
        for child in list(cell.children):
            target.append(child.extract())
    else:
        p = soup.new_tag("p")
        for child in list(cell.children):
            p.append(child.extract())
        target.append(p)


def _absolute_url(url: str, base_url: str) -> str:
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urljoin(base_url, url)
    return url


def _code_language(el: Tag) -> str:
    code = el.find("code")
    classes = (code.get("class") if code else None) or el.get("class") or []
    for cls in classes:
        if cls.startswith("language-") and cls != "language-auto":
            return cls.removeprefix("language-")
    return ""


def _tidy(md: str) -> str:
    md = md.replace(" ", " ")
    md = re.sub(r"[ \t]+\n", "\n", md)  # trailing whitespace
    md = re.sub(r"\n{3,}", "\n\n", md)  # runs of blank lines
    md = re.sub(r"(^|\n\n)(>[ \t]*\n)+", r"\1", md)  # empty lines opening a callout quote
    md = re.sub(r"(\n>[ \t]*)+(\n\n|$)", r"\2", md)  # ...and closing one
    return md.strip()


class _Converter(MarkdownConverter):
    def convert_img(self, el, text, parent_tags):
        alt = (el.get("alt") or "").strip()
        src = el.get("src") or ""
        if not src:
            return ""
        # Images inside headings/tables are kept inline; elsewhere give them their own line.
        md = f"![{alt}]({src})"
        return md if "_inline" in parent_tags else f"\n\n{md}\n\n"

    def convert_hr(self, el, text, parent_tags):
        # Zendesk uses <hr> purely as a visual separator between sections that already have headings.
        return "\n\n"
