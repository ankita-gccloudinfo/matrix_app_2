# PDF ingestion + retrieval for the "pdf" graph route in ollamaagent2.py.
#
# Runs in the main app environment. Embedding and reranking computation is
# delegated over HTTP to pdf_embed_worker.py, which runs inside the isolated
# `pdf_embed_env` venv (see that file for why) — this module never imports
# torch or sentence-transformers itself.
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
import sys
import fitz  # pymupdf
import httpx
import pytesseract
from PIL import Image
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, FieldCondition, Filter, MatchAny, MatchValue, PointStruct,
    VectorParams,
)

# Scanned/image-only PDFs (e.g. newspaper clippings) have no embedded text
# layer, so page.get_text() returns empty/near-empty — OCR is the fallback.
# Hindi included alongside English since uploaded documents aren't all in
# English (e.g. Dainik Bhaskar clippings).
_OCR_LANGS = "eng+hin"
_OCR_MIN_TEXT_LEN = 20

# Overridable via project_config (see common/project_config.py) — keeps the
# previous hardcoded value as the default.
PDF_QDRANT_HOST = os.getenv("PDF_QDRANT_HOST", "localhost")
PDF_QDRANT_PORT = int(os.getenv("PDF_QDRANT_PORT", "6333"))
PDF_COLLECTION = os.getenv("PDF_COLLECTION", "pdf")
EMBED_DIM = 1024  # jina-embeddings-v3 default output size
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PYTHON = sys.executable

_WORKER_SCRIPT = os.path.join(_PROJECT_ROOT, "services", "pdf_embed_worker.py")
_WORKER_PORT = 8799
_WORKER_URL = f"http://127.0.0.1:{_WORKER_PORT}"

# Embeddings are ALWAYS computed by an external OpenAI-compatible
# /v1/embeddings server (e.g. vLLM serving jina-embeddings-v3 on a GPU box).
# The local worker subprocess is only spawned to run the reranker model.
EXTERNAL_EMBEDDINGS_URL = os.getenv("EXTERNAL_EMBEDDINGS_URL", "http://100.100.130.85:2225/v1/embeddings")
EXTERNAL_EMBEDDINGS_MODEL = os.getenv("EXTERNAL_EMBEDDINGS_MODEL", "jinaai/jina-embeddings-v3")

pdf_qdrant_client = QdrantClient(host=PDF_QDRANT_HOST, port=PDF_QDRANT_PORT)

_worker_process = None


def _worker_healthy() -> bool:
    try:
        r = httpx.get(f"{_WORKER_URL}/health", timeout=2)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except httpx.HTTPError:
        return False


def load_embedding_model(startup_timeout: int = 360):
    """Spawn the embedding worker subprocess (isolated venv) if it isn't already
    running, and block until it reports healthy. Call once at server startup —
    mirrors services/transcription.py's load_whisper_model()."""
    global _worker_process

    if _worker_healthy():
        print(" PDF embedding worker already running.")
        return

    if not os.path.exists(_PYTHON):
        raise RuntimeError(f"Python executable not found: {_PYTHON}")

    print(" Starting PDF embedding worker...")
    log_path = os.path.join(_PROJECT_ROOT, "worker.log")
    log_file = open(log_path, "a")
    # Drop the main process's OMP_NUM_THREADS=1 (set to avoid an OpenMP
    # conflict in THIS process) so the worker's PyTorch can use every core
    # instead of being silently pinned to one.
    env = {**os.environ, "PDF_EMBED_WORKER_PORT": str(_WORKER_PORT)}
    env.pop("OMP_NUM_THREADS", None)
    _worker_process = subprocess.Popen(
        [_PYTHON, _WORKER_SCRIPT],
        stdout=log_file, stderr=subprocess.STDOUT, env=env,
    )

    deadline = time.time() + startup_timeout
    while time.time() < deadline:
        if _worker_healthy():
            print(" PDF embedding worker ready.")
            return
        if _worker_process.poll() is not None:
            print(f"⚠️ PDF embedding worker exited early — see {log_path}")
            return
        time.sleep(1)

    print(f"⚠️ PDF embedding worker did not become healthy within {startup_timeout}s "
          f"(first run downloads the embedding + reranker models, ~2.8GB) — see {log_path}")


def stop_embedding_worker():
    if _worker_process and _worker_process.poll() is None:
        _worker_process.terminate()


# Chunk count per HTTP request. The worker has no CPU-RAM OOM guard (only
# GPU OOM is handled, see pdf_embed_worker.py's _demote_to_cpu) — this
# machine has no CUDA device, so every embed call runs on CPU, and a big
# batch (used to be 256) encoding simultaneously on a CPU-bound transformer
# can spike RSS enough that the OS SIGKILLs the worker mid-request with no
# Python traceback. Smaller batches lower that peak.
_EMBED_BATCH_SIZE = 64

_worker_respawn_lock = threading.Lock()


def _post_to_worker(path: str, json_body: dict):
    """POST to the embed worker, respawning it once and retrying if it's
    unreachable — a SIGKILL'd worker (see _EMBED_BATCH_SIZE above) previously
    left EVERY subsequent PDF upload failing with Connection refused until
    someone manually restarted the main server; this makes it self-heal.

    No request timeout (timeout=None) — a big/slow PDF (e.g. a large clinical
    textbook) can take longer to embed on this CPU-bound worker than a fixed
    timeout allows, which was surfacing as "Failed to process PDF: timed
    out" instead of letting it finish. The worker being unreachable (dead
    process) still fails/retries immediately above; this only removes the
    cutoff for a worker that's alive but slow."""
    url = f"{_WORKER_URL}{path}"
    try:
        resp = httpx.post(url, json=json_body, timeout=None)
    except httpx.ConnectError:
        print(f"⚠️ PDF embedding worker unreachable at {url} — respawning and retrying once...")
        with _worker_respawn_lock:
            if not _worker_healthy():
                load_embedding_model()
        resp = httpx.post(url, json=json_body, timeout=None)
    resp.raise_for_status()
    return resp


def _embed_via_external_api(texts: list[str], task: str) -> list[list[float]]:
    """Calls the external OpenAI-compatible /v1/embeddings server.
    "task" is passed through as an extra field in case the server honors
    jina-v3's task-specific LoRA adapters."""
    resp = httpx.post(
        EXTERNAL_EMBEDDINGS_URL,
        json={"model": EXTERNAL_EMBEDDINGS_MODEL, "input": texts, "task": task},
        timeout=None,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return [item["embedding"] for item in sorted(data, key=lambda d: d["index"])]


def _embed(texts: list[str], task: str) -> list[list[float]]:
    """Embed in batches."""
    vectors = []
    for i in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[i:i + _EMBED_BATCH_SIZE]
        vectors.extend(_embed_via_external_api(batch, task))
    return vectors


def _rerank(query: str, texts: list[str]) -> list[float]:
    """Cross-encoder rerank of a candidate pool — scores query+chunk jointly,
    unlike cosine similarity, so it catches keyword/ID-exact chunks that a
    pure dense-vector search ranks too low."""
    if not texts:
        return []
    resp = _post_to_worker("/rerank", {"query": query, "documents": texts})
    return resp.json()["scores"]


def _ensure_pdf_collection():
    if not pdf_qdrant_client.collection_exists(PDF_COLLECTION):
        pdf_qdrant_client.create_collection(
            collection_name=PDF_COLLECTION,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )


def _ocr_page(page) -> str:
    """Render a page to an image and OCR it — used when the page has no (or
    negligible) embedded text layer, i.e. it's a scanned image rather than
    born-digital text."""
    pix = page.get_pixmap(dpi=200)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        return pytesseract.image_to_string(img, lang=_OCR_LANGS)
    except pytesseract.TesseractError as e:
        print(f"⚠️ OCR failed for a page: {e}")
        return ""


def extract_pages(file_bytes: bytes) -> list[str]:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        pages = []
        for page in doc:
            text = page.get_text()
            if len(text.strip()) < _OCR_MIN_TEXT_LEN:
                text = _ocr_page(page)
            pages.append(text)
        return pages
    finally:
        doc.close()


def _chunk_text(text: str, chunk_size: int = 6000, overlap: int = 1000) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def ingest_pdf(
    file_bytes: bytes,
    filename: str,
    user_id: str = "anonymous",
    user_name: str = "Unknown",
    is_admin_upload: bool = False,
) -> dict:
    """Extract, chunk, embed, and upsert one PDF into the `pdf` Qdrant collection.

    Each chunk payload carries:
      - user_id          : uploader's MongoDB _id (used to scope search)
      - user_name        : uploader's display name (for query-log display)
      - is_admin_upload  : True → chunk is returned for ALL users regardless
                           of their own user_id; False → private to uploader.
    """
    _ensure_pdf_collection()

    pages = extract_pages(file_bytes)

    chunk_texts, chunk_pages = [], []
    for page_num, page_text in enumerate(pages, start=1):
        for chunk in _chunk_text(page_text):
            chunk_texts.append(chunk)
            chunk_pages.append(page_num)

    if not chunk_texts:
        return {"filename": filename, "pages": len(pages), "chunks": 0}

    vectors = _embed(chunk_texts, task="retrieval.passage")
    uploaded_at = datetime.now(timezone.utc).isoformat()

    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "text": text,
                "filename": filename,
                "page": page,
                "uploaded_at": uploaded_at,
                # ── isolation fields ──────────────────────────────────────
                "user_id": user_id,          # uploader identity
                "user_name": user_name,      # for admin query-log display
                "is_admin_upload": is_admin_upload,  # True → visible to all
            },
        )
        for text, vector, page in zip(chunk_texts, vectors, chunk_pages)
    ]
    pdf_qdrant_client.upsert(collection_name=PDF_COLLECTION, points=points)

    return {"filename": filename, "pages": len(pages), "chunks": len(points)}


def list_available_filenames(user_id: str = "anonymous", limit: int = 500) -> list[str]:
    """Distinct filenames currently visible to this user — admin-shared PDFs
    plus their own private uploads — same isolation rule as search_pdf.
    Used to let an LLM pick which specific file(s) a query is about before
    pdf_search scopes to them, instead of pooling every admin PDF together."""
    if not pdf_qdrant_client.collection_exists(PDF_COLLECTION):
        return []
    isolation_filter = Filter(
        should=[
            FieldCondition(key="user_id", match=MatchValue(value=user_id)),
            FieldCondition(key="is_admin_upload", match=MatchValue(value=True)),
        ]
    )
    points, _ = pdf_qdrant_client.scroll(
        collection_name=PDF_COLLECTION,
        scroll_filter=isolation_filter,
        with_payload=["filename"],
        limit=limit,
    )
    return sorted({p.payload.get("filename") for p in points if p.payload.get("filename")})


def search_pdf(
    query: str,
    filenames: list[str],
    user_id: str = "anonymous",
    limit: int = 6,
    pool_size: int = 25,
) -> list[dict]:
    """Semantic search over PDF chunks scoped to the current user.

    A chunk is returned when EITHER condition is true:
      1. Its ``user_id`` matches the caller's ``user_id``  (private upload)
      2. Its ``is_admin_upload`` flag is True               (shared for all)

    If a filename scope is supplied, the search is restricted to those
    filenames. If it is empty, the function still returns admin-shared PDF
    chunks and the caller's own private chunks, so admin-uploaded PDFs can be
    globally visible across sessions without requiring the user to upload them
    themselves.

    Retrieves a larger `pool_size` candidate set by cosine similarity, then
    reranks it with a cross-encoder and keeps the top `limit` — cosine
    similarity alone ranks purely by embedding proximity, which misses chunks
    that are the best answer but phrased differently from the query."""
    if not pdf_qdrant_client.collection_exists(PDF_COLLECTION):
        return []

    vector = _embed([query], task="retrieval.query")[0]

    # Match chunks where the uploader is the caller OR the upload is admin-wide.
    user_isolation_filter = Filter(
        should=[
            FieldCondition(key="user_id",         match=MatchValue(value=user_id)),
            FieldCondition(key="is_admin_upload",  match=MatchValue(value=True)),
        ]
    )

    # If the caller explicitly has a PDF scope, narrow to those filenames.
    # Otherwise, let the global admin-shared PDFs plus the caller's private
    # PDFs participate in search for the current turn.
    query_filter = user_isolation_filter
    if filenames:
        filename_filter = Filter(
            must=[FieldCondition(key="filename", match=MatchAny(any=filenames))]
        )
        query_filter = Filter(must=[user_isolation_filter, filename_filter])

    hits = pdf_qdrant_client.query_points(
        collection_name=PDF_COLLECTION,
        query=vector,
        query_filter=query_filter,
        limit=pool_size,
    ).points

    if not hits:
        return []

    scores = _rerank(query, [h.payload.get("text", "") for h in hits])
    reranked = sorted(zip(hits, scores), key=lambda pair: pair[1], reverse=True)[:limit]

    return [
        {
            "text": h.payload.get("text", ""),
            "filename": h.payload.get("filename", ""),
            "page": h.payload.get("page", ""),
            "score": score,
        }
        for h, score in reranked
    ]
