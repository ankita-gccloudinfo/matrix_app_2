import httpx

import config

# Embeddings are computed by a vLLM server exposing jina-embeddings-v3 over
# the OpenAI-compatible /v1/embeddings route, not a locally-loaded model.
# NOTE: vLLM currently only supports jina-v3's "text-matching" LoRA merge —
# the retrieval.passage / retrieval.query task adapters used by the old local
# SentenceTransformer path aren't selectable via this API
# (https://github.com/vllm-project/vllm/issues/16120), so embed_passages and
# embed_query both hit the same endpoint with no task distinction.
EMBED_API_URL = config.EMBED_API_URL
EMBED_MODEL_NAME = config.EMBEDDING_MODEL

DEFAULT_EMBED_BATCH_SIZE = int(getattr(config, "EMBED_BATCH_SIZE", 0) or 128)

# Guard against pathologically long TEXT columns spiking request size/latency.
MAX_CHARS = 3000

_client = httpx.Client(timeout=120)


def _post_embeddings(texts):
    resp = _client.post(EMBED_API_URL, json={"model": EMBED_MODEL_NAME, "input": texts})
    resp.raise_for_status()
    data = sorted(resp.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def embed_passages(texts, batch_size=None):
    """Embed documents for indexing via the vLLM embeddings API."""
    truncated = [t[:MAX_CHARS] for t in texts]
    bs = batch_size or DEFAULT_EMBED_BATCH_SIZE
    vectors = []
    for i in range(0, len(truncated), bs):
        vectors.extend(_post_embeddings(truncated[i:i + bs]))
    return vectors


def embed_query(text):
    """Embed a search query via the vLLM embeddings API."""
    return _post_embeddings([text[:MAX_CHARS]])[0]
