from types import SimpleNamespace

from sync import RemoteArticle, content_hash, plan_sync
from uploader import FileSearchStore


def test_plan_classifies_added_updated_skipped_removed():
    local = {"1": "h1", "2": "h2-new", "3": "h3"}
    remote = {"2": RemoteArticle("h2-old", ["f2"]), "3": RemoteArticle("h3", ["f3"]), "9": RemoteArticle("h9", ["f9"])}
    plan = plan_sync(local, remote)
    assert plan.summary() == {"added": 1, "updated": 1, "skipped": 1, "removed": 1}
    assert (plan.added, plan.updated, plan.skipped, plan.removed) == (["1"], ["2"], ["3"], ["9"])


def test_partial_scrape_does_not_remove():
    plan = plan_sync({"1": "h"}, {"9": RemoteArticle("h9", ["f9"])}, prune=False)
    assert plan.removed == []


def test_content_hash_is_stable_and_content_sensitive():
    assert content_hash("a") == content_hash("a") != content_hash("b")


def _doc(name, article_id, digest, count=2, state="STATE_ACTIVE"):
    meta = [
        SimpleNamespace(key="article_id", string_value=article_id, numeric_value=None),
        SimpleNamespace(key="content_hash", string_value=digest, numeric_value=None),
        SimpleNamespace(key="chunk_count", string_value=None, numeric_value=count),
    ]
    return SimpleNamespace(name=name, state=state, custom_metadata=meta)


def _store(docs):
    documents = SimpleNamespace(list=lambda **_: docs)
    client = SimpleNamespace(file_search_stores=SimpleNamespace(documents=documents))
    return FileSearchStore(client, "fileSearchStores/test")


def test_remote_articles_groups_chunks_by_article():
    remote = _store([_doc("d1", "1", "h"), _doc("d2", "1", "h"), _doc("d3", "2", "k", count=1)]).remote_articles()
    assert remote["1"].file_ids == ["d1", "d2"] and remote["1"].content_hash == "h"
    assert remote["2"].content_hash == "k"


def test_failed_chunk_forces_article_update():
    remote = _store([_doc("d1", "1", "h"), _doc("d2", "1", "h", state="STATE_FAILED")]).remote_articles()
    assert plan_sync({"1": "h"}, remote).updated == ["1"]


def test_partially_uploaded_article_is_uploaded_again():
    remote = _store([_doc("d1", "1", "h", count=3)]).remote_articles()  # 1 of 3 chunks made it
    assert plan_sync({"1": "h"}, remote).updated == ["1"]
