# PDF ingestion + retrieval for the "pdf" graph route in ollamaagent2.py.
#
# Runs in the main app environment. Embedding goes straight to the
# vLLM-hosted jina-embeddings-v3 over HTTP (see ../embedder.py). Reranking is
# still delegated over HTTP to pdf_embed_worker.py, which runs inside the
# isolated `pdf_embed_env` venv (see that file for why) — this module never
# imports torch or sentence-transformers itself.
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
import sys
import fitz  # pymupdf
import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, FieldCondition, Filter, MatchAny, PointStruct, VectorParams,
)

import embedder

# Overridable via project_config (see common/project_config.py) — keeps the
# previous hardcoded value as the default.
PDF_QDRANT_HOST = os.getenv("PDF_QDRANT_HOST", "10.242.24.35")
PDF_QDRANT_PORT = int(os.getenv("PDF_QDRANT_PORT", "6333"))
PDF_COLLECTION = os.getenv("PDF_COLLECTION", "pdf")
EMBED_DIM = 1024  # jina-embeddings-v3 default output size
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PYTHON = sys.executable

_WORKER_SCRIPT = os.path.join(_PROJECT_ROOT, "services", "pdf_embed_worker.py")
_WORKER_PORT = 8799
_WORKER_URL = f"http://127.0.0.1:{_WORKER_PORT}"

pdf_qdrant_client = QdrantClient(host=PDF_QDRANT_HOST, port=PDF_QDRANT_PORT)

_worker_process = None


def _worker_healthy() -> bool:
    try:
        r = httpx.get(f"{_WORKER_URL}/health", timeout=2)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except httpx.HTTPError:
        return False


def load_rerank_worker(startup_timeout: int = 360):
    """Spawn the reranker worker subprocess (isolated venv) if it isn't already
    running, and block until it reports healthy. Call once at server startup —
    mirrors services/transcription.py's load_whisper_model()."""
    global _worker_process

    if _worker_healthy():
        print(" PDF rerank worker already running.")
        return

    if not os.path.exists(_PYTHON):
        raise RuntimeError(f"Python executable not found: {_PYTHON}")

    print(" Starting PDF rerank worker...")
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
            print(" PDF rerank worker ready.")
            return
        if _worker_process.poll() is not None:
            print(f"⚠️ PDF rerank worker exited early — see {log_path}")
            return
        time.sleep(1)

    print(f"⚠️ PDF rerank worker did not become healthy within {startup_timeout}s "
          f"(first run downloads the reranker model) — see {log_path}")


def stop_rerank_worker():
    if _worker_process and _worker_process.poll() is None:
        _worker_process.terminate()


_worker_respawn_lock = threading.Lock()


def _post_to_worker(path: str, json_body: dict):
    """POST to the rerank worker, respawning it once and retrying if it's
    unreachable — a SIGKILL'd worker previously left EVERY subsequent PDF
    search failing with Connection refused until someone manually restarted
    the main server; this makes it self-heal.

    No request timeout (timeout=None) — a big candidate pool can take longer
    to rerank on this CPU-bound worker than a fixed timeout allows, which was
    surfacing as a request timing out instead of letting it finish. The
    worker being unreachable (dead process) still fails/retries immediately
    above; this only removes the cutoff for a worker that's alive but slow."""
    url = f"{_WORKER_URL}{path}"
    try:
        resp = httpx.post(url, json=json_body, timeout=None)
    except httpx.ConnectError:
        print(f"⚠️ PDF rerank worker unreachable at {url} — respawning and retrying once...")
        with _worker_respawn_lock:
            if not _worker_healthy():
                load_rerank_worker()
        resp = httpx.post(url, json=json_body, timeout=None)
    resp.raise_for_status()
    return resp


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


def extract_pages(file_bytes: bytes) -> list[str]:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        return [page.get_text() for page in doc]
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

    Each chunk payload carries user_id/user_name/is_admin_upload so the admin
    dashboard's PDF Uploads tab can attribute and scope deletes/renames per
    uploader (see /api/admin/pdfs in server.py)."""
    _ensure_pdf_collection()

    pages = extract_pages(file_bytes)

    chunk_texts, chunk_pages = [], []
    for page_num, page_text in enumerate(pages, start=1):
        for chunk in _chunk_text(page_text):
            chunk_texts.append(chunk)
            chunk_pages.append(page_num)

    if not chunk_texts:
        return {"filename": filename, "pages": len(pages), "chunks": 0}

    vectors = embedder.embed_passages(chunk_texts)
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
                "user_id": user_id,
                "user_name": user_name,
                "is_admin_upload": is_admin_upload,
            },
        )
        for text, vector, page in zip(chunk_texts, vectors, chunk_pages)
    ]
    pdf_qdrant_client.upsert(collection_name=PDF_COLLECTION, points=points)

    return {"filename": filename, "pages": len(pages), "chunks": len(points)}


def search_pdf(query: str, filenames: list[str], limit: int = 6, pool_size: int = 25) -> list[dict]:
    """Semantic search over chunks belonging to `filenames` only — the `pdf`
    collection persists across sessions, so results must be scoped to the
    document(s) actually uploaded in the current session.

    Retrieves a larger `pool_size` candidate set by cosine similarity, then
    reranks it with a cross-encoder and keeps the top `limit` — cosine
    similarity alone ranks purely by embedding proximity, which misses chunks
    that are the best answer but phrased differently from the query."""
    if not filenames or not pdf_qdrant_client.collection_exists(PDF_COLLECTION):
        return []

    vector = embedder.embed_query(query)
    query_filter = Filter(must=[FieldCondition(key="filename", match=MatchAny(any=filenames))])

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
