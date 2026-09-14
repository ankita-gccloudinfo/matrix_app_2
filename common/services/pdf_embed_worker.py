# Runs ONLY inside the isolated `pdf_embed_env` venv (numpy<2 + torch==2.2.2 —
# the newest torch build available for this Intel Mac). transformers/sentence-
# transformers versions in the main app environment are too new for that torch
# ceiling, so embedding computation is isolated here and exposed over a tiny
# local HTTP API that services/pdf_rag.py (running in the main environment)
# talks to, instead of importing torch/sentence-transformers directly.
import os
import threading

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import CrossEncoder

EMBED_MODEL_NAME = "jinaai/jina-embeddings-v3"
# Multilingual (incl. Hindi) cross-encoder used to rerank the Qdrant candidate
# pool after the initial dense-vector search — fixes cases where cosine
# similarity ranks a keyword/ID-exact chunk below a merely-related one.
RERANK_MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

# Use whichever GPU currently has enough free VRAM when this environment has
# more than one (e.g. a shared multi-GPU box) — picking a fixed index would
# happily land on a GPU another process is already using. Falls back to CPU
# (making sure PyTorch actually uses every core — by default it inherits
# OMP_NUM_THREADS from whatever spawned this process, which the main app pins
# to 1 to avoid an OpenMP conflict in ITS OWN process, silently single-
# threading this worker too if left unchecked) when no GPU has enough free.
def get_device():
    if not torch.cuda.is_available():
        return "cpu"

    from pynvml import (
        nvmlInit,
        nvmlDeviceGetCount,
        nvmlDeviceGetHandleByIndex,
        nvmlDeviceGetMemoryInfo,
    )

    nvmlInit()

    best_index, best_free_gb = None, 0.0
    for i in range(nvmlDeviceGetCount()):
        gpu = nvmlDeviceGetHandleByIndex(i)
        free_gb = nvmlDeviceGetMemoryInfo(gpu).free / 1024**3
        print(f"NVIDIA GPU {i} free VRAM: {free_gb:.2f} GB")
        if free_gb > best_free_gb:
            best_index, best_free_gb = i, free_gb

    # Need around 4GB for jina embeddings
    if best_index is not None and best_free_gb > 1:
        return f"cuda:{best_index}"

    print("No GPU with enough free VRAM, using CPU")
    return "cpu"


_DEVICE = get_device()
_DTYPE = torch.float16 if _DEVICE.startswith("cuda") else torch.float32
# GPU has VRAM to spare for bigger batches (A10, 24GB); CPU keeps the
# sentence-transformers default so we don't blow out system RAM instead.
_BATCH_SIZE = 128 if _DEVICE.startswith("cuda") else 32

if _DEVICE == "cpu":
    torch.set_num_threads(os.cpu_count() or 28)

# We no longer load any local embedding model here; all embeddings
# are delegated to the external API by pdf_rag.py.
# This worker now exclusively serves the cross-encoder for reranking.
_model = None

print(f" Loading reranker model {RERANK_MODEL_NAME} on {_DEVICE}...")
_reranker = CrossEncoder(RERANK_MODEL_NAME, device=_DEVICE, max_length=512)
print(f" Reranker model loaded on {_DEVICE}.")

app = FastAPI(title="PDF Embedding Worker")

# get_device() only checks free VRAM ONCE at startup — on a GPU shared with
# another process (e.g. Ollama serving the main chat LLM, which may only
# claim its VRAM lazily on first use), that check can pass while a later
# request still OOMs once the GPU fills up from elsewhere. Rather than
# crashing every request with a 500 from then on, permanently demote this
# worker's models to CPU the first time that happens and keep serving —
# slower, but correct — until the process is restarted.
_device_lock = threading.Lock()


def _is_oom(e: Exception) -> bool:
    return isinstance(e, torch.OutOfMemoryError) or "out of memory" in str(e).lower()


def _demote_to_cpu(reason: Exception):
    global _DEVICE, _BATCH_SIZE
    with _device_lock:
        if _DEVICE == "cpu":
            return  # another request already demoted us
        print(f"⚠️ GPU OOM ({reason}) — permanently switching this worker to CPU.")
        torch.cuda.empty_cache()
        try:
            _reranker.to("cpu")
        except AttributeError:
            _reranker.model.to("cpu")
        _DEVICE = "cpu"
        _BATCH_SIZE = 32
        torch.set_num_threads(os.cpu_count() or 28)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": "external",
        "device": _DEVICE,
    }


class RerankRequest(BaseModel):
    query: str
    documents: list[str]


@app.post("/rerank")
def rerank(req: RerankRequest):
    if not req.documents:
        return {"scores": []}
    pairs = [[req.query, doc] for doc in req.documents]
    try:
        scores = _reranker.predict(pairs, batch_size=_BATCH_SIZE).tolist()
    except RuntimeError as e:
        if not _is_oom(e):
            raise
        _demote_to_cpu(e)
        scores = _reranker.predict(pairs, batch_size=_BATCH_SIZE).tolist()
    return {"scores": scores}


if __name__ == "__main__":
    import uvicorn
    # Plain HTTP is intentional here, not an oversight: this worker is only ever
    # called over 127.0.0.1 by services/pdf_rag.py in the SAME process's host
    # (spawned as a local subprocess, see load_embedding_model()), never from a
    # browser — unlike server.py's 8123, which serves HTTPS because browser
    # geolocation requires a secure context. Do not add TLS here; it would just
    # break the plain-http calls pdf_rag.py already makes.
    port = int(os.environ.get("PDF_EMBED_WORKER_PORT", "8799"))
    uvicorn.run(app, host="0.0.0.0", port=port)
