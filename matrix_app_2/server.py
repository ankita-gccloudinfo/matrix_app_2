from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
import os
import re
import sys
import json
import uuid
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

# Shared code lives in ../common (see common/routes.py) — both this app and
# ai_sayak_medical_up import from it instead of keeping duplicate copies.
# Everything below that ISN'T imported from common is specific to this app:
# the SQL/Qdrant/Neo4j intel agent graph, MySQL, and the district/feed/
# network-graph endpoints further down. (The VM Monitor subprocess used to
# live here too — it's now owned by admin_config/server.py, see there.)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

PROJECT_ID = "matrix_app"

# Must run BEFORE importing ollamaagent2/database.mysql_db/services.pdf_rag
# below — those modules read their config (MYSQL_*, QDRANT_*, NEO4J_*,
# PDF_QDRANT_*, ...) from os.environ at import time, so any admin-configured
# override (see django/admin_config) has to land in os.environ before that
# import happens. No-ops gracefully if nothing has been configured yet.
from common.project_config import apply_project_config
apply_project_config(PROJECT_ID)

from ollamaagent2 import graph as agent_app, call_llm, is_safe_sql, clear_trace, get_trace
from common.database.mongo import get_sessions_collection
from database.mysql_db import get_district_counts, get_feed_posts, run_query, get_posts_by_ids
from services.location import deduct_location, UP_DISTRICTS
from common.services.transcription import load_whisper_model, get_whisper_model
from services.pdf_rag import load_rerank_worker, stop_rerank_worker, ingest_pdf, extract_pages
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
AVATAR_ID = "65f9e3c9-d48b-4118-b73a-4ae2e3cbb8f0"  # "June HR" — confirmed valid public avatar for this account
# ────────────────────────────────────────────────────────────────

# This file's own self-signed HTTPS cert (see the __main__ block at the
# bottom) — kept here regardless of the VM Monitor, which used to also read
# these same two paths before it moved to admin_config/server.py (it now
# manages its own subprocess and cert check there).
_CERT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cert.pem")
_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "key.pem")
_HAS_TLS_CERT = os.path.exists(_CERT_PATH) and os.path.exists(_KEY_PATH)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_whisper_model()
    load_nemotron_model()
    load_rerank_worker()
    yield
    stop_rerank_worker()

app = FastAPI(title="Police Intel API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from typing import Optional, List, Dict

frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
question_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "question")

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
    expert_name: Optional[str] = None
    lang: Optional[str] = "en"
    chat_id: Optional[str] = None


class LocationRequest(BaseModel):
    latitude: float
    longitude: float


class SpeakRequest(BaseModel):
    session_id: Optional[str] = None
    text: str


class SqlPostsRequest(BaseModel):
    ids: List[int]

@app.post("/api/sql-posts")
async def sql_posts_endpoint(request: SqlPostsRequest):
    try:
        posts = await asyncio.to_thread(get_posts_by_ids, request.ids)
        return {"posts": posts}
    except Exception as e:
        print(f"Error fetching SQL posts: {e}")
        return JSONResponse({"error": "Failed to fetch SQL posts.", "posts": []}, status_code=500)


# ─────────────────────────────────────────────────────────────────────────────
# Chat — kept app-specific (not in common/routes.py). Otherwise identical to
# ai_sayak_medical_up's /api/chat minus the lat/lng emergency-hospital fields.
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat_endpoint(chat_request: ChatRequest, http_request: Request, response: Response):
    _, session = get_or_create_session(http_request, response)
    query = chat_request.query

    chat_id = chat_request.chat_id or str(uuid.uuid4())
    if chat_request.chat_id:
        existing_doc = await get_sessions_collection().find_one({"_id": chat_id})
        messages = existing_doc["messages"].copy() if existing_doc else []
    else:
        messages = []
    messages.append({"role": "user", "content": query})
    question_number = sum(1 for m in messages if m.get("role") == "user")

    current_user = await get_current_user(http_request)
    user_name = current_user["name"] if current_user else "Anonymous"
    user_id = current_user["_id"] if current_user else None

    clear_trace()

    invoke_task = asyncio.create_task(agent_app.ainvoke({
        "query": query,
        "messages": messages,
        "limit": chat_request.limit,
        "session_id": chat_id,
        "expert_name": chat_request.expert_name or "",
        "lang": chat_request.lang,
        "user_id": user_id,
        "user_name": user_name,
        "chat_id": chat_id,
        "question_number": question_number,
    }))

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
    messages.append({"role": "assistant", "content": answer})

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


def _resolve_location_sync(lat: float, lng: float):
    """Both deduct_location (blocking HTTP call) and get_district_counts
    (blocking MySQL call) in one thread hop instead of two — location_endpoint
    just awaits this once. Keeps the two sequential (get_district_counts needs
    deduct_location's result) but off FastAPI's event loop, so this no longer
    stalls every OTHER concurrent request for the ~3-4s this takes."""
    district = deduct_location(lat, lng)
    counts = get_district_counts(district)
    return district, counts


@app.post("/api/location")
async def location_endpoint(request: LocationRequest):
    district, counts = await asyncio.to_thread(
        _resolve_location_sync, request.latitude, request.longitude
    )
    district_coords = {"lat": request.latitude, "lng": request.longitude}

    for d in UP_DISTRICTS:
        if d["name"].lower() == district.lower():
            district_coords = {"lat": d["lat"], "lng": d["lng"]}
            break

    return {
        "district": district,
        "lat": district_coords["lat"],
        "lng": district_coords["lng"],
        "user_lat": request.latitude,
        "user_lng": request.longitude,
        "today_count": counts["today"],
        "yesterday_count": counts["yesterday"],
        "week_count": counts["last_7_days"],
        "total_count": counts["total"]
    }


@app.get("/api/districts")
async def districts_endpoint():
    from database.mysql_db import get_connection

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT primary_district
            FROM analyzed_data
            WHERE DATE(created_at) = CURDATE()
        """)

        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        today_counts = {}

        for (districts,) in rows:
            if not districts:
                continue

            district_text = districts.lower()

            for district in UP_DISTRICTS:
                district_name = district["name"].lower()

                if district_name in district_text:
                    today_counts[district_name] = (
                        today_counts.get(district_name, 0) + 1
                    )

        districts_with_counts = []

        for district in UP_DISTRICTS:
            districts_with_counts.append({
                "name": district["name"],
                "lat": district["lat"],
                "lng": district["lng"],
                "today_count": today_counts.get(
                    district["name"].lower(),
                    0
                )
            })

        return {"districts": districts_with_counts}

    except Exception as e:
        print(f"Error fetching district counts: {e}")
        return {"districts": []}


@app.get("/api/feed")
async def feed_endpoint(district: str, limit: int = 30, offset: int = 0):
    posts = get_feed_posts(district, limit, offset)
    return {"posts": posts}


# ── Network Analysis ("Multi Topic Analysis" sidebar panel) ────────────────
# Merged directly into this app (no separate subprocess/service): reuses
# call_llm and check_sql_safety from ollamaagent2.py so this feature benefits
# from the same PII-column/forbidden-keyword/table-allowlist safety gate as
# the rest of the app, instead of a separate weaker mini safety-check.
# The SQL-generation prompt itself stays dedicated to this feature's own
# schema/output contract (graph vs. users vs. posts shape) — ollamaagent2's
# general chat prompt doesn't know about that 3-shape contract, and routing
# this through the full conversational graph would return natural-language
# text instead of the structured rows nodeanalysis.html's D3 graph needs.

_NETWORK_SQL_PROMPT = """You are an expert MySQL query generator for a network graph analysis database.
Your ONLY task is to convert the user's natural language request into a SINGLE valid MySQL SELECT query.

================================================
🚨 DATABASE SCHEMA
================================================
You have access to only these 4 tables:

1. topic
   - unique_topic_id: varchar(255) (UUID)
   - topic_title: varchar(255)
   - broad_category: longtext (JSON array)
   - sub_category: longtext (JSON array)
   - primary_districts: longtext (JSON array)
   - total_no_of_post: bigint

2. analyzed_data
   - id: int
   - unique_topic_id: varchar(255) (Links to topic.unique_topic_id)
   - post_user_id: int (Links to post_users.id)
   - input_text: text
   - created_at: datetime
   - sentiment_label: varchar(20)

3. post_users
   - id: int
   - username: varchar(255)
   - display_name: varchar(255)
   - platform: varchar(20)
   - followers_count: bigint
   - following_count: bigint
   - bio_description: text
   - profile_image_url: text
   - is_verified: tinyint(1)
   - location: varchar(255)

4. category_handle_master
   - id: bigint
   - category_name: text
   - handle_name: text

================================================
🚨 INSTRUCTIONS FOR USER INTENT TYPES
================================================
Your query MUST match one of these 3 patterns based on what the user asks for:

---
PATTERN A: NETWORK GRAPH / RELATIONSHIPS (Default)
Use this if the user wants to see "connections", "network", "analyze a user", or "relationships".
You MUST select:
- Topic columns: unique_topic_id, topic_title, broad_category, sub_category, primary_districts, total_no_of_post
- User columns: pu.id AS user_id, username, display_name, platform, followers_count, following_count, profile_image_url, bio_description, is_verified, location
- Link metrics: COUNT(ad.id) AS userPostCount
- Classification: MAX(chm.category_name) as handle_category
JOIN `analyzed_data ad` with `topic t ON ad.unique_topic_id = t.unique_topic_id`
JOIN `post_users pu ON ad.post_user_id = pu.id`
LEFT JOIN `category_handle_master chm ON (chm.handle_name = pu.username OR CONCAT('@', chm.handle_name) = pu.username)`
GROUP BY all selected user and topic columns.
Example: "Analyze Yogi Adityanath" -> filter by `pu.username LIKE '%yogi%'` or similar.

---
PATTERN B: FIND ACTIVE USERS / USERS TABLE
Use this if the user asks for a list of "top active users", "top 20 users", "active users", or "search users".
You MUST query `post_users` and count topics and posts from `analyzed_data`.
If looking for top active users involved in more than 3 topics:
Select: `u.id, u.username, u.display_name, u.platform, u.followers_count, u.following_count, ad_agg.total_topics_involved, ad_agg.total_posts_involved`
JOIN:
  `post_users u` joined with `(SELECT post_user_id, COUNT(DISTINCT unique_topic_id) AS total_topics_involved, COUNT(id) AS total_posts_involved FROM analyzed_data GROUP BY post_user_id HAVING COUNT(DISTINCT unique_topic_id) > 3) ad_agg ON u.id = ad_agg.post_user_id`
Group/Filter: Filter out news handles and category handles if "Others" is specified, or join `category_handle_master chm ON (chm.handle_name = u.username OR CONCAT('@', chm.handle_name) = u.username) AND LOWER(chm.category_name) = LOWER(...)` if a category is given. Limit to 20.
Example: "Find top 20 active users in political handles" -> return active users list.

---
PATTERN C: FETCH POSTS / TIMESTAMPS LIST
Use this if the user asks to "fetch posts", "list posts", or "posts of a user".
You MUST select: `ad.id, ad.input_text AS text, ad.created_at, t.topic_title`
JOIN: `analyzed_data ad LEFT JOIN topic t ON ad.unique_topic_id = t.unique_topic_id`
Filter: by `ad.post_user_id = ...` or user's username. Order by `created_at DESC` and limit to 100.
Example: "Fetch posts for user ID 48502" -> return posts list.

================================================
🚨 OUTPUT RULES
================================================
- Output ONLY the raw SQL query.
- Do NOT wrap the query in markdown code fences.
- Do NOT write explanations, labels, or comments.
- Must be a single SELECT statement without semicolons.

User Query:
"{user_query}"
"""


async def _generate_network_sql(user_query: str) -> str:
    prompt = _NETWORK_SQL_PROMPT.format(user_query=user_query)
    sql = (await call_llm(prompt)).strip()
    sql = re.sub(r"```(?:sql)?", "", sql).strip().strip("`").strip()
    return sql


def _parse_network_rows_to_graph(rows: list) -> dict:
    nodes = []
    links = []
    processed_topics = set()
    processed_users = set()

    for row in rows:
        topic_id = row.get("unique_topic_id")
        user_id = row.get("user_id") or row.get("post_user_id") or row.get("id")

        if topic_id:
            topic_id_str = str(topic_id)
            if topic_id_str not in processed_topics:
                nodes.append({
                    "id": f"topic-{topic_id_str}",
                    "name": row.get("topic_title") or "Unknown Topic",
                    "type": "topic",
                    "postCount": int(row.get("total_no_of_post") or row.get("postCount") or 0),
                    "broadCategory": row.get("broad_category"),
                    "subCategory": row.get("sub_category"),
                    "primaryDistricts": row.get("primary_districts"),
                    "uniqueTopicId": topic_id_str
                })
                processed_topics.add(topic_id_str)

        if user_id:
            user_id_str = str(user_id)
            if user_id_str not in processed_users:
                nodes.append({
                    "id": f"user-{user_id_str}",
                    "name": row.get("display_name") or row.get("username") or "Unknown User",
                    "username": row.get("username"),
                    "platform": row.get("platform") or "unknown",
                    "followersCount": row.get("followers_count"),
                    "followingCount": row.get("following_count"),
                    "profileImageUrl": row.get("profile_image_url"),
                    "bioDescription": row.get("bio_description"),
                    "isVerified": bool(row.get("is_verified") or False),
                    "location": row.get("location"),
                    "handleCategory": row.get("handle_category") or "Others",
                    "type": "user",
                    "userPostCount": int(row.get("userPostCount") or 1)
                })
                processed_users.add(user_id_str)

        if user_id and topic_id:
            links.append({
                "source": f"user-{user_id}",
                "target": f"topic-{topic_id}",
                "weight": int(row.get("userPostCount") or 1)
            })

    return {"nodes": nodes, "links": links}


# ── Social Connection Layers (Followers/Following/Retweets/Likes/Quotes/
# Replies) ───────────────────────────────────────────────────────────────
# A second, separate graph mode alongside the topic<->user graph above: this
# one draws real user<->user relationship edges. Reads the same tables the
# sibling PROD_TWITTER_SERVICE app uses for its own /api/network-graph
# (profile_network for follows, post_user_interactions+post_bank for
# retweet/like/quote/reply) — both apps point at the same up_police_matrix
# DB. Fixed, parameterized SQL (not LLM-generated), so no check_sql_safety
# gate needed here, same as /topics/top20 below.

_CONNECTION_EDGE_TYPES = {"follower", "following", "retweet", "like", "quote", "reply"}
_INTERACTION_EDGE_TYPES = ("retweet", "like", "quote", "reply")


def _in_placeholders(n: int) -> str:
    return ", ".join(["%s"] * n)


def _load_follow_connection_edges(uid_set: set, edge_types: set) -> list:
    """profile_network semantics: user_id = person being followed (target),
    follower_id = person who follows (source)."""
    want_follower = "follower" in edge_types
    want_following = "following" in edge_types
    if (not want_follower and not want_following) or not uid_set:
        return []

    uid_list = list(uid_set)
    placeholders = _in_placeholders(len(uid_list))
    sql = f"""
        SELECT user_id, follower_id
        FROM profile_network
        WHERE platform = 'twitter'
          AND status = 'active'
          AND (user_id IN ({placeholders}) OR follower_id IN ({placeholders}))
    """
    rows = run_query(sql, tuple(uid_list) + tuple(uid_list))

    results = []
    for row in rows:
        target_user_id = int(row["user_id"])
        follower_id = int(row["follower_id"])
        if want_follower and target_user_id in uid_set:
            results.append((follower_id, target_user_id, "follower"))
        if want_following and follower_id in uid_set:
            results.append((follower_id, target_user_id, "following"))
    return results


def _load_interaction_connection_edges(uid_set: set, edge_types: set) -> list:
    """post_user_interactions + post_bank: edge is actor (who interacted) ->
    author (whose post they interacted with)."""
    types_wanted = [t for t in _INTERACTION_EDGE_TYPES if t in edge_types]
    if not types_wanted or not uid_set:
        return []

    uid_list = list(uid_set)
    uid_placeholders = _in_placeholders(len(uid_list))
    type_placeholders = _in_placeholders(len(types_wanted))
    sql = f"""
        SELECT pui.post_user_id, pb.author_user_id, pui.interaction_type
        FROM post_user_interactions pui
        JOIN post_bank pb ON pb.id = pui.post_bank_id
        WHERE pui.post_user_id IN ({uid_placeholders})
          AND pui.interaction_type IN ({type_placeholders})
          AND pb.author_user_id IS NOT NULL
    """
    rows = run_query(sql, tuple(uid_list) + tuple(types_wanted))

    results = []
    for row in rows:
        actor_id = row.get("post_user_id")
        author_id = row.get("author_user_id")
        if actor_id and author_id:
            results.append((int(actor_id), int(author_id), row["interaction_type"]))
    return results


def _fetch_connection_user_profiles(uid_set: set) -> dict:
    if not uid_set:
        return {}
    uid_list = list(uid_set)
    placeholders = _in_placeholders(len(uid_list))
    sql = f"""
        SELECT id, username, display_name, platform, followers_count, following_count,
               profile_image_url, bio_description, is_verified, location
        FROM post_users
        WHERE id IN ({placeholders})
    """
    rows = run_query(sql, tuple(uid_list))
    return {int(r["id"]): r for r in rows}


@app.get("/network/connections")
async def network_connections_endpoint(
    user_id: int,
    edge_types: str = "follower,following",
    depth: int = 1,
    max_nodes: int = 300,
):
    requested_types = {t.strip().lower() for t in edge_types.split(",") if t.strip()}
    requested_types &= _CONNECTION_EDGE_TYPES
    if not requested_types:
        raise HTTPException(status_code=400, detail="No valid edge_types requested.")

    depth = max(1, min(int(depth), 2))
    max_nodes = max(1, min(int(max_nodes), 500))

    seed_set = {user_id}
    all_uids = {user_id}
    edges_raw = []  # (source_id, target_id, connection_type)

    frontier = set(seed_set)
    expanded = set()
    for _hop in range(depth):
        frontier -= expanded
        if not frontier:
            break

        hop_edges = (
            _load_follow_connection_edges(frontier, requested_types)
            + _load_interaction_connection_edges(frontier, requested_types)
        )
        edges_raw.extend(hop_edges)
        expanded |= frontier

        new_uids = set()
        for src, tgt, _etype in hop_edges:
            new_uids.add(src)
            new_uids.add(tgt)
        all_uids |= new_uids
        frontier = new_uids

        if len(all_uids) >= max_nodes:
            break

    truncated = len(all_uids) > max_nodes
    if truncated:
        keep = seed_set | set(list(all_uids - seed_set)[: max_nodes - len(seed_set)])
        all_uids = keep
        edges_raw = [e for e in edges_raw if e[0] in all_uids and e[1] in all_uids]

    profiles = _fetch_connection_user_profiles(all_uids)

    seen_edges = set()
    links = []
    for src, tgt, etype in edges_raw:
        key = (src, tgt, etype)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        links.append({
            "source": f"user-{src}",
            "target": f"user-{tgt}",
            "connectionType": etype,
        })

    connection_counts = {}
    for l in links:
        connection_counts[l["source"]] = connection_counts.get(l["source"], 0) + 1
        connection_counts[l["target"]] = connection_counts.get(l["target"], 0) + 1

    nodes = []
    for uid in all_uids:
        p = profiles.get(uid, {})
        node_id = f"user-{uid}"
        nodes.append({
            "id": node_id,
            "type": "user",
            "name": p.get("display_name") or p.get("username") or f"User {uid}",
            "username": p.get("username"),
            "platform": p.get("platform") or "unknown",
            "followersCount": p.get("followers_count"),
            "followingCount": p.get("following_count"),
            "profileImageUrl": p.get("profile_image_url"),
            "bioDescription": p.get("bio_description"),
            "isVerified": bool(p.get("is_verified") or False),
            "location": p.get("location"),
            "isSeed": uid in seed_set,
            "userPostCount": connection_counts.get(node_id, 1),
        })

    return {
        "type": "connections",
        "nodes": nodes,
        "links": links,
        "stats": {
            "totalNodes": len(nodes),
            "totalEdges": len(links),
            "truncated": truncated,
        },
    }


@app.get("/api/topics/search")
async def search_topics_endpoint(q: str = "", district: str = None, limit: int = 20):
    """Free-text topic search backing the standalone Report Builder page's
    topic picker — kept separate from /topics/top20 below since that
    endpoint already has a live consumer (the network graph UI) with its own
    contract (LIMIT 20, a total_no_of_post floor, category/subcategory
    filters); bolting free-text search onto it risked that contract."""
    sql = "SELECT unique_topic_id, topic_title, total_no_of_post, primary_districts, broad_category FROM topic WHERE 1=1"
    params = []

    if q and q.strip():
        sql += " AND topic_title LIKE %s"
        params.append(f"%{q.strip()}%")

    if district and district.strip() and district != "All":
        sql += " AND primary_districts LIKE %s"
        params.append(f"%{district.strip()}%")

    sql += " ORDER BY total_no_of_post DESC LIMIT %s"
    params.append(max(1, min(limit, 50)))

    try:
        rows = run_query(sql, tuple(params))
        return {"topics": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/topics/top20")
async def network_top20_topics(district: str = None, category: str = None, subcategory: str = None):
    sql = "SELECT unique_topic_id, topic_title, total_no_of_post, primary_districts, broad_category FROM topic WHERE total_no_of_post >= 200"
    params = []

    if district and district.strip() and district != "All":
        sql += " AND primary_districts LIKE %s"
        params.append(f"%{district.strip()}%")

    if subcategory and subcategory.strip():
        sql += " AND sub_category LIKE %s"
        params.append(f"%{subcategory.strip()}%")
    elif category and category.strip() and category != "All":
        sql += " AND broad_category LIKE %s"
        params.append(f"%{category.strip()}%")

    sql += " ORDER BY total_no_of_post DESC LIMIT 20"

    try:
        rows = run_query(sql, tuple(params))
        return rows
    except Exception as e:
        print(f"Error fetching top 20 topics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/network/agent")
async def network_agent_endpoint(q: str):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is empty")

    sql = await _generate_network_sql(q)
    if not sql:
        raise HTTPException(status_code=500, detail="Failed to generate SQL query from prompt.")

    # Safety gate — shared with the main chat pipeline (ollamaagent2.py).
    is_safe = is_safe_sql(sql)
    if not is_safe:
        msg = "SQL query failed safety checks (not a single SELECT or contains blocked keywords)."
        print(f"⚠️ Network SQL safety rejection: {msg}\nQuery: {sql}")
        raise HTTPException(status_code=403, detail=f"Generated SQL failed safety checks: {msg}")

    try:
        rows = run_query(sql)

        if not rows:
            return {"type": "empty", "sql": sql, "rows": []}

        first = rows[0]

        # Type C: Posts list (contains post text and timestamps)
        if "text" in first and "created_at" in first:
            for r in rows:
                if r.get("created_at") and hasattr(r["created_at"], "strftime"):
                    r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
            return {"type": "posts", "sql": sql, "rows": rows}

        # Type B: Users list (contains user stats totals)
        elif "total_topics_involved" in first or "total_posts_involved" in first:
            return {"type": "users", "sql": sql, "rows": rows}

        # Type A: Default connection network graph (nodes & links)
        else:
            graph_data = _parse_network_rows_to_graph(rows)
            return {
                "type": "graph",
                "sql": sql,
                "nodes": graph_data["nodes"],
                "links": graph_data["links"],
            }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Network SQL execution/parsing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Database execution error: {str(e)}")


@app.get("/graph-viewer")
async def serve_graph_viewer():
    """Standalone full-page graph view opened via the 'open in new tab'
    button on any Multi Topic Analysis graph — reads the graph data the
    opener tab stashed in localStorage (see network_graph.js), no server-side
    state involved."""
    return FileResponse(os.path.join(frontend_path, "graph-viewer.html"))


@app.get("/workflow")
async def serve_workflow():
    """Interactive visual workflow diagram for ollamaagent2.py LangGraph."""
    return FileResponse(os.path.join(frontend_path, "ollamaagent2_workflow.html"))



if __name__ == "__main__":
    import uvicorn
    _port = int(os.getenv("PORT", "8123"))
    _ssl_kwargs = {}
    if _HAS_TLS_CERT:
        _ssl_kwargs = {"ssl_certfile": _CERT_PATH, "ssl_keyfile": _KEY_PATH}
        print(f"Starting API Server and Web UI on https://0.0.0.0:{_port} (self-signed cert)")
    else:
        print(f"⚠️ {_CERT_PATH} / {_KEY_PATH} not found — starting on plain HTTP "
              f"(geolocation will NOT work from non-localhost origins; see README for cert setup)")
        print(f"Starting API Server and Web UI on http://0.0.0.0:{_port}")
    uvicorn.run(app, host="0.0.0.0", port=_port, **_ssl_kwargs)