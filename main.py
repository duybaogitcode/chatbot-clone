"""Scrape support.optisigns.com -> Markdown -> Gemini File Search store, uploading only the delta.

Runs once and exits: 0 on success, 1 if anything failed (so the scheduler flags the run).
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from google import genai

from chunker import chunk_markdown
from config import Config, load_config
from converter import article_to_markdown
from scraper import Article, fetch_articles
from sync import content_hash, plan_sync
from uploader import ChunkFile, FileSearchStore

log = logging.getLogger("optibot")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    for noisy in ("httpx", "httpx2", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg = load_config()
    started = time.monotonic()

    articles = fetch_articles(cfg.help_center_url, cfg.locale, limit=cfg.max_articles)
    markdown = {a.id: article_to_markdown(a, cfg.help_center_url) for a in articles}
    write_markdown(cfg.articles_dir, articles, markdown, prune=cfg.max_articles is None)
    log.info("Scraped %d articles -> %s/", len(articles), cfg.articles_dir)

    if cfg.dry_run:
        log.info("DRY_RUN set: skipping upload")
        return 0
    if not cfg.api_key:
        log.error("API_KEY (or GEMINI_API_KEY) is not set")
        return 1

    store = FileSearchStore.open(genai.Client(api_key=cfg.api_key), cfg.store_name, cfg.store_id)
    remote = store.remote_articles()
    hashes = {aid: content_hash(md) for aid, md in markdown.items()}
    # A partial scrape (MAX_ARTICLES) must not delete the articles it didn't fetch.
    plan = plan_sync(hashes, remote, prune=cfg.max_articles is None)

    by_id = {a.id: a for a in articles}
    to_upload = [
        chunk_file
        for aid in plan.added + plan.updated
        for chunk_file in build_chunk_files(by_id[aid], markdown[aid], hashes[aid])
    ]
    upload = store.upload(to_upload)

    # Replace, not patch: old chunks are removed only after the new ones are in the store.
    stale = [fid for aid in plan.updated + plan.removed for fid in remote[aid].file_ids]
    store.delete(stale)

    report = {
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_s": round(time.monotonic() - started, 1),
        "articles_scraped": len(articles),
        **plan.summary(),
        "files_uploaded": len(to_upload),
        "chunks_embedded": upload.completed,
        "chunks_failed": upload.failed,
        "stale_files_deleted": len(stale),
    }
    log.info("Run summary: %s", json.dumps(report))
    with open(os.path.join(cfg.articles_dir, "last_run.json"), "w") as fh:
        json.dump(report, fh, indent=2)

    return 1 if upload.failed else 0


def write_markdown(directory: str, articles: list[Article], markdown: dict[str, str], prune: bool) -> None:
    os.makedirs(directory, exist_ok=True)
    wanted = {f"{a.slug}.md" for a in articles}
    for article in articles:
        with open(os.path.join(directory, f"{article.slug}.md"), "w", encoding="utf-8") as fh:
            fh.write(markdown[article.id])
    if prune:  # drop files of articles that were unpublished or renamed
        for name in os.listdir(directory):
            if name.endswith(".md") and name not in wanted:
                os.remove(os.path.join(directory, name))


def build_chunk_files(article: Article, markdown: str, digest: str) -> list[ChunkFile]:
    chunks = chunk_markdown(markdown, article.title, article.url)
    return [
        ChunkFile(
            filename=f"{article.slug}--{chunk.index:02d}.md",
            text=chunk.text,
            attributes={
                "article_id": article.id,
                "content_hash": digest,
                "chunk_index": chunk.index,
                "chunk_count": len(chunks),
                "url": article.url,
                "updated_at": article.updated_at,
            },
        )
        for chunk in chunks
    ]


if __name__ == "__main__":
    sys.exit(main())
