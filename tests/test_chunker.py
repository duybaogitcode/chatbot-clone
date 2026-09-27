from chunker import MAX_TOKENS, chunk_markdown, count_tokens

URL = "https://support.optisigns.com/hc/en-us/articles/1-Test"


def doc(body: str) -> str:
    return f"# Test\n\nArticle URL: {URL}\n\n{body}"


def test_every_chunk_starts_with_article_url():
    body = "\n\n".join(f"## Section {i}\n\n" + "word " * 200 for i in range(5))
    chunks = chunk_markdown(doc(body), "Test", URL)
    assert len(chunks) > 1
    assert all(c.text.startswith(f"Article URL: {URL}\nArticle: Test\n") for c in chunks)


def test_section_path_follows_heading_nesting():
    body = "## Setup\n\n" + "a " * 150 + "\n\n### Wi-Fi\n\n" + "b " * 150 + "\n\n## Other\n\n" + "c " * 150
    sections = [c.section for c in chunk_markdown(doc(body), "Test", URL)]
    assert sections == ["Setup", "Setup > Wi-Fi", "Other"]


def test_small_sections_are_merged():
    body = "## A\n\nshort\n\n## B\n\nalso short"
    chunks = chunk_markdown(doc(body), "Test", URL)
    assert len(chunks) == 1 and "## B" in chunks[0].text


def test_long_sections_are_split_under_the_cap():
    body = "## Big\n\n" + "\n\n".join("sentence " * 80 for _ in range(20))
    chunks = chunk_markdown(doc(body), "Test", URL)
    assert len(chunks) > 1
    assert all(count_tokens(c.text) <= MAX_TOKENS + 60 for c in chunks)  # + header


def test_headings_inside_code_blocks_are_not_split_on():
    body = "## Script\n\n```\n## not a heading\necho hi\n```"
    chunks = chunk_markdown(doc(body), "Test", URL)
    assert len(chunks) == 1 and "## not a heading" in chunks[0].text


def test_images_become_alt_text_and_anchors_are_dropped():
    body = '<a id="x"></a>\n\n## Step\n\n![Apps button](https://x/1.png) and [jump](#x)'
    text = chunk_markdown(doc(body), "Test", URL)[0].text
    assert "(Image: Apps button)" in text and "https://x/1.png" not in text
    assert "<a id" not in text and "jump" in text and "(#x)" not in text
