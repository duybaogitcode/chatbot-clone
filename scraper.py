"""Fetch articles from the Zendesk Help Center API behind support.optisigns.com."""

import logging
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    url: str
    updated_at: str
    body_html: str

    @property
    def slug(self) -> str:
        # html_url ends in "<id>-<Title-Words>"; the id prefix keeps it unique.
        return self.url.rstrip("/").rsplit("/", 1)[-1].lower()


def fetch_articles(base_url: str, locale: str, limit: int | None = None) -> list[Article]:
    url = f"{base_url}/api/v2/help_center/{locale}/articles.json?per_page=100&sort_by=updated_at"
    articles: list[Article] = []
    session = requests.Session()

    while url:
        data = _get_json(session, url)
        for raw in data["articles"]:
            if raw.get("draft") or not raw.get("body"):
                continue
            articles.append(
                Article(
                    id=str(raw["id"]),
                    title=raw["title"].strip(),
                    url=raw["html_url"],
                    updated_at=raw["updated_at"],
                    body_html=raw["body"],
                )
            )
            if limit and len(articles) >= limit:
                return articles
        url = data.get("next_page")

    log.info("Fetched %d articles from %s", len(articles), base_url)
    return articles


def _get_json(session: requests.Session, url: str, retries: int = 3) -> dict:
    for attempt in range(1, retries + 1):
        resp = session.get(url, timeout=30)
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = int(resp.headers.get("Retry-After", 2 * attempt))
            log.warning("GET %s -> %d, retrying in %ds", url, resp.status_code, wait)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return resp.json()
