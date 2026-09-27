"""Decide what changed between the freshly scraped articles and what is in the File Search store.

Pure logic, no I/O, so it is easy to test. The store itself is the source of truth:
every uploaded chunk document carries `article_id` and `content_hash` attributes, so the job needs no
extra database and a fresh container on the scheduler knows exactly what was uploaded before.
"""

import hashlib
from dataclasses import dataclass, field


def content_hash(markdown: str) -> str:
    # Hashing the converted Markdown (not Zendesk's updated_at) also re-uploads articles when
    # the converter/chunker output changes, and ignores edits that don't change the content.
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


@dataclass
class RemoteArticle:
    content_hash: str
    file_ids: list[str] = field(default_factory=list)


@dataclass
class SyncPlan:
    added: list[str] = field(default_factory=list)  # article ids
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)  # in the store, no longer on the site

    def summary(self) -> dict[str, int]:
        return {k: len(v) for k, v in vars(self).items()}


def plan_sync(local_hashes: dict[str, str], remote: dict[str, RemoteArticle], prune: bool = True) -> SyncPlan:
    plan = SyncPlan()
    for article_id, digest in local_hashes.items():
        existing = remote.get(article_id)
        if existing is None:
            plan.added.append(article_id)
        elif existing.content_hash != digest:
            plan.updated.append(article_id)
        else:
            plan.skipped.append(article_id)

    if prune:
        plan.removed = [aid for aid in remote if aid not in local_hashes]
    return plan
