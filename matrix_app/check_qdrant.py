"""
check_qdrant.py
───────────────
Connects to LOCAL Qdrant (localhost:6333) and inspects the content_index
to show: collection stats, payload schema, and sample records from each source_table.
"""

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
import json

# ── Connect to LOCAL Qdrant ─────────────────────────────────────────────────
client = QdrantClient(host="localhost", port=6333)
COLLECTION = "content_index"

print("=" * 60)
print("  QDRANT INSPECTOR  →  localhost:6333")
print("=" * 60)

# ── 1. List all collections ─────────────────────────────────────────────────
print("\n📦 COLLECTIONS FOUND:")
collections = client.get_collections().collections
for c in collections:
    print(f"   • {c.name}")

if COLLECTION not in [c.name for c in collections]:
    print(f"\n❌ '{COLLECTION}' NOT FOUND. Is the collection name correct?")
    exit(1)

# ── 2. Collection Info ──────────────────────────────────────────────────────
info = client.get_collection(COLLECTION)
print(f"\n📊 COLLECTION: {COLLECTION}")
print(f"   Total Points (Vectors) : {info.points_count:,}")
print(f"   Vector Size            : {info.config.params.vectors.size}")
print(f"   Distance Metric        : {info.config.params.vectors.distance}")
print(f"   Status                 : {info.status}")

# ── 3. Check each source_table ──────────────────────────────────────────────
SOURCE_TABLES = ["analyzed_data", "reply", "fb_comments", "insta_comments"]

print("\n📂 BREAKDOWN BY source_table:")
for table in SOURCE_TABLES:
    result = client.count(
        collection_name=COLLECTION,
        count_filter=Filter(
            must=[FieldCondition(key="source_table", match=MatchValue(value=table))]
        ),
        exact=True,
    )
    print(f"   • {table:<25} : {result.count:>10,} vectors")

# ── 4. Sample 1 record from each source_table ──────────────────────────────
print("\n🔍 SAMPLE PAYLOAD FROM EACH SOURCE TABLE:")
for table in SOURCE_TABLES:
    results = client.scroll(
        collection_name=COLLECTION,
        scroll_filter=Filter(
            must=[FieldCondition(key="source_table", match=MatchValue(value=table))]
        ),
        limit=1,
        with_payload=True,
        with_vectors=False,
    )
    points = results[0]
    if points:
        print(f"\n   ─── {table} ───")
        payload = points[0].payload
        for k, v in payload.items():
            val_str = str(v)[:80] + "…" if len(str(v)) > 80 else str(v)
            print(f"     {k:<30}: {val_str}")
    else:
        print(f"\n   ─── {table} : NO DATA FOUND ───")

# ── 5. Check payload field completeness ────────────────────────────────────
print("\n✅ PAYLOAD FIELD COMPLETENESS CHECK (analyzed_data):")
EXPECTED_FIELDS = [
    "source_table", "source_id", "unique_topic_id", "text_content",
    "district", "broad_category", "sub_category", "sentiment",
    "platform", "author", "created_at"
]

sample = client.scroll(
    collection_name=COLLECTION,
    scroll_filter=Filter(
        must=[FieldCondition(key="source_table", match=MatchValue(value="analyzed_data"))]
    ),
    limit=5,
    with_payload=True,
    with_vectors=False,
)[0]

for field in EXPECTED_FIELDS:
    present = sum(1 for p in sample if field in p.payload and p.payload[field] is not None)
    print(f"   {'✓' if present > 0 else '✗'} {field:<30} : {present}/{len(sample)} samples have it")

print("\n\n✅ Inspection complete!")
