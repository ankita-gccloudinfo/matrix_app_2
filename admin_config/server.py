"""Project Config Admin — a small standalone service (port 8122) for
managing per-project configuration (Qdrant host/collection, MySQL, LLM
backend, LiveAvatar, ...) for matrix_app, ai_sayak_medical_up, and
river_cannel, instead of hand-editing each app's .env/hardcoded values.

Each of those apps calls common/project_config.py's apply_project_config()
at startup, which reads the project's doc from the same `project_admin.
project_config` MongoDB collection this service writes to, and injects it
into os.environ before that app's own config-reading modules import — so a
saved change here takes effect the next time the target app is restarted.

Deliberately NOT built on common/routes.py — this manages infrastructure
credentials for every other project, so it gets its own real password-based
login (see auth.py) rather than the other apps' name-only "who's asking"
login.

Also owns and runs the Matrix VM Monitor subprocess (vm_monitor_service.py,
moved here from matrix_app/) — a system-resource dashboard (CPU/RAM/GPU/
disk/network) that isn't tied to any one chatbot project's lifecycle, so it
belongs on the one service meant to always be running. See start_vm_monitor()
below and GET /api/vm-monitor/status.
"""
import json
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional

import pymupdf as fitz  # pymupdf — text-only extraction here, no OCR/embedding: this
             # service just needs enough text to hand the LLM a summary, not
             # the full ingestion pipeline common/services/pdf_rag.py runs.
from html import escape as html_escape
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dotenv import load_dotenv
load_dotenv()

import httpx
import pymongo

from auth import hash_password, verify_password
import scaffold

ADMIN_MONGO_URI = os.getenv("ADMIN_MONGO_URI", os.getenv("MONGO_URI", "mongodb://localhost:27017"))
_client = pymongo.MongoClient(ADMIN_MONGO_URI)
_db = _client["project_admin"]
admin_users = _db["admin_users"]
project_config = _db["project_config"]
projects_collection = _db["projects"]
demos_collection = _db["demos"]

# Same vLLM OpenAI-compatible backend every scaffolded chatbot's
# ollamaagent2.py talks to by default (see scaffold.py's
# _OLLAMAAGENT_TEMPLATE) — reused here purely to draft the throwaway demo
# preview HTML below, not to run a real chatbot.
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://100.98.23.74:2211/v1")
VLLM_MODEL_NAME = os.getenv("VLLM_MODEL_NAME", "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY")

# Parent directory of admin_config/ — every project this service manages
# lives as a sibling directory here (matrix_app/, ai_sayak_medical_up/,
# river_cannel/, and anything created via POST /api/projects).
ROOT_DIR = os.path.dirname(os.path.abspath(__file__)) + "/.."
ROOT_DIR = os.path.normpath(ROOT_DIR)

# The 3 apps this panel started out managing — seeded into `projects` on
# first run only (see _seed_projects below). After that, the `projects`
# collection is the source of truth, so newly-created projects (see
# POST /api/projects) show up here too without a code change.
_SEED_PROJECTS = [
    {"_id": "matrix_app", "label": "Matrix App (Police Intel)", "port": 8123},
    {"_id": "ai_sayak_medical_up", "label": "AI Sayak Medical (Doctor Intel)", "port": 8124},
    {"_id": "river_cannel", "label": "River Cannel", "port": 8125},
]


def _seed_projects():
    if projects_collection.count_documents({}) == 0:
        projects_collection.insert_many(_SEED_PROJECTS)


_seed_projects()


def _known_project_ids() -> set:
    return {doc["_id"] for doc in projects_collection.find({}, {"_id": 1})}


# ── VM Monitor: runs as its own subprocess (own port, own psutil/SQLite
# background thread) — moved here from matrix_app/server.py so system-level
# VM monitoring isn't tied to any single chatbot project's lifecycle. This
# admin service is the one thing meant to always be running, so it's the
# natural owner: it only spawns vm_monitor_service.py, health-checks it, and
# stops it — the dashboard/API (see GET /api/vm-monitor/status below and the
# frontend's iframe) talk to it directly on its own port.
_VM_MONITOR_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vm_monitor_service.py")
_VM_MONITOR_PORT = 8790
# vm_monitor_service.py serves HTTPS with a self-signed cert whenever one is
# present alongside it (same convention matrix_app/server.py uses for its
# own HTTPS) — the health check and dashboard iframe both need to speak
# whichever scheme it's actually using.
_VM_MONITOR_CERT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cert.pem")
_VM_MONITOR_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "key.pem")
_VM_MONITOR_HAS_TLS_CERT = os.path.exists(_VM_MONITOR_CERT_PATH) and os.path.exists(_VM_MONITOR_KEY_PATH)
_VM_MONITOR_URL = f"{'https' if _VM_MONITOR_HAS_TLS_CERT else 'http'}://127.0.0.1:{_VM_MONITOR_PORT}"
_vm_monitor_process = None


def _vm_monitor_healthy() -> bool:
    try:
        r = httpx.get(f"{_VM_MONITOR_URL}/health", timeout=2, verify=False)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def start_vm_monitor(startup_timeout: int = 30):
    """Spawn the VM Monitor subprocess if it isn't already running, and block
    until it reports healthy. Call once at server startup."""
    global _vm_monitor_process

    if _vm_monitor_healthy():
        print("📊 VM Monitor already running.")
        return

    print("📊 Starting VM Monitor service...")
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vm_monitor.log")
    log_file = open(log_path, "a")
    env = {**os.environ, "VM_MONITOR_PORT": str(_VM_MONITOR_PORT)}
    _vm_monitor_process = subprocess.Popen(
        [sys.executable, _VM_MONITOR_SCRIPT],
        stdout=log_file, stderr=subprocess.STDOUT, env=env,
    )

    deadline = time.time() + startup_timeout
    while time.time() < deadline:
        if _vm_monitor_healthy():
            print(f"📊 VM Monitor ready on {_VM_MONITOR_URL}")
            return
        if _vm_monitor_process.poll() is not None:
            print(f"⚠️ VM Monitor exited early — see {log_path}")
            return
        time.sleep(1)

    print(f"⚠️ VM Monitor did not become healthy within {startup_timeout}s — see {log_path}")


def stop_vm_monitor():
    if _vm_monitor_process and _vm_monitor_process.poll() is None:
        _vm_monitor_process.terminate()


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_vm_monitor()
    yield
    stop_vm_monitor()


app = FastAPI(title="Project Config Admin", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSION_COOKIE_NAME = "admin_sid"
# In-memory session store — same pattern the other apps use for PDF session
# state (see common/routes.py's SessionState/_sessions). Fine for a
# single-operator local admin tool; sessions reset on service restart.
_sessions: Dict[str, str] = {}  # sid -> username


def get_current_admin(request: Request) -> Optional[str]:
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if not sid:
        return None
    return _sessions.get(sid)


def require_admin(request: Request) -> str:
    username = get_current_admin(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not logged in.")
    return username


# ── Auth: bootstrap-only registration + real login ──────────────────────
class RegisterRequest(BaseModel):
    username: str
    password: str


@app.get("/api/admin/bootstrap-needed")
async def bootstrap_needed():
    return {"needed": admin_users.count_documents({}) == 0}


@app.post("/api/admin/register")
async def register(req: RegisterRequest):
    """Bootstrap-only: creates the first (and, for this single-operator
    tool, expected-to-be-only) admin account. Always 403s once one exists —
    this is not a multi-tenant signup flow."""
    if admin_users.count_documents({}) > 0:
        raise HTTPException(status_code=403, detail="An admin account already exists.")
    username = req.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required.")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    admin_users.insert_one({
        "_id": username,
        "password_hash": hash_password(req.password),
        "created_at": datetime.now(),
    })
    return {"status": "created"}


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/admin/login")
async def login(req: LoginRequest, response: Response):
    doc = admin_users.find_one({"_id": req.username.strip()})
    if not doc or not verify_password(req.password, doc.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = doc["_id"]
    response.set_cookie(SESSION_COOKIE_NAME, sid, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return {"status": "logged_in", "username": doc["_id"]}


@app.get("/api/admin/me")
async def me(request: Request):
    username = get_current_admin(request)
    if not username:
        return {"logged_in": False}
    return {"logged_in": True, "username": username}


@app.post("/api/admin/logout")
async def logout(request: Request, response: Response):
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if sid:
        _sessions.pop(sid, None)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "logged_out"}


# ── Per-project config CRUD ──────────────────────────────────────────────
@app.get("/api/projects")
async def list_projects(request: Request):
    require_admin(request)
    docs = list(projects_collection.find().sort("port", 1))
    return {"projects": [{"id": d["_id"], "label": d["label"], "port": d["port"]} for d in docs]}


class CreateProjectRequest(BaseModel):
    name: str
    label: Optional[str] = None


def _create_project(name: str, label: str) -> dict:
    """Shared by POST /api/projects and the demo-promote flow below.
    Validates, scaffolds the directory (see scaffold.py), registers it in
    run_all.sh, and records it in `projects`. Raises HTTPException on any
    failure — caller must not have inserted a projects doc yet if this
    raises."""
    error = scaffold.validate_project_name(name, ROOT_DIR, _known_project_ids())
    if error:
        raise HTTPException(status_code=400, detail=error)

    existing_ports = [d["port"] for d in projects_collection.find({}, {"port": 1})]
    port = scaffold.next_available_port(existing_ports)

    try:
        scaffold.scaffold_project(ROOT_DIR, name, label, port)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create project files: {e}")

    added_to_run_all = scaffold.register_in_run_all(ROOT_DIR, name)

    projects_collection.insert_one({"_id": name, "label": label, "port": port, "created_at": datetime.now()})

    return {
        "status": "created",
        "project": {"id": name, "label": label, "port": port},
        "added_to_run_all": added_to_run_all,
    }


@app.post("/api/projects")
async def create_project(req: CreateProjectRequest, request: Request):
    """Scaffolds a brand-new project directory (see scaffold.py) — the same
    blank-skeleton shape as river_cannel — and registers it so it shows up
    in the nav immediately. You still need to start it yourself (it's added
    to run_all.sh automatically when possible)."""
    require_admin(request)
    name = req.name.strip()
    label = (req.label or "").strip() or scaffold.title_case(name)
    return _create_project(name, label)


_PROTECTED_PROJECTS = {"matrix_app", "ai_sayak_medical_up", "river_cannel", "admin_config"}


class DeleteProjectRequest(BaseModel):
    password: str


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, req: DeleteProjectRequest, request: Request):
    """Unregisters a project from the admin panel. Requires the admin's
    password as a second factor — prevents accidental deletion. The project
    folder on disk is NOT removed (do that manually if needed); only the
    MongoDB registration and run_all.sh entry are removed."""
    username = require_admin(request)

    if project_id in _PROTECTED_PROJECTS:
        raise HTTPException(status_code=403, detail=f"'{project_id}' is a protected project and cannot be deleted.")

    admin_doc = admin_users.find_one({"_id": username})
    if not admin_doc or not verify_password(req.password, admin_doc.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Incorrect password.")

    doc = projects_collection.find_one({"_id": project_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found.")

    projects_collection.delete_one({"_id": project_id})
    project_config.delete_one({"_id": project_id})

    removed_from_run_all = scaffold.unregister_from_run_all(ROOT_DIR, project_id)

    return {
        "status": "deleted",
        "project_id": project_id,
        "removed_from_run_all": removed_from_run_all,
        "note": "Project folder on disk was NOT removed — delete it manually if needed.",
    }


# ── Demo preview generation ──────────────────────────────────────────────
# "Demo" is a cheap, disposable step before committing to a real project:
# the admin describes a theme + feature list, we ask the LLM for a
# full government-portal-style landing page (cards, auto-generated questions,
# themed colors) and show it in an iframe. On "Promote", _create_project()
# scaffolds the project directory and the generated HTML is saved as
# mainindex.html — served at / by the new project's server. ollamaagent2.py
# is still always hand-written afterward — a demo never generates real chat
# logic, only the landing page.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_CODE_FENCE = re.compile(r"^```(?:html)?\s*\n?|\n?```\s*$", re.MULTILINE)


def _build_demo_prompt(name: str, theme: str, features: List[str], sample_questions: List[str]) -> str:
    feature_list = "\n".join(f"- {f}" for f in features) or "- General Q&A chat"
    if sample_questions:
        questions_hint = "Use these as inspiration for the question chips on the cards:\n" + "\n".join(f"- {q}" for q in sample_questions)
    else:
        questions_hint = "Invent 3 realistic sample questions per card, relevant to each feature."
    return f"""Generate a single self-contained HTML landing page for a government-style AI chatbot portal called "{name}".

Theme / vertical: {theme or "general purpose"}

Features (create one card per feature):
{feature_list}

{questions_hint}

Design requirements (follow EXACTLY):

1. HEADER:
   - 5px top stripe in theme accent color (gradient left to right)
   - White header bar: circular conic-gradient emblem showing initials, bold app title "{name}" in Baloo 2, muted subtitle

2. HERO SECTION:
   - Centered heading "Welcome to {name}"
   - One sentence describing what this portal does, in muted gray

3. CARDS GRID (most important — do this carefully):
   - CSS grid: 2 columns on desktop, 1 column on mobile (max-width 640px)
   - One card per feature. Each card must have:
     a. Large emoji icon (relevant to that specific feature topic)
     b. Card title: the feature name, bold, 16px
     c. Exactly 3 SPECIFIC questions — NOT generic. Questions must be directly about the feature topic.
        Example for "Vehicle Registration": "How do I renew my vehicle RC?", "What documents are needed for registration?", "How long does registration take?"
        Example for "Health Records": "How can I access my medical history?", "Where can I get my vaccination certificate?", "How do I link Aadhar with health records?"
        Style questions as pill chips: light gray background (#F1F3F5), border-radius 20px, padding 6px 14px, font-size 13px, cursor pointer, hover darkens slightly.
     d. A "Start Chat →" button: full width, href="/chat", background in theme primary color, white text, border-radius 24px, padding 11px 0

4. FLOATING AVATAR WIDGET (required — add this):
   - A circular floating button fixed at bottom-right (right:24px, bottom:24px, z-index:100)
   - Size: 58px × 58px, border-radius 50%, background: theme primary color, white shadow
   - Contains a face emoji (🧑‍⚕️ for health, 👮 for police, 🚗 for transport, 🤖 for default)
   - On click (JavaScript onclick): toggles an overlay panel above it
   - Overlay panel (position:fixed, bottom:94px, right:24px, width:280px):
     * Dark header bar with avatar name "AI Assistant" and green "● Online" dot
     * Avatar face circle (72px, gradient background, emoji centered)
     * Status text: "Ready to help you"
     * A row of 2 quick-question chips (clickable chips that link to /chat)
     * A "Start Conversation →" button linking to /chat
     * A close ✕ button top-right of the overlay

5. FOOTER: centered, muted, "{name} © 2025 | Powered by AI"

6. COLORS — pick based on theme "{theme or 'general'}":
   - health/medical/doctor → primary:#1F6F5C, accent:#FF9933, bg:#F8F9FA
   - police/security/intel/crime → primary:#12233D, accent:#FF9933, bg:#F4F6F9
   - transport/vehicle/parivahan/driving → primary:#1A4B8C, accent:#E87722, bg:#F5F7FA
   - legal/law/court/justice → primary:#1B4332, accent:#C9A84C, bg:#F9F8F4
   - education/school/student → primary:#7C3AED, accent:#F59E0B, bg:#FAFAF8
   - default/general → primary:#3730A3, accent:#F59E0B, bg:#F8F9FA

7. FONTS: <link href="https://fonts.googleapis.com/css2?family=Hind:wght@400;500;600&family=Baloo+2:wght@500;600;700&display=swap" rel="stylesheet">

8. Card hover: box-shadow deepens, transform translateY(-3px), transition 0.2s ease

9. JavaScript allowed — only for the avatar toggle (onclick show/hide the overlay panel)

10. Output ONLY raw HTML starting with <!DOCTYPE html>. No markdown fences, no explanation."""


async def _call_demo_llm(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=180) as client:
        try:
            resp = await client.post(
                f"{VLLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
                json={
                    "model": VLLM_MODEL_NAME,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": 8000,  # a page with many feature cards produces long HTML — avoid mid-page truncation
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Demo generation failed talking to the LLM backend: {e}")

    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise HTTPException(status_code=502, detail="LLM backend returned an unexpected response shape.")

    text = _THINK_BLOCK.sub("", text).strip()
    text = _CODE_FENCE.sub("", text).strip()
    return text


# ── PDF → demo structure analysis ────────────────────────────────────────
# Lets the admin skip filling the demo form by hand: upload a document, an
# LLM reads it and proposes the same {name, theme, pages[]} shape
# /api/demos/generate already expects, the admin reviews/edits it in the
# form, then clicks "Generate preview" same as any hand-filled demo — this
# endpoint only proposes, it never calls the LLM twice or generates HTML.
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
_PDF_TEXT_CHAR_LIMIT = 48000


def _build_pdf_analysis_prompt(text_excerpt: str) -> str:
    return f"""You are analyzing a document to design a multi-portal AI chatbot demo.

DOCUMENT EXCERPT (may be truncated):
---
{text_excerpt}
---

Based on this document, decide:
1. A short lowercase project name (letters, digits, underscores only, e.g. "health_dept") that fits the document's subject.
2. A one or two word theme (e.g. "health", "police", "transport", "legal", "education", "general").
3. How many distinct portal pages this chatbot needs (1 to 3). Base this ONLY on whether the document actually serves multiple distinct audiences or purposes (e.g. a citizen-facing part and a separate officer/internal part). Most documents only need 1 page — only propose 2 or 3 if the content clearly supports separate audiences or sections.
4. For each page: a short name, and EVERY distinct major feature/capability actually described in the document as its own separate feature — do not artificially limit the count to a small number. If the document describes 10, 15, or more distinct capabilities/sections, list all of them separately rather than collapsing them into a handful of generic groups. Only merge sub-bullets together when they are clearly part of the exact same capability. Also give 4 to 8 sample questions a real user could ask about that page's content, grounded in specifics from the document (names, numbers, procedures actually mentioned).

Output ONLY a single JSON object, no markdown fences, no explanation, in exactly this shape:
{{
  "name": "project_slug",
  "theme": "one or two words",
  "pages": [
    {{
      "name": "Page Name",
      "features": ["feature 1", "feature 2"],
      "sample_questions": ["question 1", "question 2"]
    }}
  ]
}}"""


@app.post("/api/demos/analyze-pdf")
async def analyze_demo_pdf(request: Request, file: UploadFile = File(...)):
    require_admin(request)
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    file_bytes = await file.read()
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        try:
            texts = []
            total_chars = 0
            for page in doc:
                page_text = page.get_text()
                texts.append(page_text)
                total_chars += len(page_text)
                if total_chars >= _PDF_TEXT_CHAR_LIMIT:
                    break
            full_text = "\n\n".join(texts).strip()
        finally:
            doc.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {e}")

    if not full_text:
        raise HTTPException(status_code=400, detail="No extractable text found in this PDF — it may be a scanned/image-only document.")

    prompt = _build_pdf_analysis_prompt(full_text[:_PDF_TEXT_CHAR_LIMIT])
    raw = await _call_demo_llm(prompt)

    match = _JSON_BLOCK.search(raw)
    if not match:
        raise HTTPException(status_code=502, detail="The AI could not analyze this document. Try again.")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="The AI returned an unreadable analysis. Try again.")

    name = re.sub(r"[^a-z0-9_]", "_", (parsed.get("name") or "demo").strip().lower()).strip("_") or "demo"
    theme = (parsed.get("theme") or "").strip()

    pages_out = []
    for p in (parsed.get("pages") or [])[:3]:
        pages_out.append({
            "name": (p.get("name") or "Portal").strip()[:60],
            "features": [f.strip() for f in (p.get("features") or []) if f.strip()][:20],
            "sample_questions": [q.strip() for q in (p.get("sample_questions") or []) if q.strip()][:8],
        })
    if not pages_out:
        pages_out = [{"name": "Main Portal", "features": [], "sample_questions": []}]

    return {"name": name, "theme": theme, "pages": pages_out, "source_filename": file.filename}


class PageSpec(BaseModel):
    name: str
    slug: str
    features: Optional[List[str]] = None
    sample_questions: Optional[List[str]] = None


class GenerateDemoRequest(BaseModel):
    name: str
    theme: Optional[str] = None
    pages: Optional[List[PageSpec]] = None


# Shared across the mainindex prompt and the subpage template so a theme
# always maps to the same (primary, accent, bg, avatar_emoji) regardless of
# which one is rendering it.
_THEME_COLOR_MAP = {
    "health": ("#1F6F5C", "#FF9933", "#F8F9FA", "🧑‍⚕️"),
    "medical": ("#1F6F5C", "#FF9933", "#F8F9FA", "🧑‍⚕️"),
    "police": ("#12233D", "#FF9933", "#F4F6F9", "👮"),
    "security": ("#12233D", "#FF9933", "#F4F6F9", "👮"),
    "transport": ("#1A4B8C", "#E87722", "#F5F7FA", "🚗"),
    "vehicle": ("#1A4B8C", "#E87722", "#F5F7FA", "🚗"),
    "legal": ("#1B4332", "#C9A84C", "#F9F8F4", "⚖️"),
    "education": ("#7C3AED", "#F59E0B", "#FAFAF8", "📚"),
}
_DEFAULT_THEME_COLORS = ("#3730A3", "#F59E0B", "#F8F9FA", "🤖")


def _theme_colors(theme: str):
    theme_key = next((k for k in _THEME_COLOR_MAP if k in (theme or "").lower()), None)
    return _THEME_COLOR_MAP.get(theme_key, _DEFAULT_THEME_COLORS)


def _build_mainindex_prompt(name: str, theme: str, pages: List[PageSpec]) -> str:
    portals = "\n".join(
        f"- Portal {i+1}: name=\"{p.name}\", slug=\"{p.slug}\", links to /{p.slug}.html"
        for i, p in enumerate(pages)
    )
    colors = _theme_colors(theme)

    return f"""Generate a self-contained HTML gateway/landing page for "{name}" — a government AI portal hub.

Theme: {theme or "general"}

Portals to show (one large clickable card per portal):
{portals}

Design (follow EXACTLY):
1. HEADER: 5px top stripe (accent color gradient). White header bar with circular conic-gradient emblem (initials), bold title "{name}" in Baloo 2 font, muted subtitle.

2. MAIN SECTION: Centered heading "Welcome to {name}" + one descriptive sentence in muted gray.

3. PORTAL CARDS LAYOUT:
   - Flex row, centered, gap 32px, wrap on mobile
   - One card per portal. Each card (min-width 280px, max-width 340px):
     * Full card is clickable → onclick navigates to that portal's own page, using the slug listed for it above (e.g. onclick="window.location.href='/PORTAL_SLUG.html'")
     * Large emoji icon at top center (60px, relevant to portal purpose)
     * Portal name bold 20px
     * 2-line description of what this portal is for
     * A colored pill badge showing portal type (e.g. "Public Access" or "Officer Login")
     * "Enter Portal →" button: theme primary color, white text, full width, border-radius 24px
     * Card: white bg, border-radius 16px, box-shadow, padding 32px 24px, hover lifts (translateY -4px)

4. FLOATING AVATAR WIDGET (bottom-right, fixed):
   - 58px circle, theme primary color bg, white emoji {colors[3]}, box-shadow
   - onclick toggles an overlay panel above it (position fixed, bottom 94px, right 24px, width 280px, border-radius 16px, white bg, shadow)
   - Overlay: dark header with "AI Assistant" + green ● Online dot, avatar face circle (72px gradient), "How can I help you?", 2 quick-link chips → href="/{pages[0].slug}.html", a "Start Conversation →" button → href="/{pages[0].slug}.html", ✕ close button

5. FOOTER: centered muted "{name} © 2025 | Powered by AI"

6. COLORS: primary {colors[0]}, accent {colors[1]}, page bg {colors[2]}

7. FONTS: <link href="https://fonts.googleapis.com/css2?family=Hind:wght@400;500;600&family=Baloo+2:wght@500;600;700&display=swap" rel="stylesheet">

8. JavaScript: only for avatar toggle (show/hide overlay)

9. Output ONLY raw HTML starting with <!DOCTYPE html>. No markdown, no explanation."""


# ── Subpage cards: template + data, one LLM call PER CARD ──────────────────
# Each subpage's HTML/CSS is a FIXED, hand-written template (below). Instead
# of one LLM call returning every card on a page at once, each feature gets
# its OWN focused LLM call — a prompt asked to fill in 20 features at once
# produces shallow, repetitive content; asked about one feature at a time it
# can go deep, matching the module-detail depth in
# ai_sayak_medical_up/health-command-centre.html (AI Prediction / What's
# Wrong / What's Normal / AI Benefit / Data Source / What It Does / Benefit).
# Calls run in parallel (capped by a semaphore, see generate_demo) and the
# fixed template renders the resulting data into .card elements plus a
# click-through detail panel per card — layout stays consistent no matter
# how many cards a page has, and the LLM only ever returns small JSON.
_CARD_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _build_single_card_prompt(app_name: str, theme: str, page_name: str,
                               feature: str, sample_questions_hint: List[str]) -> str:
    if sample_questions_hint:
        q_hint = "Use these as inspiration if one is relevant to this specific feature:\n" + "\n".join(f"- {q}" for q in sample_questions_hint)
    else:
        q_hint = "Invent realistic questions grounded in this feature's actual topic."

    return f"""You are writing detailed analytical briefing content for ONE card on a government AI portal page called "{page_name}", part of "{app_name}".

Theme: {theme or "general"}

The feature this card covers: "{feature}"

{q_hint}

Write this like a real analytics-module briefing for a senior officer — concrete and specific to this exact feature, not generic filler. Illustrative sample numbers/district names/percentages are fine (this is a demo), but they must read as plausible and specific, not vague.

IMPORTANT — everything must be BILINGUAL. Every text field below must be an object with an "en" (English) key and a "hi" (Hindi, Devanagari script — a natural, fluent translation, not a literal word-for-word one) key. The "hi" text must express the exact same meaning and the exact same illustrative numbers/facts as the "en" text — never leave "hi" blank or a placeholder. The "icon" field is the only exception (a single emoji, not bilingual).

Produce a JSON object with these exact fields:
- "title": {{"en": "...", "hi": "..."}} — short card title (3-6 words), cleaned up from the feature name
- "icon": one single relevant emoji (not bilingual)
- "tagline": {{"en": "...", "hi": "..."}} — one short sentence (under 15 words) summarizing what this feature does
- "data_source": {{"en": "...", "hi": "..."}} — one sentence naming the illustrative systems/data feeds this module would draw from
- "what_it_does": {{"en": "...", "hi": "..."}} — 1-2 sentences describing what this module tracks or computes
- "benefit": {{"en": "...", "hi": "..."}} — one sentence on why this matters / what problem it solves for the reader
- "ai_prediction": {{"en": "...", "hi": "..."}} — one sentence — a forward-looking, predictive insight this module would surface
- "whats_wrong": {{"en": "...", "hi": "..."}} — one sentence — the most notable outlier/problem this module would currently flag
- "whats_normal": {{"en": "...", "hi": "..."}} — one sentence — what's currently operating within normal/expected range
- "ai_benefit": {{"en": "...", "hi": "..."}} — one sentence — the concrete time/effort saved by automating this
- "qa": AT LEAST 30 question/answer pairs, each pair having a bilingual "q" (question) and a bilingual "a" (answer), for a real user asking about this feature. Each answer must be a concrete, specific, illustrative sample answer (numbers/district names/percentages — plausible for a demo, not vague), and the "en" and "hi" version of the same pair must express the exact same numbers/facts. Cover real variety, not near-duplicates — different angles such as: current status/counts, trends over time, comparisons (district/entity/period vs. period), specific named entities, exceptions/outliers, causes, thresholds, forecasts, and process/how-to questions. Every pair must be grounded in this feature's actual topic, not generic. These pairs work like a small instant bilingual knowledge base for this card — each answer must stand alone and make sense without any other context, in either language.

Output ONLY a single JSON object, no markdown fences, no explanation, in exactly this shape:
{{
  "title": {{"en": "...", "hi": "..."}}, "icon": "...", "tagline": {{"en": "...", "hi": "..."}},
  "data_source": {{"en": "...", "hi": "..."}}, "what_it_does": {{"en": "...", "hi": "..."}}, "benefit": {{"en": "...", "hi": "..."}},
  "ai_prediction": {{"en": "...", "hi": "..."}}, "whats_wrong": {{"en": "...", "hi": "..."}}, "whats_normal": {{"en": "...", "hi": "..."}}, "ai_benefit": {{"en": "...", "hi": "..."}},
  "qa": [
    {{"q": {{"en": "...", "hi": "..."}}, "a": {{"en": "...", "hi": "..."}}}},
    {{"q": {{"en": "...", "hi": "..."}}, "a": {{"en": "...", "hi": "..."}}}}
  ]
}}
(qa must have at least 30 entries)"""


def _parse_single_card_data(raw: str, fallback_title: str) -> dict:
    match = _CARD_JSON_BLOCK.search(raw)
    parsed = {}
    if match:
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}

    def _bilingual(value, limit: int = 400, fallback: str = "") -> dict:
        """Every text field is {"en", "hi"} from the LLM. If it came back as
        a plain string instead (model didn't follow the shape), use it for
        both languages rather than dropping the content."""
        if isinstance(value, dict):
            en = (value.get("en") or fallback or "").strip()[:limit]
            hi = (value.get("hi") or en).strip()[:limit]
            return {"en": en, "hi": hi}
        text = (str(value).strip() if value else fallback).strip()[:limit]
        return {"en": text, "hi": text}

    def _field(key: str, limit: int = 400) -> dict:
        return _bilingual(parsed.get(key), limit)

    qa_out = []
    for item in (parsed.get("qa") or []):
        if not isinstance(item, dict):
            continue
        q = _bilingual(item.get("q"), 220)
        a = _bilingual(item.get("a"), 600)
        if q["en"] and a["en"]:
            qa_out.append({"q": q, "a": a})
    qa_out = qa_out[:50]

    return {
        "title": _bilingual(parsed.get("title"), 80, fallback_title),
        "icon": (parsed.get("icon") or "✨").strip()[:8],
        "tagline": _field("tagline", 160),
        "data_source": _field("data_source"),
        "what_it_does": _field("what_it_does"),
        "benefit": _field("benefit"),
        "ai_prediction": _field("ai_prediction"),
        "whats_wrong": _field("whats_wrong"),
        "whats_normal": _field("whats_normal"),
        "ai_benefit": _field("ai_benefit"),
        "qa": qa_out,
    }


# Placeholder tokens (no braces) rather than an f-string/.format() — this
# template is mostly CSS/JS full of literal { } braces, and f-string brace
# escaping across a block this size is exactly what caused a NameError here
# before (see git history). Plain .replace() calls sidestep that class of bug.
_SUBPAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__PAGE_NAME__ — __APP_NAME__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Hind:wght@400;500;600&family=Baloo+2:wght@500;600;700&family=Noto+Sans+Devanagari:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    --primary: __PRIMARY__;
    --accent: __ACCENT__;
    --bg: __BG__;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: 'Hind', 'Noto Sans Devanagari', sans-serif;
    background: var(--bg);
    color: #1a1a1a;
  }
  .stripe { height: 5px; background: linear-gradient(90deg, var(--accent), var(--primary)); }
  header {
    background: #fff;
    padding: 14px 24px;
    display: flex;
    align-items: center;
    gap: 14px;
    border-bottom: 1px solid #E5E7EB;
  }
  .back-link { color: #6B7280; text-decoration: none; font-size: 13px; font-weight: 600; }
  .header-title { display: flex; flex-direction: column; flex: 1; }
  .header-title b { font-family: 'Baloo 2', 'Noto Sans Devanagari', sans-serif; font-size: 17px; color: #111827; }
  .header-title span { font-size: 12px; color: #6B7280; }
  .lang-toggle {
    display: flex; align-items: center; background: #F1F3F5; border-radius: 20px; padding: 3px; gap: 2px; flex-shrink: 0;
  }
  .lang-toggle button {
    background: none; border: none; font-size: 12px; font-weight: 700; color: #6B7280;
    padding: 5px 12px; border-radius: 16px; cursor: pointer; font-family: inherit;
  }
  .lang-toggle button.active { background: #fff; color: #111827; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .hero { text-align: center; padding: 40px 20px 24px; }
  .hero h1 { font-family: 'Baloo 2', 'Noto Sans Devanagari', sans-serif; font-size: 28px; margin: 0 0 8px; color: #111827; }
  .hero p { color: #6B7280; font-size: 15px; margin: 0; }
  .cards-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 20px;
    max-width: 960px;
    margin: 0 auto;
    padding: 0 24px 60px;
  }
  @media (max-width: 640px) { .cards-grid { grid-template-columns: 1fr; } }
  .card {
    background: #fff;
    border: 1px solid #E5E7EB;
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    display: flex;
    flex-direction: column;
    cursor: pointer;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
  }
  .card:hover { transform: translateY(-3px); box-shadow: 0 8px 20px rgba(0,0,0,0.1); }
  .card-icon { font-size: 40px; text-align: center; margin-bottom: 10px; }
  .card-title { font-weight: 700; font-size: 16px; text-align: center; margin-bottom: 6px; color: #111827; }
  .card-tagline { font-size: 12.5px; color: #6B7280; text-align: center; margin-bottom: 14px; line-height: 1.4; }
  .card-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; justify-content: center; }
  .chip {
    background: #F1F3F5; border-radius: 20px; padding: 6px 12px; font-size: 12px;
    cursor: pointer; transition: background 0.15s ease; white-space: nowrap; flex-shrink: 0;
  }
  .chip:hover { background: #E5E7EB; }
  /* Related-questions row in the detail modal can hold 30+ items — scrolls
     horizontally instead of wrapping into a very tall block. */
  .related-questions-scroll {
    display: flex; flex-wrap: nowrap; gap: 6px; overflow-x: auto;
    padding-bottom: 10px; margin-bottom: 20px; scrollbar-width: thin;
  }
  .related-questions-count { font-size: 11px; color: #9CA3AF; font-weight: 400; text-transform: none; margin-left: 6px; }
  .card-view-link {
    text-align: center; font-size: 12.5px; font-weight: 600; color: var(--primary);
    margin-bottom: 12px;
  }
  .card-cta {
    margin-top: auto; display: block; text-align: center; text-decoration: none;
    background: var(--primary); color: #fff; font-weight: 600; padding: 11px 0;
    border-radius: 24px; font-size: 14px; border: none; cursor: pointer; width: 100%;
    font-family: inherit;
  }

  /* ── Card detail overlay (opened by clicking a card) ──────────────── */
  .detail-overlay {
    position: fixed; inset: 0; background: rgba(17,24,39,0.55);
    display: none; align-items: flex-start; justify-content: center;
    padding: 40px 20px; overflow-y: auto; z-index: 200;
  }
  .detail-overlay.open { display: flex; }
  .detail-panel {
    background: #fff; border-radius: 20px; max-width: 720px; width: 100%;
    padding: 32px; position: relative; box-shadow: 0 20px 60px rgba(0,0,0,0.35);
  }
  .detail-close {
    position: absolute; top: 16px; right: 16px; background: #F1F3F5; border: none;
    width: 32px; height: 32px; border-radius: 50%; cursor: pointer; font-size: 15px; color: #374151;
  }
  .detail-header { display: flex; align-items: center; gap: 14px; margin-bottom: 4px; }
  .detail-icon { font-size: 36px; }
  .detail-title { font-family: 'Baloo 2', 'Noto Sans Devanagari', sans-serif; font-size: 21px; color: #111827; }
  .detail-tagline { color: #6B7280; font-size: 13.5px; margin: 6px 0 22px; }
  .detail-section-label {
    display: inline-flex; align-items: center; gap: 6px; background: var(--primary); color: #fff;
    font-size: 11px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
    padding: 5px 12px; border-radius: 20px; margin-bottom: 14px;
  }
  .detail-ai-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 24px; }
  @media (max-width: 560px) { .detail-ai-grid { grid-template-columns: 1fr; } }
  .ai-box { background: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 12px; padding: 14px; }
  .ai-box-label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase; margin-bottom: 6px; }
  .ai-box.prediction .ai-box-label { color: #B45309; }
  .ai-box.wrong .ai-box-label { color: #B91C1C; }
  .ai-box.normal .ai-box-label { color: #15803D; }
  .ai-box.benefit .ai-box-label { color: var(--primary); }
  .ai-box-text { font-size: 12.5px; color: #374151; line-height: 1.5; }
  .detail-related-label { font-size: 11px; font-weight: 700; color: #9CA3AF; text-transform: uppercase; margin-bottom: 8px; }
  .detail-cols { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 20px 0 26px; }
  @media (max-width: 640px) { .detail-cols { grid-template-columns: 1fr; } }
  .detail-col-label { font-size: 10.5px; font-weight: 700; color: var(--primary); text-transform: uppercase; margin-bottom: 6px; }
  .detail-col-text { font-size: 12.5px; color: #374151; line-height: 1.5; }

  /* ── Ask-this-card mini chat (instant Q&A first, /api/chat fallback) ── */
  .detail-chat { background: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 14px; padding: 14px; margin-bottom: 20px; }
  .detail-chat-thread { max-height: 220px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }
  .detail-chat-empty { font-size: 12px; color: #9CA3AF; font-style: italic; text-align: center; padding: 8px 0; }
  .chat-msg { max-width: 85%; padding: 8px 12px; border-radius: 14px; font-size: 12.5px; line-height: 1.45; word-break: break-word; }
  .chat-msg.user { align-self: flex-end; background: var(--primary); color: #fff; border-bottom-right-radius: 4px; }
  .chat-msg.bot { align-self: flex-start; background: #fff; border: 1px solid #E5E7EB; border-bottom-left-radius: 4px; color: #1a1a1a; }
  .chat-msg .chat-tag { display: block; font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em; opacity: 0.65; margin-bottom: 3px; }
  .detail-chat-row { display: flex; gap: 8px; }
  .detail-chat-input {
    flex: 1; padding: 9px 12px; border: 1px solid #E5E7EB; border-radius: 20px;
    font-size: 12.5px; font-family: inherit; outline: none;
  }
  .detail-chat-input:focus { border-color: var(--primary); }
  .detail-chat-send {
    background: var(--primary); color: #fff; border: none; border-radius: 20px;
    padding: 0 18px; font-size: 12.5px; font-weight: 600; cursor: pointer; font-family: inherit;
  }
  .detail-chat-mic {
    background: #F1F3F5; border: none; border-radius: 50%; width: 34px; height: 34px;
    font-size: 14px; cursor: pointer; flex-shrink: 0; transition: background 0.15s ease;
  }
  .detail-chat-mic:hover { background: #E5E7EB; }
  .detail-chat-mic.listening { background: #DC2626; animation: cardMicPulse 0.9s ease-in-out infinite; }
  .detail-chat-mic:disabled { opacity: 0.4; cursor: not-allowed; }
  @keyframes cardMicPulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(220,38,38,0.4); }
    50% { box-shadow: 0 0 0 10px rgba(220,38,38,0); }
  }
  .avatar-btn {
    position: fixed; right: 24px; bottom: 24px; width: 58px; height: 58px; border-radius: 50%;
    background: var(--primary); color: #fff; border: none; font-size: 26px; cursor: pointer;
    box-shadow: 0 6px 18px rgba(0,0,0,0.25); z-index: 100;
  }
  .avatar-overlay {
    position: fixed; right: 24px; bottom: 94px; width: 280px; background: #fff; border-radius: 16px;
    box-shadow: 0 12px 32px rgba(0,0,0,0.2); overflow: hidden; z-index: 100; display: none;
  }
  .avatar-overlay.open { display: block; }
  .avatar-overlay-header {
    background: #111827; color: #fff; padding: 14px 16px; display: flex; justify-content: space-between; align-items: center;
  }
  .avatar-overlay-header .name { font-weight: 600; font-size: 13.5px; }
  .avatar-overlay-header .online { font-size: 11px; color: #4ADE80; }
  .avatar-overlay-close { background: none; border: none; color: #fff; font-size: 16px; cursor: pointer; }
  .avatar-overlay-body { padding: 16px; text-align: center; }
  .avatar-face {
    width: 64px; height: 64px; border-radius: 50%; background: linear-gradient(135deg, var(--primary), var(--accent));
    display: flex; align-items: center; justify-content: center; font-size: 28px; margin: 0 auto 10px;
  }
  .avatar-status { font-size: 12px; color: #6B7280; margin-bottom: 14px; }
  .avatar-chip-row { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; margin-bottom: 14px; }
  .avatar-cta {
    display: block; text-decoration: none; background: var(--primary); color: #fff; font-weight: 600;
    padding: 10px 0; border-radius: 20px; font-size: 13px;
  }
  footer { text-align: center; padding: 20px; color: #9CA3AF; font-size: 12px; }
</style>
</head>
<body>
  <div class="stripe"></div>
  <header>
    <a class="back-link" href="/demo">← Back</a>
    <div class="header-title">
      <b>__APP_NAME__</b>
      <span>__PAGE_NAME__</span>
    </div>
    <div class="lang-toggle">
      <button type="button" id="langBtnEn" class="active" onclick="setLanguage('en')">EN</button>
      <button type="button" id="langBtnHi" onclick="setLanguage('hi')">HI</button>
    </div>
  </header>

  <div class="hero">
    <h1>__PAGE_NAME__</h1>
    <p id="heroDesc">__HERO_DESC__</p>
  </div>

  <div class="cards-grid" id="cardsGrid"></div>

  <div class="detail-overlay" id="detailOverlay" onclick="if(event.target===this) closeDetail()">
    <div class="detail-panel" id="detailPanel"></div>
  </div>

  <button class="avatar-btn" onclick="document.getElementById('avatarOverlay').classList.toggle('open')">__AVATAR_EMOJI__</button>
  <div class="avatar-overlay" id="avatarOverlay">
    <div class="avatar-overlay-header">
      <div>
        <div class="name" id="avatarName">__PAGE_NAME__ Assistant</div>
        <div class="online" id="avatarOnline">● Online</div>
      </div>
      <button class="avatar-overlay-close" onclick="document.getElementById('avatarOverlay').classList.remove('open')">✕</button>
    </div>
    <div class="avatar-overlay-body">
      <div class="avatar-face">__AVATAR_EMOJI__</div>
      <div class="avatar-status" id="avatarStatus">Ready to help you</div>
      <div class="avatar-chip-row" id="avatarChips"></div>
      <a class="avatar-cta" href="/chat" id="avatarCta">Start Chat →</a>
    </div>
  </div>

  <footer><span id="footerText">__APP_NAME__ — __PAGE_NAME__ © 2025 | Powered by AI</span></footer>

  <script>
    const CARDS = __CARDS_JSON__;
    const HERO_DESC = __HERO_JSON__;
    const FOOTER_TEXT = __FOOTER_JSON__;

    function escapeHtml(s) {
      const d = document.createElement('div');
      d.textContent = s == null ? '' : String(s);
      return d.innerHTML;
    }

    // ── Bilingual state — every LLM-authored text field is {en, hi}; t()
    // resolves it to the currently active language, falling back to
    // English if a translation is missing. Persisted like
    // ai_sayak_medical_up's mainindex.html/health-command-centre.html do —
    // wrapped in try/catch since localStorage throws instead of just being
    // absent in some contexts (private browsing, sandboxed iframes). ──
    function getSavedLang() {
      try { return localStorage.getItem('demoLang'); } catch (e) { return null; }
    }
    function saveLang(lang) {
      try { localStorage.setItem('demoLang', lang); } catch (e) {}
    }
    let currentLang = getSavedLang() || 'en';

    function t(field) {
      if (field == null) return '';
      if (typeof field === 'string') return field;
      return field[currentLang] || field.en || '';
    }

    const UI_STRINGS = {
      relatedQuestions: { en: 'Related Questions', hi: 'संबंधित प्रश्न' },
      scrollForMore: { en: 'questions — click one, or scroll for more', hi: 'प्रश्न — किसी पर क्लिक करें, या स्क्रॉल करें' },
      viewAnalysis: { en: 'View AI analysis →', hi: 'AI विश्लेषण देखें →' },
      startChat: { en: 'Start Chat →', hi: 'चैट शुरू करें →' },
      aiAnalysis: { en: '● AI Analysis', hi: '● AI विश्लेषण' },
      aiPrediction: { en: 'AI Prediction', hi: 'AI भविष्यवाणी' },
      whatsWrong: { en: "What's Wrong", hi: 'क्या गलत है' },
      whatsNormal: { en: "What's Normal", hi: 'क्या सामान्य है' },
      aiBenefit: { en: 'AI Benefit', hi: 'AI लाभ' },
      dataSource: { en: 'Data Source', hi: 'डेटा स्रोत' },
      whatItDoes: { en: 'What It Does', hi: 'यह क्या करता है' },
      benefit: { en: 'Benefit', hi: 'लाभ' },
      askPlaceholder: { en: 'Ask about', hi: 'इसके बारे में पूछें' },
      chatEmpty: { en: 'Ask a question about this card, or click one above.', hi: 'इस कार्ड के बारे में प्रश्न पूछें, या ऊपर किसी पर क्लिक करें।' },
      askBtn: { en: 'Ask', hi: 'पूछें' },
      assistant: { en: 'Assistant', hi: 'सहायक' },
      online: { en: '● Online', hi: '● ऑनलाइन' },
      readyToHelp: { en: 'Ready to help you', hi: 'आपकी मदद के लिए तैयार' },
      speakQuestion: { en: 'Speak your question', hi: 'अपना प्रश्न बोलें' },
      voiceNotSupported: { en: 'Voice input is not supported in this browser — try Chrome or Edge.', hi: 'इस ब्राउज़र में वॉइस इनपुट समर्थित नहीं है — Chrome या Edge आज़माएं।' },
      thinking: { en: 'Thinking…', hi: 'सोच रहा हूँ…' },
      knowledgeBase: { en: 'AI · Knowledge Base', hi: 'AI · ज्ञान भंडार' },
      relatedCard: { en: 'AI · Related Card', hi: 'AI · संबंधित कार्ड' },
      live: { en: 'AI · Live', hi: 'AI · लाइव' },
      error: { en: 'Error', hi: 'त्रुटि' },
      errorMsg: { en: 'Could not reach the AI backend right now.', hi: 'अभी AI बैकएंड से संपर्क नहीं हो सका।' },
      crossPrefix: { en: 'This looks related to', hi: 'यह इससे संबंधित लगता है' },
      crossSuffix: { en: 'instead — but here’s the answer:', hi: 'बल्कि — लेकिन यहाँ उत्तर है:' },
    };

    // ── Fuzzy Q&A matching — same approach as ai_sayak_medical_up's
    // health-command-centre.html: normalize + word-overlap scoring against
    // each card's own qa list first, then every OTHER card's qa list on
    // this page, before ever falling back to the real /api/chat backend.
    // Matching always happens against the CURRENTLY active language's text
    // (t(turn.q)) — a Hindi-speaking user typing/speaking Hindi matches
    // against the Hindi question text, an English one against English. ──
    function normalizeText(text) {
      return String(text)
        .toLowerCase()
        .replace(/[।?,!.—\-:;'"()]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    }

    function matchScore(input, trained) {
      const inputWords = input.split(' ').filter(w => w.length > 1);
      const trainedWords = trained.split(' ').filter(w => w.length > 1);
      if (!inputWords.length || !trainedWords.length) return 0;
      let matchCount = 0;
      for (const word of inputWords) {
        if (trainedWords.some(tw => tw.includes(word) || word.includes(tw))) matchCount++;
      }
      return matchCount / Math.max(inputWords.length, trainedWords.length);
    }

    function bestOwnScore(cardIdx, normalizedInput) {
      const qa = (CARDS[cardIdx] || {}).qa || [];
      let best = 0;
      for (const turn of qa) {
        const score = matchScore(normalizedInput, normalizeText(t(turn.q)));
        if (score > best) best = score;
      }
      return best;
    }

    // Exact match returns instantly; otherwise the best-scoring turn wins
    // if it clears the 50% threshold.
    function findOwnAnswer(cardIdx, userInput) {
      const qa = (CARDS[cardIdx] || {}).qa || [];
      if (!qa.length) return null;
      const input = normalizeText(userInput);
      let bestMatch = null, bestScore = 0;
      for (const turn of qa) {
        const trainedQ = normalizeText(t(turn.q));
        if (input === trainedQ) return t(turn.a);
        const score = matchScore(input, trainedQ);
        if (score > bestScore) { bestScore = score; bestMatch = t(turn.a); }
      }
      return bestScore >= 0.5 ? bestMatch : null;
    }

    // Only redirects to another card's answer when it scores at least 0.5
    // AND beats the current card's own best score.
    function findCrossCardAnswer(userInput, currentIdx) {
      const input = normalizeText(userInput);
      const currentScore = bestOwnScore(currentIdx, input);
      let best = null;
      CARDS.forEach((c, idx) => {
        if (idx === currentIdx) return;
        for (const turn of (c.qa || [])) {
          const trainedQ = normalizeText(t(turn.q));
          const score = input === trainedQ ? 1 : matchScore(input, trainedQ);
          if (!best || score > best.score) best = { idx, score, answer: t(turn.a), title: t(c.title) };
        }
      });
      return (best && best.score >= 0.5 && best.score > currentScore) ? best : null;
    }

    function addChatMsg(who, text, tag) {
      const thread = document.getElementById('detailChatThread');
      if (!thread) return;
      const empty = thread.querySelector('.detail-chat-empty');
      if (empty) empty.remove();
      const div = document.createElement('div');
      div.className = 'chat-msg ' + who;
      div.innerHTML = (tag ? `<span class="chat-tag">${escapeHtml(tag)}</span>` : '') + escapeHtml(text);
      thread.appendChild(div);
      thread.scrollTop = thread.scrollHeight;
    }

    let currentDetailIdx = 0;

    // Speaks the answer aloud when the question came in by voice — mirrors
    // health-command-centre.html's isVoice-in/voice-out pairing so a mic
    // question gets a spoken reply, while a typed/clicked one stays silent.
    function speakText(text) {
      try {
        if (!window.speechSynthesis) return;
        window.speechSynthesis.cancel();
        const utter = new SpeechSynthesisUtterance(text);
        utter.lang = currentLang === 'hi' ? 'hi-IN' : 'en-IN';
        window.speechSynthesis.speak(utter);
      } catch (e) {}
    }

    // 3-stage funnel: this card's own qa -> another card's qa on this page
    // -> real backend (/api/chat), only once nothing local matches.
    function askCardQuestion(question, isVoice) {
      addChatMsg('user', question);

      const ownAnswer = findOwnAnswer(currentDetailIdx, question);
      if (ownAnswer) {
        addChatMsg('bot', ownAnswer, t(UI_STRINGS.knowledgeBase));
        if (isVoice) speakText(ownAnswer);
        return;
      }

      const cross = findCrossCardAnswer(question, currentDetailIdx);
      if (cross) {
        const crossText = `${t(UI_STRINGS.crossPrefix)} "${cross.title}" ${t(UI_STRINGS.crossSuffix)} ${cross.answer}`;
        addChatMsg('bot', crossText, t(UI_STRINGS.relatedCard));
        if (isVoice) speakText(crossText);
        return;
      }

      addChatMsg('bot', t(UI_STRINGS.thinking), t(UI_STRINGS.live));
      fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: question, lang: currentLang }),
      })
        .then(res => res.text())
        .then(data => {
          const thread = document.getElementById('detailChatThread');
          const last = thread && thread.lastElementChild;
          let text = data;
          try {
            const parsed = JSON.parse(data);
            text = parsed.response || parsed.answer || parsed.text || data;
          } catch (e) {}
          if (last) { last.innerHTML = `<span class="chat-tag">${escapeHtml(t(UI_STRINGS.live))}</span>` + escapeHtml(text); }
          if (isVoice) speakText(text);
        })
        .catch(() => {
          const thread = document.getElementById('detailChatThread');
          const last = thread && thread.lastElementChild;
          if (last) { last.innerHTML = `<span class="chat-tag">${escapeHtml(t(UI_STRINGS.error))}</span>${escapeHtml(t(UI_STRINGS.errorMsg))}`; }
        });
    }

    // ── Mic (Web Speech API) — same approach as health-command-centre.html:
    // speech-to-text feeds straight into askCardQuestion(), so a spoken
    // question gets identical instant-answer / cross-card / LLM-fallback
    // behavior as a typed one, just with a spoken reply on top. Recognition
    // language switches with currentLang so Hindi mode listens for Hindi. ──
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    let recog = null;
    let listening = false;
    if (SR) {
      recog = new SR();
      recog.interimResults = false;
      recog.maxAlternatives = 1;
      recog.onresult = (e) => {
        const text = e.results[0][0].transcript;
        const input = document.getElementById('detailChatInput');
        if (input) input.value = '';
        askCardQuestion(text, true);
      };
      recog.onend = () => {
        listening = false;
        const btn = document.getElementById('detailChatMicBtn');
        if (btn) btn.classList.remove('listening');
      };
      recog.onerror = () => {
        listening = false;
        const btn = document.getElementById('detailChatMicBtn');
        if (btn) btn.classList.remove('listening');
      };
    }

    function toggleCardMic() {
      if (!recog) return;
      const btn = document.getElementById('detailChatMicBtn');
      if (listening) {
        recog.stop();
        listening = false;
        if (btn) btn.classList.remove('listening');
        return;
      }
      try {
        if (window.speechSynthesis) window.speechSynthesis.cancel();
        recog.lang = currentLang === 'hi' ? 'hi-IN' : 'en-IN';
        recog.start();
        listening = true;
        if (btn) btn.classList.add('listening');
      } catch (e) { /* already started */ }
    }

    function sendCardMessage() {
      const input = document.getElementById('detailChatInput');
      const q = input.value.trim();
      if (!q) return;
      input.value = '';
      askCardQuestion(q);
    }

    const grid = document.getElementById('cardsGrid');
    function renderCardsGrid() {
      grid.innerHTML = '';
      CARDS.forEach((card, i) => {
        const el = document.createElement('div');
        el.className = 'card';
        el.addEventListener('click', () => openDetail(i));
        el.innerHTML = `
          <div class="card-icon">${escapeHtml(card.icon || '✨')}</div>
          <div class="card-title">${escapeHtml(t(card.title))}</div>
          <div class="card-tagline">${escapeHtml(t(card.tagline))}</div>
          <div class="card-chips">
            ${(card.qa || []).slice(0, 2).map(item => `<span class="chip">${escapeHtml(t(item.q))}</span>`).join('')}
          </div>
          <div class="card-view-link">${escapeHtml(t(UI_STRINGS.viewAnalysis))}</div>
          <button class="card-cta" type="button">${escapeHtml(t(UI_STRINGS.startChat))}</button>
        `;
        el.querySelectorAll('.card-chips .chip').forEach((chipEl, ci) => {
          chipEl.addEventListener('click', (e) => {
            e.stopPropagation();
            const q = (card.qa || [])[ci];
            openDetail(i);
            if (q) setTimeout(() => askCardQuestion(t(q.q)), 60);
          });
        });
        el.querySelector('.card-cta').addEventListener('click', (e) => {
          e.stopPropagation();
          window.location.href = '/chat';
        });
        grid.appendChild(el);
      });
    }
    renderCardsGrid();

    function openDetail(idx) {
      currentDetailIdx = idx;
      detailIsOpen = true;
      const card = CARDS[idx] || {};
      const qa = card.qa || [];
      const panel = document.getElementById('detailPanel');
      panel.innerHTML = `
        <button class="detail-close" type="button" id="detailCloseBtn">✕</button>
        <div class="detail-header">
          <div class="detail-icon">${escapeHtml(card.icon || '✨')}</div>
          <div class="detail-title">${escapeHtml(t(card.title))}</div>
        </div>
        <div class="detail-tagline">${escapeHtml(t(card.tagline))}</div>

        <div class="detail-section-label">${escapeHtml(t(UI_STRINGS.aiAnalysis))}</div>
        <div class="detail-ai-grid">
          <div class="ai-box prediction">
            <div class="ai-box-label">${escapeHtml(t(UI_STRINGS.aiPrediction))}</div>
            <div class="ai-box-text">${escapeHtml(t(card.ai_prediction))}</div>
          </div>
          <div class="ai-box wrong">
            <div class="ai-box-label">${escapeHtml(t(UI_STRINGS.whatsWrong))}</div>
            <div class="ai-box-text">${escapeHtml(t(card.whats_wrong))}</div>
          </div>
          <div class="ai-box normal">
            <div class="ai-box-label">${escapeHtml(t(UI_STRINGS.whatsNormal))}</div>
            <div class="ai-box-text">${escapeHtml(t(card.whats_normal))}</div>
          </div>
          <div class="ai-box benefit">
            <div class="ai-box-label">${escapeHtml(t(UI_STRINGS.aiBenefit))}</div>
            <div class="ai-box-text">${escapeHtml(t(card.ai_benefit))}</div>
          </div>
        </div>

        <div class="detail-related-label">${escapeHtml(t(UI_STRINGS.relatedQuestions))}<span class="related-questions-count">${qa.length} ${escapeHtml(t(UI_STRINGS.scrollForMore))}</span></div>
        <div class="related-questions-scroll" id="detailQuestionsRow">
          ${qa.map(item => `<span class="chip">${escapeHtml(t(item.q))}</span>`).join('')}
        </div>

        <div class="detail-chat">
          <div class="detail-chat-thread" id="detailChatThread">
            <div class="detail-chat-empty">${escapeHtml(t(UI_STRINGS.chatEmpty))}</div>
          </div>
          <div class="detail-chat-row">
            <input type="text" class="detail-chat-input" id="detailChatInput" placeholder="${escapeHtml(t(UI_STRINGS.askPlaceholder))} ${escapeHtml(t(card.title) || '')}…">
            <button type="button" class="detail-chat-mic" id="detailChatMicBtn" title="${escapeHtml(t(UI_STRINGS.speakQuestion))}">🎤</button>
            <button type="button" class="detail-chat-send" id="detailChatSendBtn">${escapeHtml(t(UI_STRINGS.askBtn))}</button>
          </div>
        </div>

        <div class="detail-cols">
          <div>
            <div class="detail-col-label">${escapeHtml(t(UI_STRINGS.dataSource))}</div>
            <div class="detail-col-text">${escapeHtml(t(card.data_source))}</div>
          </div>
          <div>
            <div class="detail-col-label">${escapeHtml(t(UI_STRINGS.whatItDoes))}</div>
            <div class="detail-col-text">${escapeHtml(t(card.what_it_does))}</div>
          </div>
          <div>
            <div class="detail-col-label">${escapeHtml(t(UI_STRINGS.benefit))}</div>
            <div class="detail-col-text">${escapeHtml(t(card.benefit))}</div>
          </div>
        </div>

        <button class="card-cta" type="button" id="detailChatBtn">${escapeHtml(t(UI_STRINGS.startChat))}</button>
      `;
      panel.querySelector('#detailCloseBtn').addEventListener('click', closeDetail);
      panel.querySelector('#detailChatBtn').addEventListener('click', () => { window.location.href = '/chat'; });
      panel.querySelector('#detailChatSendBtn').addEventListener('click', sendCardMessage);
      panel.querySelector('#detailChatInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') sendCardMessage();
      });
      const micBtn = panel.querySelector('#detailChatMicBtn');
      if (micBtn) {
        if (!SR) {
          micBtn.disabled = true;
          micBtn.title = t(UI_STRINGS.voiceNotSupported);
        } else {
          micBtn.addEventListener('click', toggleCardMic);
        }
      }
      panel.querySelectorAll('#detailQuestionsRow .chip').forEach((chipEl, ci) => {
        chipEl.addEventListener('click', () => askCardQuestion(t(qa[ci].q)));
      });
      document.getElementById('detailOverlay').classList.add('open');
    }

    let detailIsOpen = false;

    function closeDetail() {
      if (recog && listening) { try { recog.stop(); } catch (e) {} }
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      detailIsOpen = false;
      document.getElementById('detailOverlay').classList.remove('open');
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeDetail();
    });

    function renderAvatarChips() {
      const avatarChips = document.getElementById('avatarChips');
      const firstCard = CARDS[0] || {};
      const firstTwoQA = (firstCard.qa || []).slice(0, 2);
      avatarChips.innerHTML = firstTwoQA.map(item => `<span class="chip">${escapeHtml(t(item.q))}</span>`).join('');
      avatarChips.querySelectorAll('.chip').forEach((chipEl, ci) => {
        chipEl.addEventListener('click', () => {
          document.getElementById('avatarOverlay').classList.remove('open');
          openDetail(0);
          setTimeout(() => askCardQuestion(t(firstTwoQA[ci].q)), 60);
        });
      });
    }
    renderAvatarChips();

    function renderStaticChrome() {
      document.getElementById('heroDesc').textContent = t(HERO_DESC);
      document.getElementById('footerText').textContent = t(FOOTER_TEXT);
      const pageNameText = document.querySelector('.header-title span').textContent;
      document.getElementById('avatarName').textContent = pageNameText + ' ' + t(UI_STRINGS.assistant);
      document.getElementById('avatarOnline').textContent = t(UI_STRINGS.online);
      document.getElementById('avatarStatus').textContent = t(UI_STRINGS.readyToHelp);
      document.getElementById('avatarCta').textContent = t(UI_STRINGS.startChat);
    }

    // Switches the whole page's language: persists the choice, flips the
    // toggle buttons, re-renders the card grid + avatar widget + static
    // chrome text from the same CARDS data (no reload, no new LLM call),
    // and refreshes the detail modal in place if one is currently open.
    function setLanguage(lang) {
      currentLang = lang;
      saveLang(lang);
      document.documentElement.lang = lang;
      document.getElementById('langBtnEn').classList.toggle('active', lang === 'en');
      document.getElementById('langBtnHi').classList.toggle('active', lang === 'hi');
      renderStaticChrome();
      renderCardsGrid();
      renderAvatarChips();
      if (detailIsOpen) openDetail(currentDetailIdx);
    }

    renderStaticChrome();
    setLanguage(currentLang);
  </script>
</body>
</html>"""


def _js_json(value) -> str:
    """json.dumps guarded against a literal </script> breaking out of the
    inline <script> tag it gets embedded in."""
    return json.dumps(value, ensure_ascii=False).replace("</script", "<\\/script")


def _render_subpage_html(app_name: str, theme: str, page_name: str, cards: list) -> str:
    primary, accent, bg, avatar_emoji = _theme_colors(theme)
    # app_name/page_name are short admin-typed labels (proper nouns), kept
    # as-is in both languages — same convention ai_sayak_medical_up's pages
    # use for "VIBHAG SAHAYAK" etc. Only the surrounding descriptive text
    # and every LLM-authored card field are actually bilingual.
    hero_desc = {
        "en": f"Explore {page_name} services and get instant AI-powered answers.",
        "hi": f"{page_name} सेवाएं देखें और तुरंत AI-संचालित उत्तर पाएं।",
    }
    footer_text = {
        "en": f"{app_name} — {page_name} © 2025 | Powered by AI",
        "hi": f"{app_name} — {page_name} © 2025 | AI द्वारा संचालित",
    }

    page_html = _SUBPAGE_TEMPLATE
    page_html = page_html.replace("__APP_NAME__", html_escape(app_name))
    page_html = page_html.replace("__PAGE_NAME__", html_escape(page_name))
    page_html = page_html.replace("__HERO_DESC__", html_escape(hero_desc["en"]))
    page_html = page_html.replace("__PRIMARY__", primary)
    page_html = page_html.replace("__ACCENT__", accent)
    page_html = page_html.replace("__BG__", bg)
    page_html = page_html.replace("__AVATAR_EMOJI__", avatar_emoji)
    page_html = page_html.replace("__CARDS_JSON__", _js_json(cards))
    page_html = page_html.replace("__HERO_JSON__", _js_json(hero_desc))
    page_html = page_html.replace("__FOOTER_JSON__", _js_json(footer_text))
    return page_html


import asyncio as _asyncio


@app.post("/api/demos/generate")
async def generate_demo(req: GenerateDemoRequest, request: Request):
    require_admin(request)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Demo name is required.")
    theme = (req.theme or "").strip()

    pages = req.pages or []
    if not pages:
        raise HTTPException(status_code=400, detail="At least one page is required.")

    for p in pages:
        p.features = [f.strip() for f in (p.features or []) if f.strip()]
        p.sample_questions = [q.strip() for q in (p.sample_questions or []) if q.strip()]

    # One LLM call for the mainindex gateway page (full HTML, as before) +
    # one LLM call PER CARD (per feature) across every page — a prompt
    # focused on a single feature produces far richer, more specific
    # analytical content than one call asked to fill in every card on a
    # page at once. Calls run in parallel, capped by a semaphore so a page
    # with many features doesn't fire dozens of simultaneous requests at
    # the LLM backend. The subpage HTML itself is always the fixed
    # _SUBPAGE_TEMPLATE, never LLM-authored.
    #
    # Each bilingual, 30+-Q&A card call takes ~30-80s (the backend batches
    # concurrent requests rather than truly parallelizing them, so per-call
    # latency rises with concurrency) — a 20-30 card demo can take several
    # minutes end to end. Streamed as NDJSON progress lines so the admin UI
    # can show "Generating N/M…" instead of one long silent wait.
    sem = _asyncio.Semaphore(6)

    async def _bounded_call(prompt: str) -> str:
        async with sem:
            return await _call_demo_llm(prompt)

    prompts = [_build_mainindex_prompt(name, theme, pages)]
    page_feature_lists = []
    for p in pages:
        features = p.features or ["General Q&A"]
        page_feature_lists.append(features)
        for feature in features:
            prompts.append(_build_single_card_prompt(name, theme, p.name, feature, p.sample_questions))

    total = len(prompts)

    async def _indexed_call(i: int, prompt: str):
        result = await _bounded_call(prompt)
        return i, result

    async def event_stream():
        results = [None] * total
        done = 0
        yield json.dumps({"type": "progress", "done": 0, "total": total}) + "\n"

        try:
            for coro in _asyncio.as_completed([_indexed_call(i, pr) for i, pr in enumerate(prompts)]):
                i, result = await coro
                results[i] = result
                done += 1
                yield json.dumps({"type": "progress", "done": done, "total": total}) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "detail": f"Demo generation failed: {e}"}) + "\n"
            return

        mainindex_html = results[0]
        cursor = 1
        page_docs = []
        for p, features in zip(pages, page_feature_lists):
            raw_slice = results[cursor:cursor + len(features)]
            cursor += len(features)
            cards = [_parse_single_card_data(raw, features[i]) for i, raw in enumerate(raw_slice)]
            page_html = _render_subpage_html(name, theme, p.name, cards)
            page_docs.append({"slug": p.slug, "name": p.name, "html": page_html})

        demo_id = str(uuid.uuid4())
        demos_collection.insert_one({
            "_id": demo_id,
            "name": name,
            "theme": theme,
            "html": mainindex_html,
            "pages": page_docs,
            "created_at": datetime.now(),
            "promoted_project_id": None,
        })
        yield json.dumps({"type": "result", "demo_id": demo_id, "html": mainindex_html, "pages": page_docs}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.get("/api/demos/{demo_id}")
async def get_demo(demo_id: str, request: Request):
    require_admin(request)
    doc = demos_collection.find_one({"_id": demo_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Demo not found.")
    doc.pop("_id", None)
    return {"demo_id": demo_id, **doc}


class PromoteDemoRequest(BaseModel):
    project_name: Optional[str] = None
    label: Optional[str] = None


@app.post("/api/demos/{demo_id}/promote")
async def promote_demo(demo_id: str, req: PromoteDemoRequest, request: Request):
    """Turns a demo into a real project via _create_project() (same
    scaffold.scaffold_project() every other project uses — nothing about
    the generated shape changes), then drops a DEMO_SPEC.md brief into the
    new folder so whoever writes its ollamaagent2.py by hand has the
    requested theme/features/sample questions to work from."""
    require_admin(request)
    demo = demos_collection.find_one({"_id": demo_id})
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found.")

    name = (req.project_name or demo["name"]).strip()
    label = (req.label or "").strip() or scaffold.title_case(name)

    result = _create_project(name, label)

    demo_html = demo.get("html", "")
    if demo_html:
        with open(os.path.join(ROOT_DIR, name, "mainindex.html"), "w", encoding="utf-8") as f:
            f.write(demo_html)

    for page in demo.get("pages", []):
        page_html = page.get("html", "")
        page_slug = page.get("slug", "")
        if page_html and page_slug:
            with open(os.path.join(ROOT_DIR, name, f"{page_slug}.html"), "w", encoding="utf-8") as f:
                f.write(page_html)

    spec_lines = [
        f"# Demo brief for {label}",
        "",
        f"Generated from admin demo `{demo_id}` on {datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        "",
        f"**Theme:** {demo.get('theme') or '(none specified)'}",
        "",
        "**Requested features:**",
    ]
    spec_lines += [f"- {f}" for f in demo.get("features", [])] or ["- (none specified)"]
    spec_lines += ["", "**Sample questions:**"]
    spec_lines += [f"- {q}" for q in demo.get("sample_questions", [])] or ["- (none specified)"]
    spec_lines += [
        "",
        "This file is a brief only — per repo convention, ollamaagent2.py in "
        "this folder is never auto-generated. Build the actual domain logic "
        "here by hand, using this as a starting spec.",
    ]
    spec_path = os.path.join(ROOT_DIR, name, "DEMO_SPEC.md")
    with open(spec_path, "w", encoding="utf-8") as f:
        f.write("\n".join(spec_lines) + "\n")

    demos_collection.update_one({"_id": demo_id}, {"$set": {"promoted_project_id": name}})

    return result


@app.get("/api/projects/{project_id}/config")
async def get_project_config(project_id: str, request: Request):
    require_admin(request)
    if project_id not in _known_project_ids():
        raise HTTPException(status_code=404, detail="Unknown project.")
    doc = project_config.find_one({"_id": project_id}) or {}
    updated_at = doc.get("updated_at")
    return {
        "project_id": project_id,
        "env": doc.get("env", {}),
        "updated_at": updated_at.strftime("%Y-%m-%d %H:%M:%S") if updated_at else None,
    }


@app.get("/api/projects/{project_id}/logs")
async def get_project_logs(project_id: str, request: Request, lines: int = 500):
    require_admin(request)
    if project_id not in _known_project_ids():
        raise HTTPException(status_code=404, detail="Unknown project.")
    
    log_file = os.path.join(ROOT_DIR, "logs", f"{project_id}.log")
    if not os.path.exists(log_file):
        return {"logs": "Log file not found. Has the project been started?"}
    
    try:
        import collections
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            last_lines = collections.deque(f, lines)
        return {"logs": "".join(last_lines)}
    except Exception as e:
        return {"logs": f"Error reading logs: {e}"}


# ── VM Monitor status ─────────────────────────────────────────────────────
# This admin service now owns and runs the VM Monitor subprocess itself (see
# start_vm_monitor() above) — a real system-resource dashboard (CPU/RAM/GPU/
# disk/network via psutil/nvidia-smi), not a per-project config target, so it
# has no entry in the `projects` collection. This endpoint just tells the
# frontend which protocol to iframe it with and whether it's currently
# reachable.
@app.get("/api/vm-monitor/status")
async def vm_monitor_status(request: Request):
    require_admin(request)
    return {
        "protocol": "https" if _VM_MONITOR_HAS_TLS_CERT else "http",
        "port": _VM_MONITOR_PORT,
        "healthy": _vm_monitor_healthy(),
    }


@app.get("/api/reference/config")
async def get_config_reference(request: Request):
    require_admin(request)
    md_path = os.path.join(ROOT_DIR, "CONFIGURATION.md")
    if not os.path.exists(md_path):
        return {"content": "CONFIGURATION.md not found."}
    with open(md_path, "r", encoding="utf-8") as f:
        return {"content": f.read()}


@app.post("/api/projects/{project_id}/restart")
async def restart_project(project_id: str, request: Request):
    require_admin(request)
    if project_id not in _known_project_ids():
        raise HTTPException(status_code=404, detail="Unknown project.")
    
    if project_id == "admin_config":
        raise HTTPException(status_code=400, detail="Cannot restart admin_config from its own UI.")

    import subprocess, signal, time
    log_dir = os.path.join(ROOT_DIR, "logs")
    pidfile = os.path.join(log_dir, f"{project_id}.pid")
    
    if os.path.exists(pidfile):
        try:
            with open(pidfile, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            for _ in range(30):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.1)
                except OSError:
                    break
            else:
                os.kill(pid, signal.SIGKILL)
        except (ValueError, OSError):
            pass
        try:
            os.remove(pidfile)
        except OSError:
            pass

    project_dir = os.path.join(ROOT_DIR, project_id)
    if not os.path.isdir(project_dir):
        raise HTTPException(status_code=404, detail="Project directory not found.")
        
    log_file = os.path.join(log_dir, f"{project_id}.log")
    with open(log_file, "a") as f:
        f.write(f"\n--- Restarted via Admin UI at {datetime.now().isoformat()} ---\n")
        proc = subprocess.Popen(
            ["python3", "server.py"],
            cwd=project_dir,
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
        
    with open(pidfile, "w") as f:
        f.write(str(proc.pid))
        
    return {"status": "restarted", "pid": proc.pid}


class ConfigUpdateRequest(BaseModel):
    env: Dict[str, str]


@app.put("/api/projects/{project_id}/config")
async def put_project_config(project_id: str, req: ConfigUpdateRequest, request: Request):
    require_admin(request)
    if project_id not in _known_project_ids():
        raise HTTPException(status_code=404, detail="Unknown project.")
    # Overwrite the whole env dict rather than merging — the frontend always
    # sends the full current table, so a key removed in the UI actually
    # gets removed here too (a $set-per-key merge would never delete one).
    project_config.update_one(
        {"_id": project_id},
        {"$set": {"env": req.env, "updated_at": datetime.now()}},
        upsert=True,
    )
    return {"status": "saved"}


frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
app.mount("/static", StaticFiles(directory=frontend_path), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(frontend_path, "index.html"))


if __name__ == "__main__":
    import uvicorn
    _port = int(os.getenv("PORT", "8122"))
    print(f"Starting Project Config Admin on http://0.0.0.0:{_port}")
    uvicorn.run(app, host="0.0.0.0", port=_port)
