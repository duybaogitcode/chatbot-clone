"""Gemini File Search store I/O: read current state, upload chunk documents, delete stale ones."""

import io
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from google import genai
from google.genai import errors

from sync import RemoteArticle

log = logging.getLogger(__name__)

# Gemini caps chunks at 512 tokens; our chunks are pre-split well below that, so each document
# is indexed as exactly one chunk.
CHUNKING_CONFIG = {"white_space_config": {"max_tokens_per_chunk": 512, "max_overlap_tokens": 0}}
WORKERS = 10  # indexing is mostly waiting on Google; 429s are retried with backoff
MAX_RETRIES = 6


@dataclass(frozen=True)
class ChunkFile:
    filename: str
    text: str
    attributes: dict[str, str | int]


@dataclass
class UploadResult:
    completed: int = 0
    failed: int = 0


class FileSearchStore:
    def __init__(self, client: genai.Client, store_name: str):
        self.client = client
        self.name = store_name  # "fileSearchStores/<id>"

    @classmethod
    def open(cls, client: genai.Client, display_name: str, store_id: str | None = None) -> "FileSearchStore":
        if store_id:
            return cls(client, client.file_search_stores.get(name=store_id).name)
        for store in client.file_search_stores.list():
            if store.display_name == display_name:
                log.info("Using file search store %s", display_name)
                return cls(client, store.name)
        store = client.file_search_stores.create(config={"display_name": display_name})
        log.info("Created file search store %s (%s) - put this in STORE_ID", display_name, store.name)
        return cls(client, store.name)

    def remote_articles(self) -> dict[str, RemoteArticle]:
        """Group the store's documents by the article they belong to."""
        articles: dict[str, RemoteArticle] = {}
        expected: dict[str, int] = {}
        for doc in self.client.file_search_stores.documents.list(parent=self.name):
            meta = {m.key: m.string_value if m.string_value is not None else m.numeric_value for m in doc.custom_metadata or []}
            article_id = meta.get("article_id")
            if not article_id:
                continue
            article_id = str(article_id)
            # A chunk that failed to index marks its article as changed, so the next run retries it.
            digest = str(meta.get("content_hash", "")) if "FAILED" not in str(doc.state) else ""
            entry = articles.setdefault(article_id, RemoteArticle(content_hash=digest))
            if entry.content_hash != digest:
                entry.content_hash = ""
            entry.file_ids.append(doc.name)
            expected[article_id] = int(meta.get("chunk_count") or 0)
        # A run cut short (e.g. daily quota) can leave an article with only some chunks: re-upload it.
        for article_id, entry in articles.items():
            if len(entry.file_ids) != expected[article_id]:
                entry.content_hash = ""
        return articles

    def upload(self, chunks: list[ChunkFile]) -> UploadResult:
        result = UploadResult()
        if not chunks:
            return result
        log.info("Uploading %d chunk documents...", len(chunks))
        with ThreadPoolExecutor(WORKERS) as pool:
            for i, ok in enumerate(pool.map(self._upload_one, chunks), start=1):
                if ok:
                    result.completed += 1
                else:
                    result.failed += 1
                if i % 100 == 0:
                    log.info("  %d/%d indexed (%d failed)", i, len(chunks), result.failed)
        return result

    def delete(self, document_names: list[str]) -> None:
        with ThreadPoolExecutor(WORKERS) as pool:
            list(pool.map(self._delete_one, document_names))

    def _upload_one(self, chunk: ChunkFile) -> bool:
        config = {
            "display_name": chunk.filename,
            "mime_type": "text/markdown",
            "custom_metadata": [
                {"key": k, "numeric_value": v} if isinstance(v, int) else {"key": k, "string_value": v}
                for k, v in chunk.attributes.items()
            ],
            "chunking_config": CHUNKING_CONFIG,
        }
        try:
            op = _with_retry(lambda: self.client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=self.name, file=io.BytesIO(chunk.text.encode("utf-8")), config=config))
            while not op.done:
                time.sleep(1)
                op = _with_retry(lambda: self.client.operations.get(op))
        except errors.APIError as e:
            log.warning("Upload failed for %s: %s", chunk.filename, e)
            return False
        if op.error:
            log.warning("Indexing failed for %s: %s", chunk.filename, op.error)
            return False
        return True

    def _delete_one(self, document_name: str) -> None:
        _with_retry(lambda: self.client.file_search_stores.documents.delete(name=document_name, config={"force": True}))


def _with_retry(call):
    """Retry rate-limit (429) and transient server errors with exponential backoff."""
    for attempt in range(MAX_RETRIES):
        try:
            return call()
        except errors.APIError as e:
            if e.code not in (429, 500, 503) or attempt == MAX_RETRIES - 1:
                raise
            wait = min(60, 2 ** (attempt + 1))
            log.info("API %s, retrying in %ds", e.code, wait)
            time.sleep(wait)
