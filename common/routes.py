"""Shared FastAPI route handlers used by both ai_sayak_medical_up and matrix_app.

Each app's own server.py calls register_common_routes(app, config) once at
startup (after CORS middleware is added), then defines only its own
app-specific routes on top — see each app's server.py for what those are and
why they live there instead of here (documented inline at each call site and
in PROJECTS_COMPARISON.md).

Handlers here were moved only after being diffed byte-for-byte identical (or
differing by exactly one config value, e.g. the TTS default voice) between
the two apps' original server.py files.
"""
import asyncio
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, List, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from common.database.mongo import (
    get_groups_collection,
    get_query_log_collection,
    get_sessions_collection,
    get_tts_config_collection,
    get_users_collection,
)
from common.services.related_links import fetch_related_links


@dataclass
class CommonRouteConfig:
    """The handful of per-app objects the shared routes genuinely depend on
    (the agent graph, PDF ingestion, model getters) — passed in rather than
    imported directly here, since each app has its own ollamaagent2.py /
    services/pdf_rag.py."""
    call_llm: Callable
    clear_trace: Callable
    get_trace: Callable
    ingest_pdf: Callable
    extract_pages: Callable
    get_whisper_model: Callable
    get_nemotron_model: Callable
    nemotron_session_cls: Any
    frontend_path: str
    question_file_path: str
    avatar_id_default: str
    liveavatar_api_key: str
    default_tts_voice_id: Optional[str] = None


# ── Shared Pydantic request models ─────────────────────────────────────────
class LoginRequest(BaseModel):
    name: str


class SettingsRequest(BaseModel):
    settings: dict


class PdfRenameRequest(BaseModel):
    doc_id: str
    old_filename: str
    new_filename: str


class PdfMergeRequest(BaseModel):
    doc_ids: list[str]
    new_filename: str


class QueryLogDeleteRequest(BaseModel):
    doc_ids: list[str]


class PdfDeleteRequest(BaseModel):
    doc_ids: list[str]


class GroupCreateRequest(BaseModel):
    name: str
    liveavatar_token: str


class ElevenLabsConfigRequest(BaseModel):
    keys: List[str]
    voice_id: Optional[str] = None


class TtsRequest(BaseModel):
    text: str
    lang: Optional[str] = "en"


class AssignGroupRequest(BaseModel):
    user_id: str
    group_id: str


class AvatarTokenRequest(BaseModel):
    avatar_id: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Session / user identity — shared with each app's own /api/chat handler
# (kept app-specific because ai_sayak threads lat/lng through it), so these
# stay importable at module level rather than nested inside register_common_routes.
# ─────────────────────────────────────────────────────────────────────────────
SESSION_COOKIE_NAME = "sid"
USER_COOKIE_NAME = "uid"


class SessionState:
    def __init__(self):
        self.pdf_filenames: list = []
        # filename -> one-sentence LLM subject summary, used to cluster
        # uploaded PDFs into "expert" groups (see /api/pdf-experts/build)
        self.pdf_subjects: dict = {}
        # [{"name": str, "filenames": [str], "avatar_id": str | None}, ...]
        self.pdf_experts: list = []


_sessions: dict[str, SessionState] = {}


def get_or_create_session(request: Request, response: Response) -> tuple[str, SessionState]:
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if not sid or sid not in _sessions:
        sid = str(uuid.uuid4())
        response.set_cookie(SESSION_COOKIE_NAME, sid, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    session = _sessions.setdefault(sid, SessionState())
    return sid, session


async def get_current_user(request: Request):
    """Returns the logged-in user's MongoDB doc, or None if not logged in / user was deleted."""
    uid = request.cookies.get(USER_COOKIE_NAME)
    if not uid:
        return None
    return await get_users_collection().find_one({"_id": uid})


def _strip_meta_sentinel(text: str) -> str:
    """Remove the __META__...__END_META__ block answer_node embeds in the raw
    answer text — the log should show the human-readable answer, not the
    JSON sentinel the frontend parses out for its UI state."""
    idx = text.find("__META__")
    if idx == -1:
        return text
    end_idx = text.find("__END_META__", idx)
    if end_idx == -1:
        return text[:idx].strip()
    return (text[:idx] + text[end_idx + len("__END_META__"):]).strip()


async def _persist_chat_session(chat_id: str, messages: list, user_id: str = None, user_name: str = None):
    """Upserts this chat's current messages under _id=chat_id, live on every
    turn — see server.py's chat_endpoint for the full rationale. Fire-and-forget;
    non-fatal — a Mongo hiccup here must never break the actual chat turn."""
    if not messages:
        return
    title = "New Chat"
    for msg in messages:
        if msg.get("role") == "user":
            title = msg["content"][:30] + ("..." if len(msg["content"]) > 30 else "")
            break
    try:
        await get_sessions_collection().update_one(
            {"_id": chat_id},
            {"$set": {
                "title": title,
                "messages": messages,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "user_id": user_id,
                "user_name": user_name,
            }},
            upsert=True,
        )
    except Exception as e:
        print(f"⚠️ Could not persist chat session (non-fatal): {e}")


async def _log_query(user_name: str, query: str, rewritten_query: str, answer: str, sql_rows, trace: list,
                      chat_id: str = None, user_id: str = None):
    try:
        await get_query_log_collection().insert_one({
            "user_name": user_name,
            "chat_id": chat_id,
            "user_id": user_id,
            "query": query,
            "rewritten_query": rewritten_query,
            "answer": answer,
            "sql_rows": sql_rows,
            "trace": trace,
            "created_at": datetime.now(),
        })
    except Exception as e:
        print(f"⚠️ Could not write to query log (non-fatal): {e}")


def _read_static_suggestions(question_file_path: str) -> list[str]:
    """Reads the app's own 'question' file from disk — the global,
    unauthenticated suggestion pool. Gracefully returns [] if the app has no
    such file (e.g. ai_sayak_medical_up doesn't ship one today)."""
    suggestions = []
    if os.path.exists(question_file_path):
        with open(question_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    suggestions.append(line)
    return suggestions


async def _resolve_voice_id(client: httpx.AsyncClient, api_key: str) -> Optional[str]:
    """Looks up a voice this specific key/account can actually use via the
    API. Free-plan keys 402 on most "voice library" voices even though
    they're visible in the dashboard — GET /v1/voices only returns voices
    that ARE usable for this key, so picking from that list (preferring a
    premade one) avoids guessing a voice_id that happens to be paid-only."""
    try:
        resp = await client.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": api_key},
        )
        if resp.status_code != 200:
            return None
        voices = resp.json().get("voices", [])
        premade = next((v for v in voices if v.get("category") == "premade"), None)
        chosen = premade or (voices[0] if voices else None)
        return chosen.get("voice_id") if chosen else None
    except httpx.HTTPError:
        return None


def register_common_routes(app: FastAPI, config: CommonRouteConfig):
    """Registers every route handler that's identical (or trivially
    parameterized via `config`) between ai_sayak_medical_up and matrix_app.
    Call once, right after CORS middleware is added, before any app-specific
    routes are defined."""

    # ── Auth ─────────────────────────────────────────────────────────────
    @app.post("/api/auth/login")
    async def login_endpoint(login_request: LoginRequest, response: Response):
        name = login_request.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name is required.")

        users = get_users_collection()
        existing = await users.find_one({"name": name})

        if existing:
            uid = existing["_id"]
            is_admin = existing.get("is_admin", False)
            await users.update_one({"_id": uid}, {"$set": {"last_login_at": datetime.now()}})
        else:
            is_admin = (await users.count_documents({})) == 0  # first-ever user -> admin
            uid = str(uuid.uuid4())
            await users.insert_one({
                "_id": uid,
                "name": name,
                "is_admin": is_admin,
                "settings": {},
                "created_at": datetime.now(),
                "last_login_at": datetime.now(),
            })

        response.set_cookie(USER_COOKIE_NAME, uid, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 365)
        return {"name": name, "is_admin": is_admin}

    @app.get("/api/auth/me")
    async def auth_me_endpoint(request: Request):
        user = await get_current_user(request)
        if not user:
            return {"logged_in": False}
        return {"logged_in": True, "name": user["name"], "is_admin": user.get("is_admin", False)}

    @app.post("/api/auth/logout")
    async def logout_endpoint(response: Response):
        response.delete_cookie(USER_COOKIE_NAME)
        return {"status": "logged_out"}

    # ── Per-user settings ────────────────────────────────────────────────
    @app.get("/api/settings")
    async def get_settings_endpoint(request: Request):
        user = await get_current_user(request)
        if not user:
            return {"logged_in": False, "settings": {}}
        return {"logged_in": True, "settings": user.get("settings", {})}

    @app.post("/api/settings")
    async def save_settings_endpoint(settings_request: SettingsRequest, request: Request):
        user = await get_current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Log in first to save settings to your profile.")
        await get_users_collection().update_one(
            {"_id": user["_id"]},
            {"$set": {"settings": settings_request.settings}}
        )
        return {"status": "saved"}

    # ── Query log (admin) ────────────────────────────────────────────────
    @app.get("/api/query-log")
    async def query_log_endpoint(request: Request, limit: int = 200):
        user = await get_current_user(request)
        if not user or not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required.")

        entries = []
        cursor = get_query_log_collection().find().sort("created_at", -1).limit(min(limit, 500))
        async for doc in cursor:
            created_at = doc.get("created_at")
            ts = created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else ""
            event = doc.get("event", "chat")  # "pdf_upload" or legacy chat (no field)
            doc_id = str(doc.get("_id"))

            if event == "pdf_upload":
                entries.append({
                    "doc_id":          doc_id,
                    "event":           "pdf_upload",
                    "user_name":       doc.get("user_name", "Unknown"),
                    "user_id":         doc.get("user_id"),
                    "filename":        doc.get("filename", ""),
                    "pages":           doc.get("pages", 0),
                    "chunks":          doc.get("chunks", 0),
                    "is_admin_upload": doc.get("is_admin_upload", False),
                    "created_at":      ts,
                })
            else:
                query = doc.get("query", "")
                rewritten_query = doc.get("rewritten_query", query)
                entries.append({
                    "doc_id":          doc_id,
                    "event":           "chat",
                    "user_name":       doc.get("user_name", "Unknown"),
                    "user_id":         doc.get("user_id"),
                    "chat_id":         doc.get("chat_id"),
                    "query":           query,
                    "rewritten_query": rewritten_query if rewritten_query != query else None,
                    "answer":          doc.get("answer", ""),
                    "sql_rows":        doc.get("sql_rows"),
                    "trace":           doc.get("trace", []),
                    "created_at":      ts,
                })
        return {"entries": entries}

    # ── PDF pipeline ─────────────────────────────────────────────────────
    @app.post("/api/upload-pdf")
    async def upload_pdf_endpoint(request: Request, response: Response, file: UploadFile = File(...)):
        if not file.filename.lower().endswith(".pdf"):
            return JSONResponse({"error": "Only PDF files are supported."}, status_code=400)

        _, session = get_or_create_session(request, response)

        current_user = await get_current_user(request)
        user_id   = current_user["_id"]  if current_user else "anonymous"
        user_name = current_user["name"] if current_user else "Anonymous"
        is_admin  = bool(current_user and current_user.get("is_admin", False))

        data = await file.read()
        try:
            result = await asyncio.to_thread(
                config.ingest_pdf, data, file.filename,
                user_id, user_name, is_admin,      # isolation fields
            )
        except Exception as e:
            print(f"Error ingesting PDF: {e}")
            return JSONResponse({"error": f"Failed to process PDF: {e}"}, status_code=500)

        session.pdf_filenames.append(file.filename)

        try:
            await get_query_log_collection().insert_one({
                "event":           "pdf_upload",
                "user_id":         user_id,
                "user_name":       user_name,
                "is_admin_upload": is_admin,
                "filename":        file.filename,
                "pages":           result.get("pages", 0),
                "chunks":          result.get("chunks", 0),
                "created_at":      datetime.now(),
            })
        except Exception as e:
            print(f"⚠️ Could not log PDF upload (non-fatal): {e}")

        try:
            pages = await asyncio.to_thread(config.extract_pages, data)
            sample_text = "\n".join(pages[:3])[:4000]
            if sample_text.strip():
                summary = await config.call_llm(
                    "Summarize the SUBJECT of this document in ONE short sentence "
                    "(what topic/domain it's about, not its contents in detail). "
                    f"Output ONLY the sentence, nothing else.\n\n{sample_text}"
                )
                session.pdf_subjects[file.filename] = summary.strip()
        except Exception as e:
            print(f"⚠️ Could not summarize PDF subject for {file.filename}: {e}")

        return result

    @app.get("/api/admin/pdfs")
    async def list_pdfs_endpoint(request: Request):
        user = await get_current_user(request)
        if not user or not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required.")

        entries = []
        cursor = get_query_log_collection().find(
            {"event": "pdf_upload"}
        ).sort("created_at", -1)
        async for doc in cursor:
            created_at = doc.get("created_at")
            entries.append({
                "doc_id":          str(doc["_id"]),
                "user_name":       doc.get("user_name", "Unknown"),
                "user_id":         doc.get("user_id"),
                "filename":        doc.get("filename", ""),
                "pages":           doc.get("pages", 0),
                "chunks":          doc.get("chunks", 0),
                "is_admin_upload": doc.get("is_admin_upload", False),
                "created_at":      created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else "",
            })
        return {"pdfs": entries}

    @app.post("/api/admin/pdf-merge")
    async def merge_pdfs_endpoint(req: PdfMergeRequest, request: Request):
        from bson import ObjectId

        user = await get_current_user(request)
        if not user or not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required.")

        if not req.doc_ids:
            raise HTTPException(status_code=400, detail="doc_ids must contain at least one PDF upload document.")

        new_name = req.new_filename.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="new_filename must not be empty.")
        if not new_name.lower().endswith(".pdf"):
            new_name = new_name + ".pdf"

        from qdrant_client.models import Filter, FieldCondition, MatchAny
        from services.pdf_rag import pdf_qdrant_client, PDF_COLLECTION

        old_filenames = []
        upload_doc_ids = []
        for doc_id in req.doc_ids:
            try:
                obj_id = ObjectId(doc_id)
            except Exception:
                raise HTTPException(status_code=400, detail=f"Invalid doc_id: {doc_id}")
            upload_doc_ids.append(obj_id)

        cursor = get_query_log_collection().find({
            "_id": {"$in": upload_doc_ids},
            "event": "pdf_upload",
        })
        async for doc in cursor:
            filename = doc.get("filename", "")
            if filename and filename not in old_filenames:
                old_filenames.append(filename)

        if not old_filenames:
            raise HTTPException(status_code=400, detail="No matching PDF upload records found.")

        updated_qdrant = 0
        if pdf_qdrant_client.collection_exists(PDF_COLLECTION):
            scroll_filter = Filter(must=[
                FieldCondition(key="filename", match=MatchAny(any=old_filenames))
            ])
            next_offset = None
            while True:
                result, next_offset = pdf_qdrant_client.scroll(
                    collection_name=PDF_COLLECTION,
                    scroll_filter=scroll_filter,
                    limit=100,
                    offset=next_offset,
                    with_payload=False,
                )
                if not result:
                    break

                point_ids = [p.id for p in result]
                if point_ids:
                    pdf_qdrant_client.set_payload(
                        collection_name=PDF_COLLECTION,
                        payload={"filename": new_name},
                        points=point_ids,
                    )
                    updated_qdrant += len(point_ids)

                if next_offset is None:
                    break

        await get_query_log_collection().update_many(
            {
                "_id": {"$in": upload_doc_ids},
                "event": "pdf_upload",
            },
            {"$set": {"filename": new_name}},
        )

        return {
            "merged_from": old_filenames,
            "new_filename": new_name,
            "qdrant_chunks": updated_qdrant,
        }

    @app.post("/api/admin/pdf-rename")
    async def rename_pdf_endpoint(req: PdfRenameRequest, request: Request):
        user = await get_current_user(request)
        if not user or not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required.")

        new_name = req.new_filename.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="new_filename must not be empty.")
        if not new_name.lower().endswith(".pdf"):
            new_name = new_name + ".pdf"

        from qdrant_client.models import Filter, FieldCondition, MatchAny
        from services.pdf_rag import pdf_qdrant_client, PDF_COLLECTION

        updated_qdrant = 0
        if pdf_qdrant_client.collection_exists(PDF_COLLECTION):
            scroll_filter = Filter(must=[
                FieldCondition(key="filename", match=MatchAny(any=[req.old_filename]))
            ])
            next_offset = None
            while True:
                result, next_offset = pdf_qdrant_client.scroll(
                    collection_name=PDF_COLLECTION,
                    scroll_filter=scroll_filter,
                    limit=100,
                    offset=next_offset,
                    with_payload=False,
                )
                if not result:
                    break
                point_ids = [p.id for p in result]
                pdf_qdrant_client.set_payload(
                    collection_name=PDF_COLLECTION,
                    payload={"filename": new_name},
                    points=point_ids,
                )
                updated_qdrant += len(point_ids)
                if next_offset is None:
                    break

        from bson import ObjectId
        updated_mongo = 0
        try:
            mongo_result = await get_query_log_collection().update_one(
                {"_id": ObjectId(req.doc_id)},
                {"$set": {"filename": new_name}},
            )
            updated_mongo = mongo_result.modified_count
        except Exception as e:
            print(f"⚠️ Could not update query-log doc on rename: {e}")

        return {
            "status":          "ok",
            "new_filename":    new_name,
            "qdrant_chunks":   updated_qdrant,
            "mongo_updated":   updated_mongo,
        }

    @app.post("/api/admin/query-log-delete")
    async def delete_query_log_endpoint(req: QueryLogDeleteRequest, request: Request):
        from bson import ObjectId

        user = await get_current_user(request)
        if not user or not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required.")

        if not req.doc_ids:
            raise HTTPException(status_code=400, detail="doc_ids must contain at least one query-log document.")

        obj_ids = []
        for doc_id in req.doc_ids:
            try:
                obj_ids.append(ObjectId(doc_id))
            except Exception:
                raise HTTPException(status_code=400, detail=f"Invalid doc_id: {doc_id}")

        mongo_result = await get_query_log_collection().delete_many({"_id": {"$in": obj_ids}})
        return {
            "status": "ok",
            "mongo_deleted": mongo_result.deleted_count,
        }

    @app.post("/api/admin/pdf-delete")
    async def delete_pdf_endpoint(req: PdfDeleteRequest, request: Request):
        from bson import ObjectId

        user = await get_current_user(request)
        if not user or not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required.")

        if not req.doc_ids:
            raise HTTPException(status_code=400, detail="doc_ids must contain at least one PDF upload document.")

        obj_ids = []
        for doc_id in req.doc_ids:
            try:
                obj_ids.append(ObjectId(doc_id))
            except Exception:
                raise HTTPException(status_code=400, detail=f"Invalid doc_id: {doc_id}")

        upload_docs = []
        cursor = get_query_log_collection().find({"_id": {"$in": obj_ids}, "event": "pdf_upload"})
        async for doc in cursor:
            upload_docs.append(doc)

        if not upload_docs:
            raise HTTPException(status_code=400, detail="No matching PDF upload records found.")

        from qdrant_client.models import Filter, FieldCondition, MatchValue
        from services.pdf_rag import pdf_qdrant_client, PDF_COLLECTION

        deleted_filenames = []
        deleted_qdrant = 0
        for doc in upload_docs:
            filename = doc.get("filename", "")
            owner_id = doc.get("user_id")
            if not filename:
                continue

            if pdf_qdrant_client.collection_exists(PDF_COLLECTION):
                must = [FieldCondition(key="filename", match=MatchValue(value=filename))]
                if owner_id is not None:
                    must.append(FieldCondition(key="user_id", match=MatchValue(value=owner_id)))
                scroll_filter = Filter(must=must)

                next_offset = None
                while True:
                    result, next_offset = pdf_qdrant_client.scroll(
                        collection_name=PDF_COLLECTION,
                        scroll_filter=scroll_filter,
                        limit=100,
                        offset=next_offset,
                        with_payload=False,
                    )
                    if not result:
                        break
                    point_ids = [p.id for p in result]
                    if point_ids:
                        pdf_qdrant_client.delete(collection_name=PDF_COLLECTION, points_selector=point_ids)
                        deleted_qdrant += len(point_ids)
                    if next_offset is None:
                        break

            deleted_filenames.append(filename)

        mongo_result = await get_query_log_collection().delete_many(
            {"_id": {"$in": [doc["_id"] for doc in upload_docs]}}
        )

        return {
            "status":                "ok",
            "deleted_filenames":     deleted_filenames,
            "qdrant_chunks_deleted": deleted_qdrant,
            "mongo_deleted":         mongo_result.deleted_count,
        }

    # ── Suggestions (base list) ──────────────────────────────────────────
    @app.get("/api/suggestions")
    async def get_suggestions_endpoint():
        return {"suggestions": _read_static_suggestions(config.question_file_path)}

    # ── PDF experts ──────────────────────────────────────────────────────
    @app.get("/api/pdf-experts")
    async def get_pdf_experts_endpoint(request: Request, response: Response):
        _, session = get_or_create_session(request, response)
        return {"experts": session.pdf_experts}

    @app.post("/api/pdf-experts/build")
    async def build_pdf_experts_endpoint(request: Request, response: Response):
        _, session = get_or_create_session(request, response)

        if not session.pdf_subjects:
            session.pdf_experts = []
            return {"experts": []}

        if len(session.pdf_subjects) == 1:
            filename, summary = next(iter(session.pdf_subjects.items()))
            session.pdf_experts = [{
                "name": summary or filename, "filenames": [filename], "avatar_id": None, "scope_mode": "own"
            }]
            return {"experts": session.pdf_experts}

        listing = "\n".join(f'- "{fn}": {summary}' for fn, summary in session.pdf_subjects.items())
        prompt = f"""You are grouping uploaded documents by SUBJECT so each distinct subject can
get its own expert. Documents covering the same subject/topic go in the same group;
documents on different subjects go in different groups.

Documents (filename: subject summary):
{listing}

Output ONLY a JSON array, no markdown, no explanation, in this exact shape:
[{{"name": "short subject label", "filenames": ["file1.pdf", "file2.pdf"]}}, ...]

Every filename listed above must appear in exactly one group."""

        raw = (await config.call_llm(prompt)).strip()
        try:
            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.startswith("json"):
                    raw = raw[4:]
            groups = json.loads(raw)
            assert isinstance(groups, list)
        except Exception as e:
            print(f"⚠️ pdf-experts clustering failed, falling back to one expert per file: {e}")
            groups = [{"name": s or fn, "filenames": [fn]} for fn, s in session.pdf_subjects.items()]

        session.pdf_experts = [
            {"name": g.get("name", "Expert"), "filenames": g.get("filenames", []), "avatar_id": None, "scope_mode": "own"}
            for g in groups if g.get("filenames")
        ]
        return {"experts": session.pdf_experts}

    @app.post("/api/pdf-experts/assign-avatar")
    async def assign_pdf_expert_avatar_endpoint(request: Request, response: Response):
        _, session = get_or_create_session(request, response)
        body = await request.json()
        expert_name = body.get("name")
        avatar_id = body.get("avatar_id")

        for expert in session.pdf_experts:
            if expert["name"] == expert_name:
                expert["avatar_id"] = avatar_id
                return {"status": "assigned", "experts": session.pdf_experts}

        return JSONResponse({"error": "Expert not found"}, status_code=404)

    @app.post("/api/pdf-experts/set-scope-mode")
    async def set_pdf_expert_scope_mode_endpoint(request: Request, response: Response):
        _, session = get_or_create_session(request, response)
        body = await request.json()
        expert_name = body.get("name")
        scope_mode = body.get("scope_mode")

        if scope_mode not in ("own", "all"):
            return JSONResponse({"error": "scope_mode must be 'own' or 'all'"}, status_code=400)

        for expert in session.pdf_experts:
            if expert["name"] == expert_name:
                expert["scope_mode"] = scope_mode
                return {"status": "updated", "experts": session.pdf_experts}

        return JSONResponse({"error": "Expert not found"}, status_code=404)

    # ── Avatar catalog ───────────────────────────────────────────────────
    @app.get("/api/avatar-catalog")
    async def avatar_catalog_endpoint(request: Request):
        api_key = request.headers.get("X-LiveAvatar-Key") or config.liveavatar_api_key
        if not api_key:
            return JSONResponse({"error": "LIVEAVATAR_API_KEY not set"}, status_code=500)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.liveavatar.com/v1/avatars/public",
                    headers={"X-API-KEY": api_key},
                )
            if resp.status_code != 200:
                return JSONResponse(
                    {"error": "LiveAvatar API error", "status": resp.status_code, "details": resp.text},
                    status_code=502,
                )
            return resp.json()
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── Agent workflow trace / related links / clear ────────────────────
    @app.get("/api/trace")
    async def trace_endpoint():
        """Node-by-node execution trace of the most recently completed chat
        turn, for the Agent Workflow panel."""
        return {"trace": config.get_trace()}

    @app.get("/api/related-links")
    async def related_links_endpoint(query: str):
        try:
            links = await asyncio.to_thread(fetch_related_links, query)
        except Exception as e:
            print(f"Error fetching related links: {e}")
            return JSONResponse({"error": "Failed to fetch related links.", "links": []}, status_code=502)
        return {"links": links}

    @app.post("/api/clear")
    async def clear_endpoint(request: Request, response: Response):
        _, session = get_or_create_session(request, response)
        session.pdf_filenames = []
        return {"status": "cleared"}

    # ── History ──────────────────────────────────────────────────────────
    @app.get("/api/history")
    async def history_endpoint():
        sessions_collection = get_sessions_collection()
        history_list = []
        cursor = sessions_collection.find().sort("date", -1)
        async for document in cursor:
            history_list.append({
                "id": document["_id"],
                "title": document["title"],
                "date": document["date"]
            })
        return {"history": history_list}

    @app.delete("/api/history/{session_id}")
    async def delete_history_endpoint(session_id: str):
        sessions_collection = get_sessions_collection()
        result = await sessions_collection.delete_one({"_id": session_id})
        if result.deleted_count == 1:
            return {"status": "deleted"}
        return {"status": "error", "message": "Session not found"}

    @app.post("/api/restore/{history_id}")
    async def restore_endpoint(history_id: str, request: Request, response: Response):
        get_or_create_session(request, response)
        sessions_collection = get_sessions_collection()
        document = await sessions_collection.find_one({"_id": history_id})
        if document:
            return {"status": "restored", "chat_id": history_id, "messages": document["messages"]}
        return {"status": "error", "message": "Session not found"}

    # ── Admin: groups ────────────────────────────────────────────────────
    @app.get("/api/admin/groups")
    async def admin_get_groups(request: Request):
        user = await get_current_user(request)
        if not user or not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required.")
        groups = []
        async for doc in get_groups_collection().find():
            groups.append({"id": str(doc["_id"]), "name": doc["name"], "liveavatar_token": doc.get("liveavatar_token", "")})
        return {"groups": groups}

    @app.post("/api/admin/groups")
    async def admin_create_group(req: GroupCreateRequest, request: Request):
        user = await get_current_user(request)
        if not user or not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required.")
        group_id = str(uuid.uuid4())
        await get_groups_collection().insert_one({
            "_id": group_id,
            "name": req.name,
            "liveavatar_token": req.liveavatar_token
        })
        return {"status": "created", "group_id": group_id}

    # ── Admin: ElevenLabs TTS key pool ──────────────────────────────────
    @app.get("/api/admin/elevenlabs-keys")
    async def admin_get_elevenlabs_keys(request: Request):
        user = await get_current_user(request)
        if not user or not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required.")
        doc = await get_tts_config_collection().find_one({"_id": "elevenlabs"}) or {}
        keys = doc.get("keys", [])
        return {
            "keys": [
                {
                    "key_preview": (k["key"][:6] + "…" + k["key"][-4:]) if len(k.get("key", "")) > 12 else k.get("key", ""),
                    "exhausted": k.get("exhausted", False),
                }
                for k in keys
            ],
            "current_index": doc.get("current_index", 0),
            "voice_id": doc.get("voice_id", ""),
        }

    @app.post("/api/admin/elevenlabs-keys")
    async def admin_set_elevenlabs_keys(req: ElevenLabsConfigRequest, request: Request):
        user = await get_current_user(request)
        if not user or not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required.")
        new_keys = [k.strip() for k in req.keys if k.strip()][:7]
        existing_doc = await get_tts_config_collection().find_one({"_id": "elevenlabs"}) or {}
        existing_by_key = {k["key"]: k for k in existing_doc.get("keys", [])}
        keys = [
            {
                "key": k,
                "exhausted": existing_by_key.get(k, {}).get("exhausted", False),
                "resolved_voice_id": existing_by_key.get(k, {}).get("resolved_voice_id"),
            }
            for k in new_keys
        ]
        await get_tts_config_collection().update_one(
            {"_id": "elevenlabs"},
            {"$set": {"keys": keys, "voice_id": req.voice_id or None}},
            upsert=True,
        )
        return {"status": "saved", "count": len(keys)}

    @app.post("/api/admin/elevenlabs-keys/reset")
    async def admin_reset_elevenlabs_keys(request: Request):
        user = await get_current_user(request)
        if not user or not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required.")
        doc = await get_tts_config_collection().find_one({"_id": "elevenlabs"}) or {}
        keys = [{"key": k["key"], "exhausted": False} for k in doc.get("keys", [])]
        await get_tts_config_collection().update_one(
            {"_id": "elevenlabs"}, {"$set": {"keys": keys, "current_index": 0}}, upsert=True
        )
        return {"status": "reset", "count": len(keys)}

    @app.post("/api/tts")
    async def tts_endpoint(req: TtsRequest):
        text = (req.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="text is required")

        doc = await get_tts_config_collection().find_one({"_id": "elevenlabs"})
        keys = doc.get("keys", []) if doc else []
        if not keys:
            return JSONResponse({"error": "no_keys_configured"}, status_code=503)

        admin_voice_id = doc.get("voice_id") or config.default_tts_voice_id
        start_index = (doc.get("current_index", 0) or 0) % len(keys)

        async with httpx.AsyncClient(timeout=30.0) as client:
            for offset in range(len(keys)):
                idx = (start_index + offset) % len(keys)
                entry = keys[idx]
                if entry.get("exhausted"):
                    continue

                voice_id = admin_voice_id or entry.get("resolved_voice_id")
                if not voice_id:
                    voice_id = await _resolve_voice_id(client, entry["key"])
                    if not voice_id:
                        continue
                    await get_tts_config_collection().update_one(
                        {"_id": "elevenlabs", "keys.key": entry["key"]},
                        {"$set": {"keys.$.resolved_voice_id": voice_id}},
                    )

                try:
                    resp = await client.post(
                        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                        headers={
                            "xi-api-key": entry["key"],
                            "Content-Type": "application/json",
                            "Accept": "audio/mpeg",
                        },
                        json={
                            "text": text,
                            "model_id": "eleven_multilingual_v2",
                            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                        },
                    )
                except httpx.HTTPError as e:
                    print(f"⚠️ ElevenLabs request failed on key #{idx + 1}: {e}")
                    continue

                if resp.status_code == 200:
                    if idx != start_index:
                        await get_tts_config_collection().update_one(
                            {"_id": "elevenlabs"}, {"$set": {"current_index": idx}}
                        )
                    return StreamingResponse(iter([resp.content]), media_type="audio/mpeg")

                if resp.status_code in (401, 429):
                    await get_tts_config_collection().update_one(
                        {"_id": "elevenlabs", "keys.key": entry["key"]},
                        {"$set": {"keys.$.exhausted": True}},
                    )
                    continue

                if resp.status_code == 402:
                    if not admin_voice_id:
                        await get_tts_config_collection().update_one(
                            {"_id": "elevenlabs", "keys.key": entry["key"]},
                            {"$unset": {"keys.$.resolved_voice_id": ""}},
                        )
                    print(f"⚠️ ElevenLabs 402 on key #{idx + 1} for voice {voice_id}: {resp.text[:200]}")
                    continue

                print(f"⚠️ ElevenLabs TTS error {resp.status_code}: {resp.text[:200]}")
                break

        return JSONResponse({"error": "all_keys_exhausted"}, status_code=503)

    # ── Admin: users ─────────────────────────────────────────────────────
    @app.get("/api/admin/users")
    async def admin_get_users(request: Request):
        user = await get_current_user(request)
        if not user or not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required.")
        users = []
        async for doc in get_users_collection().find():
            users.append({"id": str(doc["_id"]), "name": doc["name"], "group_id": doc.get("group_id")})
        return {"users": users}

    @app.post("/api/admin/users/assign")
    async def admin_assign_group(req: AssignGroupRequest, request: Request):
        user = await get_current_user(request)
        if not user or not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required.")

        if not req.group_id:
            await get_users_collection().update_one({"_id": req.user_id}, {"$unset": {"group_id": ""}})
        else:
            await get_users_collection().update_one({"_id": req.user_id}, {"$set": {"group_id": req.group_id}})
        return {"status": "assigned"}

    # ── LiveAvatar: session token ────────────────────────────────────────
    @app.post("/api/avatar-token")
    async def avatar_token(http_request: Request, body: AvatarTokenRequest = AvatarTokenRequest()):
        api_key = http_request.headers.get("X-LiveAvatar-Key")
        if not api_key:
            user = await get_current_user(http_request)
            if user and user.get("group_id"):
                group = await get_groups_collection().find_one({"_id": user["group_id"]})
                if group and group.get("liveavatar_token"):
                    api_key = group["liveavatar_token"]
            if not api_key:
                api_key = config.liveavatar_api_key

        if not api_key:
            return JSONResponse({"error": "LIVEAVATAR_API_KEY not set"}, status_code=500)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.liveavatar.com/v1/sessions/token",
                    headers={
                        "X-API-KEY": api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "mode": "FULL",
                        "avatar_id": body.avatar_id or config.avatar_id_default,
                        "is_sandbox": False,
                        "interactivity_type": "CONVERSATIONAL",
                        "avatar_persona": {
                            "language": "en"
                        }
                    }
                )
            raw = resp.json()
            print("LIVEAVATAR RAW RESPONSE:", resp.status_code, raw)

            if resp.status_code != 200:
                return JSONResponse(
                    {"error": "LiveAvatar API error", "status": resp.status_code, "details": raw},
                    status_code=500
                )

            data = raw.get("data") if isinstance(raw, dict) else None
            if not isinstance(data, dict):
                return JSONResponse(
                    {"error": "Unexpected response shape from LiveAvatar", "raw": raw},
                    status_code=500
                )

            token = data.get("session_token") or data.get("token")
            session_id = data.get("session_id") or data.get("id")
            if not token:
                return JSONResponse({"error": "No token in response", "raw": raw}, status_code=500)

            return {"token": token, "session_id": session_id}
        except Exception as e:
            print("AVATAR TOKEN EXCEPTION:", repr(e))
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── Speech-to-text ───────────────────────────────────────────────────
    @app.post("/api/transcribe")
    async def transcribe_audio(audio: UploadFile = File(...)):
        whisper_model = config.get_whisper_model()
        if whisper_model is None:
            return JSONResponse({"error": "Whisper model is not loaded."}, status_code=500)

        try:
            fd, temp_path = tempfile.mkstemp(suffix=".webm")
            with os.fdopen(fd, 'wb') as f:
                f.write(await audio.read())

            segments, info = whisper_model.transcribe(temp_path, beam_size=5)
            text = "".join([segment.text for segment in segments])
            os.remove(temp_path)
            return JSONResponse({"text": text.strip()})
        except Exception as e:
            print(f"Error during transcription: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.websocket("/api/ws/transcribe")
    async def websocket_transcribe(websocket: WebSocket):
        """
        WebSocket endpoint for real-time self-hosted streaming ASR powered by Nemotron-3.5-ASR-streaming-0.6b.
        Client streams raw 16kHz PCM audio bytes; server streams back live text JSON frames.
        """
        await websocket.accept()

        if config.get_nemotron_model() is None:
            await websocket.send_json({
                "type": "error",
                "message": "Nemotron ASR model is not loaded on this server (missing NeMo/transformers "
                           "dependency or an incompatible torch version) — switch to Browser Native in Settings."
            })
            await websocket.close()
            print("🎙️ Nemotron ASR WebSocket rejected — model not loaded")
            return

        session = config.nemotron_session_cls(sample_rate=16000)
        print("🎙️ WebSocket client connected for Nemotron ASR streaming")
        try:
            while True:
                data = await websocket.receive()
                if "bytes" in data and data["bytes"]:
                    session.append_audio_chunk(data["bytes"])
                    text = await asyncio.to_thread(session.process_buffer)
                    if text:
                        await websocket.send_json({"type": "transcript", "text": text, "is_final": False})
                elif "text" in data and data["text"]:
                    try:
                        msg = json.loads(data["text"])
                        if msg.get("action") == "reset":
                            session.reset()
                        elif msg.get("action") == "finalize":
                            text = await asyncio.to_thread(session.process_buffer)
                            await websocket.send_json({"type": "transcript", "text": text, "is_final": True})
                            session.reset()
                    except Exception:
                        pass
        except WebSocketDisconnect:
            print("🎙️ WebSocket client disconnected from Nemotron ASR")
        except Exception as e:
            print(f"WebSocket transcription error: {e}")

    # ── Static assets + page routes ─────────────────────────────────────
    # follow_symlink=True: the common CSS/HTML files shared between the two
    # apps are symlinked into each app's frontend/ tree (see
    # PROJECTS_COMPARISON.md) — Starlette's StaticFiles defaults to NOT
    # following symlinks, which would 404 every one of them.
    app.mount("/static", StaticFiles(directory=config.frontend_path, follow_symlink=True), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(config.frontend_path, "index.html"))

    @app.get("/c/{chat_id}")
    async def serve_chat_url(chat_id: str):
        """ChatGPT-style deep link (/c/<chat_id>) — serves the same SPA shell;
        script.js reads the chat_id out of the URL on load and calls
        /api/restore/{chat_id} to load that conversation."""
        return FileResponse(os.path.join(config.frontend_path, "index.html"))

    @app.get("/query-log")
    async def serve_query_log():
        """Admin-only page listing which user made what query and what output
        they got (see /api/query-log) — linked from the Profile modal for admins."""
        return FileResponse(os.path.join(config.frontend_path, "query-log.html"))
