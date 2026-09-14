import queue
import threading
import uuid

from qdrant_client.models import PointStruct

import checkpoint
import db
import embedder
import qdrant_store

CONTENT_COLLECTION = "content_index"


def _point_id(table, row_id, column):
    """Deterministic id -> re-indexing the same row always overwrites the same
    point instead of creating a duplicate, so a retried/interrupted run is safe."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{table}:{row_id}:{column}"))


def _prefetch_batches(batch_iter, buffer_size=2):
    """Runs db.fetch_batches() on a background thread and hands batches back
    through a bounded queue, so the next MySQL round-trip happens WHILE the
    GPU is still busy embedding the current batch, instead of after it. This
    is what keeps the GPU from idling between batches (fetch/embed/upsert
    was previously fully sequential)."""
    q = queue.Queue(maxsize=buffer_size)
    SENTINEL = object()

    def _producer():
        try:
            for batch in batch_iter:
                q.put(batch)
        finally:
            q.put(SENTINEL)

    threading.Thread(target=_producer, daemon=True).start()

    while True:
        batch = q.get()
        if batch is SENTINEL:
            return
        yield batch


def _index_table(table, id_column, text_column, columns, payload_fn, checkpoint_name, where=None, limit=None):
    last_id = checkpoint.load(checkpoint_name)
    raw_batches = db.fetch_batches(table, columns, id_column=id_column, after_id=last_id, where=where, limit=limit)
    for batch in _prefetch_batches(raw_batches):
        texts, rows_with_text = [], []
        for row in batch:
            text = (row.get(text_column) or "").strip()
            if text:
                texts.append(text)
                rows_with_text.append(row)

        if texts:
            vectors = embedder.embed_passages(texts)
            points = [
                PointStruct(
                    id=_point_id(table, row[id_column], text_column),
                    vector=vector,
                    payload=payload_fn(row, text),
                )
                for row, vector, text in zip(rows_with_text, vectors, texts)
            ]
            qdrant_store.upsert(CONTENT_COLLECTION, points)

        last_id = batch[-1][id_column]
        checkpoint.save(checkpoint_name, last_id)
        print(f"[{table}] indexed up to id={last_id} ({len(texts)}/{len(batch)} had text)")


def index_analyzed_data(limit=None, today_only=False):
    columns = [
        "id", "unique_topic_id", "input_text", "topic_title", "primary_district",
        "broad_category", "sub_category", "sentiment_label",
        "post_bank_core_source", "post_bank_author_username", "created_at",
    ]

    def payload(row, text):
        return {
            "entity_type": "CONTENT",
            "source_table": "analyzed_data",
            "source_column": "input_text",
            "source_id": row["id"],
            "unique_topic_id": row.get("unique_topic_id"),
            "text_content": text,
            "district": row.get("primary_district"),
            "broad_category": row.get("broad_category"),
            "sub_category": row.get("sub_category"),
            "sentiment": row.get("sentiment_label"),
            "platform": row.get("post_bank_core_source"),
            "author": row.get("post_bank_author_username"),
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        }

    where = "created_at >= CURDATE()" if today_only else None
    checkpoint_name = "analyzed_data_today" if today_only else "analyzed_data"
    _index_table("analyzed_data", "id", "input_text", columns, payload, checkpoint_name, where=where, limit=limit)


def index_reply(limit=None, today_only=False):
    columns = [
        "id", "post_bank_id", "reply_text", "reply_author_username",
        "reply_like_count", "reply_created_at",
    ]

    def payload(row, text):
        return {
            "entity_type": "CONTENT",
            "source_table": "reply",
            "source_column": "reply_text",
            "source_id": row["id"],
            "post_bank_id": row.get("post_bank_id"),
            "text_content": text,
            "author": row.get("reply_author_username"),
            "like_count": row.get("reply_like_count"),
            "created_at": row["reply_created_at"].isoformat() if row.get("reply_created_at") else None,
        }

    where = "reply_created_at >= CURDATE()" if today_only else None
    checkpoint_name = "reply_today" if today_only else "reply"
    _index_table("reply", "id", "reply_text", columns, payload, checkpoint_name, where=where, limit=limit)


def index_fb_comments(limit=None, today_only=False):
    columns = ["id", "post_bank_id", "message", "commenter_username", "like_count", "created_time"]

    def payload(row, text):
        return {
            "entity_type": "CONTENT",
            "source_table": "fb_comments",
            "source_column": "message",
            "source_id": row["id"],
            "post_bank_id": row.get("post_bank_id"),
            "text_content": text,
            "author": row.get("commenter_username"),
            "like_count": row.get("like_count"),
            "created_at": row["created_time"].isoformat() if row.get("created_time") else None,
        }

    where = "created_time >= CURDATE()" if today_only else None
    checkpoint_name = "fb_comments_today" if today_only else "fb_comments"
    _index_table("fb_comments", "id", "message", columns, payload, checkpoint_name, where=where, limit=limit)


def index_insta_comments(limit=None, today_only=False):
    columns = ["id", "post_bank_id", "message", "commenter_username", "like_count", "created_time"]

    def payload(row, text):
        return {
            "entity_type": "CONTENT",
            "source_table": "insta_comments",
            "source_column": "message",
            "source_id": row["id"],
            "post_bank_id": row.get("post_bank_id"),
            "text_content": text,
            "author": row.get("commenter_username"),
            "like_count": row.get("like_count"),
            "created_at": row["created_time"].isoformat() if row.get("created_time") else None,
        }

    where = "created_time >= CURDATE()" if today_only else None
    checkpoint_name = "insta_comments_today" if today_only else "insta_comments"
    _index_table("insta_comments", "id", "message", columns, payload, checkpoint_name, where=where, limit=limit)


def index_topic(limit=None):
    columns = ["id", "unique_topic_id", "topic_title"]
    
    def payload(row, text):
        return {
            "entity_type": "INCIDENT",
            "source_table": "topic",
            "source_column": "topic_title",
            "source_id": row["id"],
            "unique_topic_id": row.get("unique_topic_id"),
            "text_content": text,
        }

    _index_table("topic", "id", "topic_title", columns, payload, "topic", limit=limit)


def index_district_internal_report(limit=None):
    columns = ["id", "unique_topic_id", "incident_description", "crime_type", "district", "thana"]

    def payload(row, text):
        return {
            "entity_type": "REPORT",
            "source_table": "district_internal_report",
            "source_column": "incident_description",
            "source_id": row["id"],
            "unique_topic_id": row.get("unique_topic_id"),
            "text_content": text,
            "crime_type": row.get("crime_type"),
            "district": row.get("district"),
            "thana": row.get("thana"),
        }

    _index_table("district_internal_report", "id", "incident_description", columns, payload, "district_internal_report", limit=limit)


def index_keywords(limit=None):
    columns = ["id", "english_keyword", "hindi_keyword", "hinglish_keyword"]
    
    def payload(row, text):
        return {
            "entity_type": "TAXONOMY",
            "source_table": "keywords",
            "source_column": "english_keyword",
            "source_id": row["id"],
            "text_content": text,
            "hindi_keyword": row.get("hindi_keyword"),
            "hinglish_keyword": row.get("hinglish_keyword"),
        }

    _index_table("keywords", "id", "english_keyword", columns, payload, "keywords", limit=limit)


def index_hashtags(limit=None):
    columns = ["id", "hashtag_keyword", "hashtag_hindi_keyword"]

    def payload(row, text):
        return {
            "entity_type": "TAXONOMY",
            "source_table": "hashtags",
            "source_column": "hashtag_keyword",
            "source_id": row["id"],
            "text_content": text,
            "hashtag_hindi_keyword": row.get("hashtag_hindi_keyword"),
        }

    _index_table("hashtags", "id", "hashtag_keyword", columns, payload, "hashtags", limit=limit)
