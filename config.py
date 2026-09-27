"""Runtime configuration, read from environment variables (and .env for local runs)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    api_key: str
    help_center_url: str
    locale: str
    store_name: str
    store_id: str | None
    model: str
    articles_dir: str
    max_articles: int | None
    dry_run: bool


def load_config() -> Config:
    max_articles = os.getenv("MAX_ARTICLES")
    return Config(
        # The brief runs the container with `-e API_KEY=...` (a Gemini API key); GEMINI_API_KEY works too.
        api_key=os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "",
        help_center_url=os.getenv("HELP_CENTER_URL", "https://support.optisigns.com"),
        locale=os.getenv("HELP_CENTER_LOCALE", "en-us"),
        store_name=os.getenv("STORE_NAME", "optibot-kb"),
        store_id=os.getenv("STORE_ID") or None,
        model=os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
        articles_dir=os.getenv("ARTICLES_DIR", "articles"),
        max_articles=int(max_articles) if max_articles else None,
        dry_run=os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes"),
    )
