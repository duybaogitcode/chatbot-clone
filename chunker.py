"""Split an article's Markdown into heading-aware chunks for the Gemini File Search store.

Why chunk ourselves instead of letting File Search's auto-chunker do it:

* The system prompt asks the bot to cite "Article URL:" lines. With automatic chunking only
  the first chunk of a file contains that line, so answers built from later chunks could not
  cite a URL. Every chunk here starts with the article URL, title and section path.
* Splitting on headings keeps each chunk about one topic ("Playback options"), instead of
  cutting mid-step at a fixed token count.
* Each chunk is uploaded as its own file, below the store's chunk size, so Gemini indexes it
  as exactly one chunk and the "chunks embedded" count in the logs is exact.
"""

import re
from dataclasses import dataclass

import tiktoken

MAX_TOKENS = 350  # cap per chunk body; + ~60-token header stays under Gemini's 512-token chunk limit,
# with margin because tiktoken only approximates Gemini's tokenizer
MIN_TOKENS = 120  # smaller sections are merged with the next one

_encoding = tiktoken.get_encoding("o200k_base")
_HEADING_RE = re.compile(r"^(#{2,4}) +(.+)$")


@dataclass(frozen=True)
class Chunk:
    index: int
    section: str
    text: str


def count_tokens(text: str) -> int:
    return len(_encoding.encode(text))


def chunk_markdown(markdown: str, title: str, url: str) -> list[Chunk]:
    sections = _split_sections(_for_embedding(markdown))

    # Merge tiny sections forward so chunks are not just a heading and one sentence.
    merged: list[tuple[str, str]] = []
    for path, body in sections:
        if merged and count_tokens(merged[-1][1]) < MIN_TOKENS:
            prev_path, prev_body = merged[-1]
            if count_tokens(prev_body + body) <= MAX_TOKENS:
                merged[-1] = (prev_path, f"{prev_body}\n\n{body}")
                continue
        merged.append((path, body))

    pieces = [(path, part) for path, body in merged for part in _split_long(body)]

    chunks = []
    for i, (path, body) in enumerate(pieces):
        header = f"Article URL: {url}\nArticle: {title}\n"
        if path:
            header += f"Section: {path}\n"
        chunks.append(Chunk(index=i, section=path, text=f"{header}\n{body.strip()}\n"))
    return chunks


def _for_embedding(markdown: str) -> str:
    """Drop what helps a human reader but only dilutes embeddings."""
    md = re.sub(r'<a id="[^"]*"></a>\n*', "", markdown)
    md = re.sub(r"\[([^\]]+)\]\(#[^)]*\)", r"\1", md)  # in-page links mean nothing out of context
    md = re.sub(r"!\[([^\]]*)\]\([^)]*\)", lambda m: f"(Image: {m.group(1)})" if m.group(1) else "", md)
    md = re.sub(r"^# .*\n+(Article URL: .*\n+)?", "", md)  # title + URL go into every chunk header
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def _split_sections(markdown: str) -> list[tuple[str, str]]:
    """Return (heading path, section text) pairs, e.g. ("Add a video > Shorts", "...")."""
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    lines: list[str] = []
    in_code = False

    def flush():
        body = "\n".join(lines).strip()
        if body:
            sections.append((" > ".join(h for _, h in stack), body))
        lines.clear()

    for line in markdown.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
        match = None if in_code else _HEADING_RE.match(line)
        if match:
            flush()
            level, heading = len(match.group(1)), match.group(2).strip(" *")
            stack[:] = [(lvl, h) for lvl, h in stack if lvl < level] + [(level, heading)]
        lines.append(line)
    flush()
    return sections


def _split_long(body: str) -> list[str]:
    """Split an oversized section on paragraph boundaries (never inside a code block)."""
    if count_tokens(body) <= MAX_TOKENS:
        return [body]

    parts, current = [], ""
    for block in _paragraphs(body):
        candidate = f"{current}\n\n{block}" if current else block
        if current and count_tokens(candidate) > MAX_TOKENS:
            parts.append(current)
            current = block
        else:
            current = candidate
    if current:
        parts.append(current)

    # A single paragraph can still be over the cap; hard-split it by tokens as a last resort.
    result = []
    for part in parts:
        tokens = _encoding.encode(part)
        result += [_encoding.decode(tokens[i : i + MAX_TOKENS]) for i in range(0, len(tokens), MAX_TOKENS)]
    return result


def _paragraphs(body: str) -> list[str]:
    blocks, current, in_code = [], [], False
    for line in body.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
        if not line.strip() and not in_code:
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks
