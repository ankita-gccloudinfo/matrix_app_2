# qdrant_fallback.py — how to run

## What it does
When a SQL query returns 0 rows, this embeds the same query text and searches
Qdrant's `content_index` collection for semantically similar content, pointing
back to the exact MySQL `source_table` / `source_id` it came from.

## Do I need to run one file or several?

**Just one — `qdrant_fallback.py` is the entry point.**

```bash
python qdrant_fallback.py "your query text here"
```

It imports `embedder.py`, `indexers.py`, `qdrant_store.py`, and `config.py`
internally — those files need to **exist** in the same directory (they
already do), but you never run them directly. Importing is automatic; you
don't need a separate command for each one.

The only time you'd touch another file directly is for **one-time setup**
(see below) — not for normal use.

## Prerequisites (one-time setup, not run every time)

These aren't files you "run" in the same sense — they're environment
dependencies that need to be *already up* before `qdrant_fallback.py` will
work:

1. **`.env` must point at a reachable Qdrant.**
   Check what it currently resolves to:
   ```bash
   python -c "import config; print(config.QDRANT_HOST, config.QDRANT_PORT)"
   ```
   - For the real/production data: leave `QDRANT_HOST` pointed at the remote
     box (`10.242.24.35` in this project's `.env`). No local setup needed —
     just run the script.
   - For local testing only: `QDRANT_HOST=localhost`, and Qdrant itself must
     actually be running there (see below).

2. **If testing locally: Qdrant must be running.**
   ```bash
   docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
     -v $(pwd)/qdrant_storage:/qdrant/storage qdrant/qdrant
   ```
   Verify: `curl http://localhost:6333/collections`

3. **If testing locally: `content_index` must exist and have data.**
   A fresh local Qdrant is empty — it won't have `content_index` until you
   create it and index something.
   ```bash
   # Get the correct vector size first
   python -c "import embedder; print(len(embedder.embed_query('test')))"
   # → 1024 for jina-embeddings-v3

   # Create the collection
   python -c "
   from qdrant_client import QdrantClient
   from qdrant_client.models import VectorParams, Distance
   client = QdrantClient(host='localhost', port=6333)
   client.create_collection(
       collection_name='content_index',
       vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
   )
   "

   # Index some real data (start small)
   python -c "import indexers; indexers.index_analyzed_data(limit=100)"
   ```

## Running it

```bash
python qdrant_fallback.py "death in lucknow"
```

or with no argument (uses a built-in default query):
```bash
python qdrant_fallback.py
```

Output: a formatted list of matches (`table`, `id`, `score`, `snippet`), or
a "no similar content found" message if nothing scored above `min_score`
(default `0.2`).

## Quick health checks

**Embedding generation working?**
```bash
python -c "
import embedder
v = embedder.embed_query('test')
print(len(v), v[:5], all(x == 0 for x in v))
"
```
Expect: `1024 [some floats] False`

**Is a specific row actually stored in Qdrant (not just embedded)?**
```bash
python -c "
import indexers
from qdrant_client import QdrantClient
point_id = indexers._point_id('analyzed_data', <ROW_ID>, 'input_text')
client = QdrantClient(host='localhost', port=6333)  # or your remote host
result = client.retrieve(collection_name='content_index', ids=[point_id], with_vectors=True, with_payload=True)
print(result)
"
```

**Visual check:** open `http://localhost:6333/dashboard#/collections` (or the
remote host's `:6333/dashboard`) in a browser — shows point counts, status,
and vector config for every collection at a glance.

## Notes
- `embed_query` and `embed_passages` hit the same vLLM endpoint with no
  task-specific distinction (vLLM doesn't yet expose jina-v3's separate
  retrieval.query / retrieval.passage adapters) — this is expected, not a bug.
- Point IDs are deterministic (`uuid5(table:row_id:column)`) — re-indexing
  the same row overwrites its existing point rather than duplicating it.
- `content_index` (production data) lives on the **remote** Qdrant by
  default. A local Qdrant instance starts empty and needs its own indexing
  run before `qdrant_fallback.py` will return anything meaningful against it.