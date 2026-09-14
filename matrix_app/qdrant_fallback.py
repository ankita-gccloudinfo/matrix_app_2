import embedder
import indexers
import qdrant_store


def suggest_similar(query_text, top_k=5, min_score=0.2):
    """When a SQL query returns 0 rows, embed the same query and look for
    semantically similar content in Qdrant. Each hit's payload carries
    source_table/source_id, which is the relation back to the SQL row it
    came from — so a result here tells you exactly where to look in MySQL,
    not just that "something similar" exists.

    Returns a list of dicts: {score, source_table, source_id, unique_topic_id,
    post_bank_id, snippet}.
    """
    vector = embedder.embed_query(query_text)
    response = qdrant_store.get_client().query_points(
        collection_name=indexers.CONTENT_COLLECTION,
        query=vector,
        limit=top_k,
    )

    suggestions = []
    for point in response.points:
        if point.score < min_score:
            continue
        payload = point.payload
        suggestions.append({
            "score": point.score,
            "source_table": payload.get("source_table"),
            "source_id": payload.get("source_id"),
            "unique_topic_id": payload.get("unique_topic_id"),
            "post_bank_id": payload.get("post_bank_id"),
            "snippet": (payload.get("text_content") or "")[:200],
        })
    return suggestions


def format_suggestions(suggestions):
    """Turns suggest_similar()'s output into the "you may find results in
    this table" message the SQL agent can show when it has nothing."""
    if not suggestions:
        return "No records were found matching your request, and no similar content was found either."

    lines = ["No exact match found, but similar content exists:"]
    for s in suggestions:
        lines.append(
            f"- table `{s['source_table']}` (id={s['source_id']}, score={s['score']:.2f}): {s['snippet']}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "death in lucknow"
    print(format_suggestions(suggest_similar(q)))
