import sys

from qdrant_client.models import FieldCondition, Filter, MatchValue

import embedder
import indexers
import qdrant_store


def search(query_text, top_k=10, source_table=None):
    vector = embedder.embed_query(query_text)
    query_filter = None
    if source_table:
        query_filter = Filter(must=[FieldCondition(key="source_table", match=MatchValue(value=source_table))])

    response = qdrant_store.get_client().query_points(
        collection_name=indexers.CONTENT_COLLECTION,
        query=vector,
        query_filter=query_filter,
        limit=top_k,
    )
    for r in response.points:
        p = r.payload
        snippet = p["text_content"][:120].replace("\n", " ")
        print(f"score={r.score:.3f}  [{p['source_table']}#{p['source_id']}]  {snippet}")
        if p.get("unique_topic_id"):
            print(f"    unique_topic_id={p['unique_topic_id']}")
        if p.get("post_bank_id"):
            print(f"    post_bank_id={p['post_bank_id']}")


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "chaku se hamla"
    search(q)
