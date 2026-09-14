"""Scaffolds a brand-new project directory, using river_cannel's blank-
skeleton shape as the template: registers every common/routes.py endpoint
plus a minimal /api/chat, backed by the smallest working agent graph
(PDF-augmented general chat, no domain specialization). The generated
ollamaagent2.py is a starting point only — per the project convention, no
code here or elsewhere ever edits an existing project's ollamaagent2.py;
that's where each project's actual domain logic lives, written by hand.

Frontend assets (css/js/index.html/query-log.html) and services/pdf_rag.py
+ pdf_embed_worker.py are symlinked straight into common/ rather than
copied, same as ai_sayak_medical_up and river_cannel already do — so a new
project starts out fully sharing the common layer, with only
frontend/js/app-config.js (branding) as its own real file alongside
server.py and ollamaagent2.py.
"""
import os
import re
import shutil

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_NAMES = {"common", "admin_config", "logs", ".git", "__pycache__"}

_SHARED_CSS_FILES = [
    "avatar-widget.css", "charts.css", "chat.css", "history.css", "layout.css",
    "mobile.css", "query-log-mobile.css", "query-log.css", "related.css",
    "settings.css", "sidebar.css", "suggestions.css", "topbar.css", "trace.css",
    "variables.css",
]
_SHARED_JS_FILES = [
    "auth.js", "i18n.js", "resizer.js", "script.js", "settings.js", "suggestions.js",
]

_SERVER_TEMPLATE = '''from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
import os
import sys
import uuid
import asyncio
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

# Shared code lives in ../common (see common/routes.py) — every project in
# this repo imports from it instead of keeping duplicate copies. This app
# was scaffolded as a blank skeleton (see admin_config/scaffold.py): it
# registers every common endpoint (auth, PDF upload/RAG, TTS, avatar,
# history, admin, ...) and adds only a minimal /api/chat on top, backed by
# the smallest possible working agent graph (ollamaagent2.py — PDF-augmented
# general chat, no domain specialization). Add real {project_id}-specific
# logic by growing that graph yourself — server.py/common/routes.py don't
# need to change to support a bigger graph, the same way matrix_app's much
# larger SQL/Qdrant graph plugs into this exact same shape.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

PROJECT_ID = "{project_id}"

# Must run BEFORE importing ollamaagent2/services.pdf_rag below — those
# modules read their config (VLLM_*, PDF_QDRANT_*, ...) from os.environ at
# import time, so any admin-configured override (see django/admin_config)
# has to land in os.environ before that import happens. No-ops gracefully if
# nothing has been configured for this project yet.
from common.project_config import apply_project_config
apply_project_config(PROJECT_ID)

from ollamaagent2 import graph as agent_app, call_llm, clear_trace, get_trace
from common.database.mongo import get_sessions_collection
from common.services.transcription import load_whisper_model, get_whisper_model
from services.pdf_rag import load_embedding_model, stop_embedding_worker, ingest_pdf, extract_pages
from common.services.nemotron_asr import load_nemotron_model, get_nemotron_model, NemotronAudioStreamSession
from common.routes import (
    register_common_routes,
    CommonRouteConfig,
    get_or_create_session,
    get_current_user,
    _strip_meta_sentinel,
    _persist_chat_session,
    _log_query,
)

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"

# ── LiveAvatar config ─────────────────────────────────────────────
LIVEAVATAR_API_KEY = os.getenv("LIVEAVATAR_API_KEY", "")
AVATAR_ID = os.getenv("AVATAR_ID", "65f9e3c9-d48b-4118-b73a-4ae2e3cbb8f0")  # "June HR" — same public avatar the other apps default to
# ────────────────────────────────────────────────────────────────

_CERT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cert.pem")
_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "key.pem")
_HAS_TLS_CERT = os.path.exists(_CERT_PATH) and os.path.exists(_KEY_PATH)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_whisper_model()
    load_nemotron_model()
    load_embedding_model()
    yield
    stop_embedding_worker()

app = FastAPI(title="{project_title} API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from typing import Optional, List

frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
question_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "question")
_mainindex_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mainindex.html")
_chat_html_path = os.path.join(frontend_path, "index.html")


@app.get("/")
async def landing_page():
    if os.path.exists(_mainindex_path):
        return FileResponse(_mainindex_path)
    return FileResponse(_chat_html_path)


@app.get("/chat")
async def chat_page():
    return FileResponse(_chat_html_path)


@app.get("/demo")
async def demo_page():
    if os.path.exists(_mainindex_path):
        return FileResponse(_mainindex_path)
    return FileResponse(_chat_html_path)


@app.get("/{{page_name}}.html")
async def serve_html_page(page_name: str):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{{page_name}}.html")
    if os.path.exists(path):
        return FileResponse(path)
    from fastapi import HTTPException as _HTTPException
    raise _HTTPException(status_code=404, detail=f"{{page_name}}.html not found")


@app.get("/c/{{chat_id}}")
async def chat_page_with_id(chat_id: str):
    return FileResponse(_chat_html_path)


register_common_routes(app, CommonRouteConfig(
    call_llm=call_llm,
    clear_trace=clear_trace,
    get_trace=get_trace,
    ingest_pdf=ingest_pdf,
    extract_pages=extract_pages,
    get_whisper_model=get_whisper_model,
    get_nemotron_model=get_nemotron_model,
    nemotron_session_cls=NemotronAudioStreamSession,
    frontend_path=frontend_path,
    question_file_path=question_file_path,
    avatar_id_default=AVATAR_ID,
    liveavatar_api_key=LIVEAVATAR_API_KEY,
    default_tts_voice_id=None,
))


class ChatRequest(BaseModel):
    query: str
    limit: Optional[str] = "50"
    # When set, scopes PDF retrieval to only these filenames instead of every
    # PDF uploaded this session — used when a specific "PDF expert" avatar is
    # active (see /api/pdf-experts/build) so it only answers from its own doc(s).
    pdf_scope: Optional[List[str]] = None
    # Name of the active PDF expert persona, if any.
    expert_name: Optional[str] = None
    lang: Optional[str] = "en"
    # Which conversation this message belongs to. None means "start a new
    # chat" — the server mints a fresh chat_id and reports it back via the
    # X-Chat-Id response header.
    chat_id: Optional[str] = None


@app.post("/api/chat")
async def chat_endpoint(chat_request: ChatRequest, http_request: Request, response: Response):
    _, session = get_or_create_session(http_request, response)
    query = chat_request.query

    chat_id = chat_request.chat_id or str(uuid.uuid4())
    if chat_request.chat_id:
        existing_doc = await get_sessions_collection().find_one({{"_id": chat_id}})
        messages = existing_doc["messages"].copy() if existing_doc else []
    else:
        messages = []
    messages.append({{"role": "user", "content": query}})
    question_number = sum(1 for m in messages if m.get("role") == "user")

    current_user = await get_current_user(http_request)
    user_name = current_user["name"] if current_user else "Anonymous"
    user_id = current_user["_id"] if current_user else None

    pdf_filenames = chat_request.pdf_scope if chat_request.pdf_scope is not None else session.pdf_filenames

    clear_trace()

    invoke_task = asyncio.create_task(agent_app.ainvoke({{
        "query": query,
        "messages": messages,
        "limit": chat_request.limit,
        "pdf_uploaded": bool(pdf_filenames),
        "pdf_filenames": pdf_filenames,
        "session_id": chat_id,
        "expert_name": chat_request.expert_name or "",
        "lang": chat_request.lang,
        "user_id": user_id,
        "user_name": user_name,
        "chat_id": chat_id,
        "question_number": question_number,
    }}))

    while not invoke_task.done():
        if await http_request.is_disconnected():
            invoke_task.cancel()
            try:
                await invoke_task
            except (asyncio.CancelledError, Exception):
                pass
            return Response(status_code=204)
        await asyncio.sleep(0.25)

    result = invoke_task.result()

    answer = result.get("answer", "No answer generated.")
    messages.append({{"role": "assistant", "content": answer}})

    asyncio.create_task(_log_query(
        user_name=user_name,
        query=query,
        rewritten_query=result.get("query", query),
        answer=_strip_meta_sentinel(answer),
        sql_rows=result.get("sql_rows"),
        trace=get_trace(),
        chat_id=chat_id,
        user_id=user_id,
    ))

    asyncio.create_task(_persist_chat_session(chat_id, messages, user_id=user_id, user_name=user_name))

    async def stream_answer():
        chunk_size = 5
        for i in range(0, len(answer), chunk_size):
            if await http_request.is_disconnected():
                break
            yield answer[i:i + chunk_size]
            await asyncio.sleep(0.012)

    stream_resp = StreamingResponse(stream_answer(), media_type="text/plain; charset=utf-8")
    stream_resp.headers["X-Chat-Id"] = chat_id
    for header_name, header_value in response.raw_headers:
        if header_name.decode().lower() == "set-cookie":
            stream_resp.raw_headers.append((header_name, header_value))
    return stream_resp


if __name__ == "__main__":
    import uvicorn
    # {default_port} (env-overridable via PORT) — see ARCHITECTURE.md for the
    # full port list across every project in this repo.
    _port = int(os.getenv("PORT", "{default_port}"))
    _ssl_kwargs = {{}}
    if _HAS_TLS_CERT:
        _ssl_kwargs = {{"ssl_certfile": _CERT_PATH, "ssl_keyfile": _KEY_PATH}}
        print(f"Starting API Server and Web UI on https://0.0.0.0:{{_port}} (self-signed cert)")
    else:
        print(f"Starting API Server and Web UI on http://0.0.0.0:{{_port}}")
    uvicorn.run(app, host="0.0.0.0", port=_port, **_ssl_kwargs)
'''

_OLLAMAAGENT_TEMPLATE = '''import os

# Overridable via project_config (see common/project_config.py) — keeps the
# same defaults as the other apps' LLM backend, so behavior is unchanged
# unless the admin panel (django/admin_config) sets an override for this
# project.
LLM_BACKEND = os.getenv("LLM_BACKEND", "vllm")  # "vllm" or "ollama"

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://10.242.71.180:2211/v1")
VLLM_MODEL_NAME = os.getenv("VLLM_MODEL_NAME", "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY")  # vLLM ignores this unless it was started with --api-key

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://10.242.24.35:11434/api/generate")
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "qwen3-coder:30b")

import re
import json
import asyncio
from typing import TypedDict, List, Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

from services.pdf_rag import search_pdf, list_available_filenames

# LangChain LLM client — points at the same vLLM OpenAI-compatible endpoint
llm = ChatOpenAI(
    model=VLLM_MODEL_NAME,
    base_url=VLLM_BASE_URL,
    api_key=VLLM_API_KEY,
    temperature=0,
)


def generate_ollama(prompt: str) -> str:
    """Helper to call Ollama synchronously (runs in thread)."""
    import requests
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL_NAME,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0,
                "num_ctx": 65536
            }
        },
        timeout=120
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


async def call_llm(prompt: str) -> str:
    """Invoke the configured LLM backend and return clean text, stripping any <think> blocks."""
    try:
        if LLM_BACKEND.lower() == "ollama":
            text = await asyncio.to_thread(generate_ollama, prompt)
        else:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            text = response.content

        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        return text.strip()
    except Exception as e:
        print(f"LLM Error ({LLM_BACKEND}):", e)
        return ""


def format_history(messages: list) -> str:
    """Last 10 turns of conversation, formatted for a prompt."""
    if not messages:
        return "(no previous conversation)"
    lines = []
    for m in messages[-20:]:
        role = "User" if m.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {m.get('content', '')}")
    return "\\n".join(lines[-10:])


# ── Trace collector — same shape as the other apps, so the shared
# GET /api/trace / Agent Workflow panel (common/routes.py) works unchanged. ──
_trace_log: list = []


def clear_trace():
    _trace_log.clear()


def get_trace():
    return list(_trace_log)


def add_trace(node_name: str, user_query: str = None, prompt: str = None,
              output: str = None, **extra):
    entry = {"node": node_name, "query": user_query, "prompt": prompt, "output": output}
    entry.update(extra)
    _trace_log.append(entry)


class State(TypedDict):
    query: str
    messages: List[Dict[str, str]]
    limit: Optional[str]
    pdf_uploaded: bool
    pdf_filenames: list
    pdf_results: List[Any]
    session_id: str
    expert_name: str
    lang: str
    user_id: Optional[str]
    user_name: str
    chat_id: str
    question_number: int
    answer: str
    sql_rows: Any


# ─────────────────────────────────────────────────────────────────────────────
# This is intentionally the smallest possible working graph: PDF-augmented
# general chat, no domain specialization. Build this project's actual domain
# logic by adding nodes/branches here — the rest of the app (server.py,
# common/routes.py) doesn't need to change to support a bigger graph, the
# same way matrix_app's much larger graph plugs in.
#
# This file is intentionally NOT touched by any other tooling in this repo
# (admin_config, common/, other projects' scaffolding) once it exists — it's
# where this project's actual behavior lives, written by hand.
# ─────────────────────────────────────────────────────────────────────────────

async def pdf_search_node(state: State) -> dict:
    """Searches the uploaded PDF(s) for relevant chunks via Qdrant semantic
    search. Passes the requesting user's user_id so search_pdf can return
    only that user's private chunks plus any admin-uploaded (globally
    shared) ones — same isolation model as the other apps."""
    query = state["query"]
    user_id = state.get("user_id") or "anonymous"
    try:
        hits = await asyncio.to_thread(
            search_pdf, query, state.get("pdf_filenames", []), user_id,
        )
    except Exception as e:
        print(f"⚠️ PDF search failed: {e}")
        hits = []
    add_trace("pdf_search", user_query=query, output=f"{len(hits)} chunk(s) retrieved")
    return {"pdf_results": hits}


async def pdf_answer_node(state: State) -> dict:
    query = state["query"]
    history = format_history(state.get("messages", []))
    hits = state.get("pdf_results", [])

    if hits:
        context = "\\n\\n---\\n\\n".join(
            f"[{h['filename']} — page {h['page']}]\\n{h['text']}" for h in hits
        )
    else:
        context = "No document excerpts were retrieved."

    prompt = f"""You are a helpful assistant. Answer the user's question using the
document excerpts below when relevant, and your own general knowledge otherwise.
Be concise and direct.

CONVERSATION HISTORY:
{history}

DOCUMENT EXCERPTS:
{context}

USER QUESTION:
{query}

Answer:"""

    answer = await call_llm(prompt)
    if not answer:
        answer = "Sorry, I couldn't generate a response right now."
    add_trace("pdf_answer", user_query=query, prompt=prompt, output=answer)
    return {"answer": answer}


graph_builder = StateGraph(State)
graph_builder.add_node("pdf_search", pdf_search_node)
graph_builder.add_node("pdf_answer", pdf_answer_node)
graph_builder.set_entry_point("pdf_search")
graph_builder.add_edge("pdf_search", "pdf_answer")
graph_builder.add_edge("pdf_answer", END)
graph = graph_builder.compile()
'''

_APP_CONFIG_TEMPLATE = '''// Per-app branding for the shared index.html (common/frontend/index.html,
// symlinked in as frontend/index.html) — this file is the only genuinely
// app-specific piece of that page's chrome.
window.APP_CONFIG = {{
    title: "{project_title}",
    disclaimerTitle: "AI Disclaimer",
    disclaimerHtml:
        "<p>This application is an AI-powered assistant for informational purposes only. " +
        "Responses may be incomplete or inaccurate — verify anything important before relying on it.</p>",
}};
'''

_ENV_TEMPLATE = (
    "HF_TOKEN=\nLIVEAVATAR_API_KEY=\n"
    "MONGO_URI=mongodb://10.242.24.35:27017\n"
    "MONGO_DB_NAME={project_id}_db\n"  # own database — don't default to police_intel_db, that's matrix_app's and would silently share query/user/PDF data with every other project on the same Mongo host
    "PDF_QDRANT_HOST=10.242.24.35\n"
)

_GITIGNORE_TEMPLATE = "__pycache__/\n*.pyc\n*.pyo\n\nserver_restart.log\nworker.log\nmetrics.db\n"

_REQUIREMENTS_TEMPLATE = """speedtest-cli
pymupdf
httpx
qdrant-client
torch==2.2.2
fastapi
pydantic
sentence-transformers==3.4.1
transformers<5,>=4.57
langchain-ollama
langchain-openai
python-dotenv
langgraph
pymongo
sqlglot
motor
faster-whisper
beautifulsoup4
uvicorn
psutil
nvidia-ml-py3
python-multipart
piper-tts
websockets
torchaudio==2.2.2
"""


def validate_project_name(name: str, root_dir: str, existing_ids: set) -> str:
    """Returns an error message if `name` can't be used, or "" if it's fine."""
    if not name:
        return "Project name is required."
    if not NAME_PATTERN.match(name):
        return "Use lowercase letters, digits, and underscores only, starting with a letter (e.g. my_new_app)."
    if name in RESERVED_NAMES:
        return f"'{name}' is a reserved name."
    if name in existing_ids:
        return f"A project named '{name}' is already registered."
    if os.path.exists(os.path.join(root_dir, name)):
        return f"A directory named '{name}' already exists on disk."
    return ""


def next_available_port(existing_ports: list) -> int:
    return (max(existing_ports) + 1) if existing_ports else 8126


def title_case(name: str) -> str:
    return " ".join(word.capitalize() for word in name.split("_"))


def _symlink(target_relative: str, link_path: str):
    """Symlinks link_path -> target_relative. Falls back to a plain copy if
    the OS/account can't create symlinks (e.g. Windows without Developer
    Mode enabled or admin rights, WinError 1314) — the new project still
    works, it just won't auto-pick-up future edits to the common/ file
    until symlink support is enabled and the copy is manually replaced."""
    try:
        os.symlink(target_relative, link_path)
    except OSError:
        target_abs = os.path.normpath(os.path.join(os.path.dirname(link_path), target_relative))
        shutil.copy2(target_abs, link_path)


def scaffold_project(root_dir: str, name: str, label: str, port: int) -> None:
    """Creates the new project's directory tree. Raises on any failure —
    caller is responsible for not having already inserted a Mongo doc for
    it if this raises (see server.py's create_project endpoint, which
    validates first and only inserts after this returns successfully)."""
    project_dir = os.path.join(root_dir, name)
    project_title = label or title_case(name)

    os.makedirs(project_dir)
    os.makedirs(os.path.join(project_dir, "services"))
    os.makedirs(os.path.join(project_dir, "database"))
    os.makedirs(os.path.join(project_dir, "frontend", "css"))
    os.makedirs(os.path.join(project_dir, "frontend", "js"))

    open(os.path.join(project_dir, "services", "__init__.py"), "w", encoding="utf-8").close()
    open(os.path.join(project_dir, "database", "__init__.py"), "w", encoding="utf-8").close()

    with open(os.path.join(project_dir, "server.py"), "w", encoding="utf-8") as f:
        f.write(_SERVER_TEMPLATE.format(project_id=name, project_title=project_title, default_port=port))

    with open(os.path.join(project_dir, "ollamaagent2.py"), "w", encoding="utf-8") as f:
        f.write(_OLLAMAAGENT_TEMPLATE)

    with open(os.path.join(project_dir, "frontend", "js", "app-config.js"), "w", encoding="utf-8") as f:
        f.write(_APP_CONFIG_TEMPLATE.format(project_title=project_title))

    with open(os.path.join(project_dir, ".env"), "w", encoding="utf-8") as f:
        f.write(_ENV_TEMPLATE.format(project_id=name))

    with open(os.path.join(project_dir, ".gitignore"), "w", encoding="utf-8") as f:
        f.write(_GITIGNORE_TEMPLATE)

    with open(os.path.join(project_dir, "reqiuremnets.txt"), "w", encoding="utf-8") as f:
        f.write(_REQUIREMENTS_TEMPLATE)

    # services/pdf_rag.py + pdf_embed_worker.py, all frontend css/js besides
    # app-config.js, index.html, query-log.html, package.json(-lock) — all
    # symlinked straight to common/, same as ai_sayak_medical_up/river_cannel.
    _symlink("../../common/services/pdf_rag.py", os.path.join(project_dir, "services", "pdf_rag.py"))
    _symlink("../../common/services/pdf_embed_worker.py", os.path.join(project_dir, "services", "pdf_embed_worker.py"))

    for css_file in _SHARED_CSS_FILES:
        _symlink(f"../../../common/frontend/css/{css_file}", os.path.join(project_dir, "frontend", "css", css_file))
    for js_file in _SHARED_JS_FILES:
        _symlink(f"../../../common/frontend/js/{js_file}", os.path.join(project_dir, "frontend", "js", js_file))

    _symlink("../../common/frontend/index.html", os.path.join(project_dir, "frontend", "index.html"))
    _symlink("../../common/frontend/query-log.html", os.path.join(project_dir, "frontend", "query-log.html"))
    _symlink("../common/package.json", os.path.join(project_dir, "package.json"))
    _symlink("../common/package-lock.json", os.path.join(project_dir, "package-lock.json"))


_START_LINE_PATTERN = re.compile(r"^start\s+(\S+)\b")


def register_in_run_all(root_dir: str, name: str) -> bool:
    """Best-effort: appends a `start <name> <name>` line to run_all.sh
    (after the last existing `start ...` line) so the new project is
    picked up next time it runs. Returns False (without raising) if
    run_all.sh doesn't exist or has no `start` lines to anchor on — the
    project directory itself is already fully created and usable either
    way, this is just a convenience. Matches lines by regex rather than
    exact whitespace, so it doesn't break if run_all.sh's alignment ever
    changes."""
    run_all_path = os.path.join(root_dir, "run_all.sh")
    if not os.path.exists(run_all_path):
        return False

    with open(run_all_path, encoding="utf-8") as f:
        lines = f.readlines()

    last_start_idx = None
    for i, line in enumerate(lines):
        m = _START_LINE_PATTERN.match(line)
        if m:
            if m.group(1) == name:
                return True  # already registered (e.g. re-running after a partial failure)
            last_start_idx = i

    if last_start_idx is None:
        return False

    new_line = f"start {name:<20} {name}\n"
    lines.insert(last_start_idx + 1, new_line)
    with open(run_all_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return True


def unregister_from_run_all(root_dir: str, name: str) -> bool:
    """Best-effort: removes the `start <name> ...` line for this project
    from run_all.sh. Returns True if the line was found and removed,
    False if run_all.sh doesn't exist or the project wasn't in it."""
    run_all_path = os.path.join(root_dir, "run_all.sh")
    if not os.path.exists(run_all_path):
        return False

    with open(run_all_path, encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = [l for l in lines if not (_START_LINE_PATTERN.match(l) and _START_LINE_PATTERN.match(l).group(1) == name)]
    if len(new_lines) == len(lines):
        return False

    with open(run_all_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    return True
