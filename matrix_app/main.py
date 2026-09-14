import argparse

from qdrant_client.models import PayloadSchemaType

import indexers
import qdrant_store

FIELD_INDEXES = {
    "entity_type": PayloadSchemaType.KEYWORD,
    "source_table": PayloadSchemaType.KEYWORD,
    "unique_topic_id": PayloadSchemaType.KEYWORD,
    "post_bank_id": PayloadSchemaType.INTEGER,
    "district": PayloadSchemaType.KEYWORD,
    "sub_category": PayloadSchemaType.KEYWORD,
    "broad_category": PayloadSchemaType.KEYWORD,
    "platform": PayloadSchemaType.KEYWORD,
    "sentiment": PayloadSchemaType.KEYWORD,
    "created_at": PayloadSchemaType.DATETIME,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only index this many rows per table (for a quick test run instead of the full backfill)",
    )
    parser.add_argument(
        "--today", action="store_true",
        help="First index only rows created today (separate checkpoint, so today's data "
             "is searchable fast), then continue the normal historical backfill in the same run.",
    )
    args = parser.parse_args()

    qdrant_store.ensure_collection(indexers.CONTENT_COLLECTION)
    qdrant_store.ensure_indexes(indexers.CONTENT_COLLECTION, FIELD_INDEXES)

    if args.today:
        print("=== Indexing today's rows first ===")
        indexers.index_analyzed_data(limit=args.limit, today_only=True)
        indexers.index_reply(limit=args.limit, today_only=True)
        indexers.index_fb_comments(limit=args.limit, today_only=True)
        indexers.index_insta_comments(limit=args.limit, today_only=True)
        print("=== Today's rows done. Continuing historical backfill ===")

    indexers.index_analyzed_data(limit=args.limit)
    indexers.index_reply(limit=args.limit)
    indexers.index_fb_comments(limit=args.limit)
    indexers.index_insta_comments(limit=args.limit)
    
    # New tables for God-Mode Graph
    indexers.index_topic(limit=args.limit)
    indexers.index_district_internal_report(limit=args.limit)
    indexers.index_keywords(limit=args.limit)
    indexers.index_hashtags(limit=args.limit)


if __name__ == "__main__":
    main()
