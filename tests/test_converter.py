from converter import article_to_markdown, html_to_markdown
from scraper import Article

BASE = "https://support.optisigns.com"


def md(html: str) -> str:
    return html_to_markdown(html, BASE)


def test_article_header_has_title_and_url():
    article = Article("1", "Add a Video", f"{BASE}/hc/en-us/articles/1-Add-a-Video", "2026-01-01T00:00:00Z", "<p>Hi</p>")
    out = article_to_markdown(article, BASE)
    assert out.startswith("# Add a Video\n\nArticle URL: https://support.optisigns.com/hc/en-us/articles/1-Add-a-Video\n")


def test_headings_lists_and_inline_styles():
    out = md('<h2><span style="color:red">Setup</span></h2><ul><li><u>One</u></li><li><strong>Two</strong></li></ul>')
    assert out == "## Setup\n\n- One\n- **Two**"


def test_single_column_table_becomes_callout_quote():
    out = md("<table><tr><td><p><strong>NOTE</strong></p></td></tr><tr><td>Restart the player.</td></tr></table>")
    assert out == "> **NOTE**\n>\n> Restart the player."


def test_layout_table_with_header_is_read_column_by_column():
    out = md(
        "<table><thead><tr><th>English</th><th>Japanese</th></tr></thead>"
        '<tbody><tr><td><img src="/a.png" alt="en"></td><td><img src="/b.png" alt="ja"></td></tr></tbody></table>'
    )
    assert out.index("English") < out.index("![en]") < out.index("Japanese") < out.index("![ja]")
    assert "|" not in out


def test_data_table_stays_a_markdown_table():
    out = md("<table><tr><th>Key</th><th>Value</th></tr><tr><td>a</td><td>1</td></tr></table>")
    assert "| Key | Value |" in out and "| a | 1 |" in out


def test_code_block_is_fenced_and_unescaped():
    out = md('<pre class="wysiwyg-code-block"><code class="language-auto">curl "x?a=1&amp;b=2"\n</code></pre>')
    assert out == '```\ncurl "x?a=1&b=2"\n```'


def test_urls_are_made_absolute():
    out = md('<p><a href="/hc/en-us/articles/2">see</a> <img src="//cdn.example.com/i.png" alt="x"></p>')
    assert "(https://support.optisigns.com/hc/en-us/articles/2)" in out
    assert "(https://cdn.example.com/i.png)" in out


def test_in_page_anchor_links_keep_their_targets():
    out = md('<p><a href="#Step_1">Go</a></p><p><a name="Step_1"></a></p><h2>Step 1</h2>')
    assert "[Go](#Step_1)" in out
    assert '<a id="Step_1"></a>' in out


def test_iframe_becomes_link():
    out = md('<iframe src="//www.youtube-nocookie.com/embed/abc"></iframe>')
    assert out == "[Embedded video](https://www.youtube-nocookie.com/embed/abc)"


def test_noise_is_removed():
    out = md('<script>x()</script><p>Text<img src="data:image/png;base64,AAAA"></p><a name="empty"></a>')
    assert "x()" not in out and "base64" not in out
    assert out.startswith("Text")
