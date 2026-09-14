import asyncio
import base64
import hashlib
import html
import ipaddress
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

from database.mysql_db import run_query
import mcp_services
from bs4 import BeautifulSoup, Tag
from . import template_reskin_engine
from . import adhoc_generation_service


# Base directories
SERVICES_DIR = Path(__file__).resolve().parent
MATRIX_APP_DIR = SERVICES_DIR.parent
WORKSPACE_ROOT = MATRIX_APP_DIR.parent
DYNAMIC_REPORT_MAKER_DIR = WORKSPACE_ROOT / "dynamic_report_maker"
MANIFEST_PATH = DYNAMIC_REPORT_MAKER_DIR / "config" / "manifest.json"
REPORTS_DIR = MATRIX_APP_DIR / "reports"
TEMPLATES_DIR = MATRIX_APP_DIR / "reports" / "templates"

# Same vLLM backend ollamaagent2.py's generate_sql() calls directly (that
# module can't be imported from here — it imports FROM this file, so
# importing it back would be circular). os.getenv wrapper added so an
# admin_config override can reach this even though ollamaagent2.py's own
# copy is a plain literal.
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://10.242.71.180:2211/v1")
VLLM_MODEL_NAME = os.getenv("VLLM_MODEL_NAME", "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY")
VLLM_MAX_CONTEXT = int(os.getenv("VLLM_MAX_CONTEXT", "65536"))
FONTS_DIR = SERVICES_DIR / "fonts"
_NOTO_REGULAR = FONTS_DIR / "NotoSansDevanagari-Regular.ttf"
_NOTO_BOLD = FONTS_DIR / "NotoSansDevanagari-Bold.ttf"

# Ensure reports/templates directories exist
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

_DIRECT_IMAGE_URL_RE = re.compile(
    r"https?://[^\s<>\"']+",
    re.IGNORECASE,
)
_MAX_REPORT_IMAGE_BYTES = 5 * 1024 * 1024
_MAX_REPORT_VIDEO_BYTES = 25 * 1024 * 1024
_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _extract_direct_image_urls(value: Any) -> List[str]:
    """Find direct image URLs in stored post text without treating post pages as images."""
    urls = []
    for match in _DIRECT_IMAGE_URL_RE.findall(str(value or "")):
        candidate = match.rstrip(".,;:!?)]}>")
        path = urlparse(candidate).path.lower()
        if candidate not in urls and re.search(r"\.(?:jpg|jpeg|png|gif|webp)$", path):
            urls.append(candidate)
    return urls[:3]


def _extract_media_urls(value: Any) -> List[str]:
    """Extract HTTP media URLs from JSON, CSV, or plain-text attachment fields."""
    if not value:
        return []
    values = value
    if isinstance(value, str):
        try:
            values = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            values = re.split(r"[,\s]+", value)
    if not isinstance(values, list):
        values = [values]
    urls = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("url") or item.get("src") or item.get("access_url") or item.get("image_access_url")
        if isinstance(item, str):
            for url in _DIRECT_IMAGE_URL_RE.findall(item):
                url = url.rstrip(".,;:!?)]}>")
                if url not in urls:
                    urls.append(url)
    return urls[:5]


def _hydrate_post_media(post: Dict[str, Any], asset_dir: Optional[Path]) -> None:
    """Attach media stored against the analyzed post and its post_bank record."""
    image_urls = []
    video_urls = []
    for field in ("photo_attachment", "attachments", "image_attachment_path", "image_access_url"):
        image_urls.extend(_extract_media_urls(post.get(field)))
    for field in ("video_attachment", "video_attachment_path"):
        video_urls.extend(_extract_media_urls(post.get(field)))
    for row in post.get("attachment_rows", []):
        attachment_type = str(row.get("attachment_type") or row.get("type") or "").lower()
        values = [row.get("image_attachment_path"), row.get("image_access_url"), row.get("access_url")] if "image" in attachment_type else []
        values += [row.get("video_attachment_path")] if "video" in attachment_type else []
        for value in values:
            if "video" in attachment_type:
                video_urls.extend(_extract_media_urls(value))
            else:
                image_urls.extend(_extract_media_urls(value))
    image_urls = list(dict.fromkeys(image_urls))[:5]
    video_urls = list(dict.fromkeys(video_urls))[:5]
    post["image_urls"] = image_urls
    post["video_urls"] = video_urls
    post["image_assets"] = [
        (url, asset) for url in image_urls
        if (asset := _download_report_image(url, asset_dir))
    ]
    post["video_assets"] = [
        (url, asset) for url in video_urls
        if (asset := _download_video_thumbnail(url, asset_dir))
    ]


def _fetch_attachment_rows(analyzed_data_id: Any, post_bank_id: Any) -> List[Dict[str, Any]]:
    rows = run_query(
        "SELECT attachment_type, image_attachment_path, video_attachment_path "
        "FROM common_attachments WHERE post_bank_id = %s OR analyzed_data_id = %s",
        (post_bank_id, analyzed_data_id),
    )
    archive_rows = run_query(
        "SELECT type, image_access_url, access_url, image_attachment_path, "
        "attachment_path FROM archive_media WHERE analyzed_data_id = %s",
        (analyzed_data_id,),
    )
    return (rows or []) + (archive_rows or [])


def _download_report_image(image_url: str, asset_dir: Optional[Path]) -> Optional[str]:
    """Download a small public image and return a self-contained data URL for Chromium."""
    if asset_dir is None:
        return None
    parsed = urlparse(image_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    try:
        if ipaddress.ip_address(parsed.hostname).is_private or ipaddress.ip_address(parsed.hostname).is_loopback:
            return None
    except ValueError:
        pass
    try:
        response = requests.get(
            image_url,
            headers={"User-Agent": "MATRIX-report-generator/1.0"},
            stream=True,
            timeout=(3, 8),
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type not in _IMAGE_MIME_TYPES:
            return None
        if int(response.headers.get("Content-Length") or 0) > _MAX_REPORT_IMAGE_BYTES:
            return None
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            size += len(chunk)
            if size > _MAX_REPORT_IMAGE_BYTES:
                return None
            chunks.append(chunk)
        image_bytes = b"".join(chunks)
        asset_dir.mkdir(parents=True, exist_ok=True)
        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}[content_type]
        asset_path = asset_dir / f"{hashlib.sha256(image_url.encode()).hexdigest()[:16]}{suffix}"
        asset_path.write_bytes(image_bytes)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{content_type};base64,{encoded}"
    except (OSError, requests.RequestException, ValueError):
        return None


def _download_video_thumbnail(video_url: str, asset_dir: Optional[Path]) -> Optional[str]:
    """Download a bounded public video and return its first useful frame as a data URL."""
    if asset_dir is None:
        return None
    parsed = urlparse(video_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    try:
        if ipaddress.ip_address(parsed.hostname).is_private or ipaddress.ip_address(parsed.hostname).is_loopback:
            return None
    except ValueError:
        pass

    temporary_path = None
    thumbnail_path = None
    try:
        response = requests.get(
            video_url,
            headers={"User-Agent": "MATRIX-report-generator/1.0"},
            stream=True,
            timeout=(3, 12),
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if not content_type.startswith("video/") and not re.search(r"\.(?:mp4|webm|mov|m4v)(?:$|\?)", parsed.path, re.I):
            return None
        if int(response.headers.get("Content-Length") or 0) > _MAX_REPORT_VIDEO_BYTES:
            return None

        with tempfile.NamedTemporaryFile(suffix=".video", delete=False) as source_file:
            temporary_path = Path(source_file.name)
            size = 0
            for chunk in response.iter_content(chunk_size=128 * 1024):
                size += len(chunk)
                if size > _MAX_REPORT_VIDEO_BYTES:
                    return None
                source_file.write(chunk)

        asset_dir.mkdir(parents=True, exist_ok=True)
        thumbnail_path = asset_dir / f"{hashlib.sha256(video_url.encode()).hexdigest()[:16]}-video.jpg"
        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", "1", "-i", str(temporary_path),
                "-frames:v", "1", "-vf", "scale=960:-2", str(thumbnail_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=20,
        )
        encoded = base64.b64encode(thumbnail_path.read_bytes()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except (OSError, requests.RequestException, subprocess.SubprocessError, ValueError):
        return None
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)

# Visual identity adapted from matrix_website's report pages (indigo→purple
# glass-card gradient, `#4F46E5`/`#9333EA`) rather than the previous plain
# navy palette — see the report-type-selection plan. Chromium (unlike the
# earlier xhtml2pdf engine) renders CSS gradients correctly, so the badge/
# page-title bands use a real gradient instead of a flat fallback color.
_ACCENT = "#4F46E5"
_ACCENT_2 = "#9333EA"
_ACCENT_GRADIENT = f"linear-gradient(135deg, {_ACCENT} 0%, {_ACCENT_2} 100%)"

# Curated report modules for clean UI selection. "v1": False entries have no
# real data source wired up yet (mentioned_persons needs an NER pipeline we
# don't have; network_graph needs the Neo4j traversal used elsewhere in
# ollamaagent2.py, out of scope for this pass) — they're shown in the picker
# as coming-soon/disabled, never actually selectable or rendered.
CORE_MODULES = [
    {
        "id": "topic_overview",
        "title": "Incident & Topic Overview",
        "description": "Category, affected districts, and total monitored post volume.",
        "keywords": ["overview", "summary", "totals", "districts", "incident"],
        "v1": True,
    },
    {
        "id": "top_posts",
        "title": "Key Posts & Evidence",
        "description": "Recent posts with source URL, author, and sentiment.",
        "keywords": ["top posts", "posts", "evidence", "tweets", "quotes"],
        "v1": True,
    },
    {
        "id": "sentiment_breakdown",
        "title": "Public Sentiment & Reaction",
        "description": "Negative, neutral, and positive distribution across monitored posts.",
        "keywords": ["sentiment", "tone", "positivity", "negativity", "mood", "reaction"],
        "v1": True,
    },
    {
        "id": "platform_distribution",
        "title": "Platform & Source Breakdown",
        "description": "Volume spread across Twitter/X, Instagram, Facebook, YouTube, and other sources.",
        "keywords": ["platforms", "sources", "twitter", "facebook", "instagram", "youtube", "whatsapp"],
        "v1": True,
    },
    {
        "id": "activity_timeline",
        "title": "Incident Progression & Timeline",
        "description": "Daily post volume since the topic started.",
        "keywords": ["timeline", "trends", "daily", "activity", "progression"],
        "v1": True,
    },
    {
        "id": "engagement_breakdown",
        "title": "Engagement Breakdown",
        "description": "Total likes, comments, shares, and views across all monitored posts.",
        "keywords": ["engagement", "likes", "comments", "shares", "views"],
        "v1": True,
    },
    {
        "id": "primary_emotions",
        "title": "Primary Emotions Analysis",
        "description": "Distribution of the dominant emotion detected across monitored posts.",
        "keywords": ["emotions", "mood", "feelings", "anger", "fear", "sadness"],
        "v1": True,
    },
    {
        "id": "posting_pattern",
        "title": "Posting Pattern by Hour & Weekday",
        "description": "When activity concentrates — post volume by hour of day and day of week.",
        "keywords": ["hourly", "weekday", "pattern", "time of day", "peak hours"],
        "v1": True,
    },
    {
        "id": "top_keywords",
        "title": "Top Keywords",
        "description": "Most frequent keywords and phrases extracted from monitored posts.",
        "keywords": ["keywords", "phrases", "cloud", "terms"],
        "v1": True,
    },
    {
        "id": "top_hashtags",
        "title": "Top Hashtags",
        "description": "Most frequent hashtags used across monitored posts.",
        "keywords": ["hashtags", "tags", "cloud"],
        "v1": True,
    },
    {
        "id": "top_mentions",
        "title": "Top Mentions",
        "description": "Accounts and handles most frequently mentioned in monitored posts.",
        "keywords": ["mentions", "handles", "accounts", "tagged"],
        "v1": True,
    },
    {
        "id": "monitored_handle_mentions",
        "title": "Monitored Handle Mentions",
        "description": "Which specifically monitored government/political/news accounts were tagged in these posts, and how often.",
        "keywords": ["monitored handles", "tagged", "government accounts", "monitored accounts"],
        "v1": True,
    },
    {
        "id": "mentioned_persons",
        "title": "Key Figures & Mentioned Persons",
        "description": "Identified persons/handles referenced in posts.",
        "keywords": ["persons", "key figures", "names"],
        "v1": False,
    },
    {
        "id": "network_graph",
        "title": "Amplification & Association Network",
        "description": "Hashtag clusters and amplifier accounts.",
        "keywords": ["network", "influencers", "amplification", "clusters"],
        "v1": False,
    },
    {
        # No data source defined yet — see the dedicated note above
        # compile_pdf_report_from_template's redaction pipeline. Kept as
        # "coming soon" (v1: False) rather than wired to a guessed proxy
        # metric, since an unreviewed proxy would be exactly the kind of
        # plausible-but-invented value the redaction/audit steps exist to
        # catch, just moved upstream of them where they can't see it.
        "id": "escalation_status",
        "title": "Escalation Status",
        "description": "Incident escalation/severity assessment. Not yet available — needs a defined scoring source before this can ship.",
        "keywords": ["escalation", "severity", "urgency", "alert level"],
        "v1": False,
    },
]
V1_COMPONENT_IDS = {m["id"] for m in CORE_MODULES if m["v1"]}

# Second catalog for "trending report" — an aggregate view across a time
# window (not tied to specific topics), modeled on matrix_website's
# /sc/trendReportOneView page. Kept small/v1-only by design (see the
# report-type-selection plan) — the source page has ~10 sections including
# bot-detection leaderboards and interactive maps that are explicitly out of
# scope for this pass.
TRENDING_MODULES = [
    {
        "id": "trending_topics_ranked",
        "title": "Top Trending Topics",
        "description": "Highest-volume topics in the selected window, ranked by post count.",
        "keywords": ["trending", "ranked", "top topics", "volume"],
        "v1": True,
    },
    {
        "id": "category_breakdown",
        "title": "Category Breakdown",
        "description": "Topic volume grouped by category (murder, protest, accident, etc.).",
        "keywords": ["category", "breakdown", "type", "classification"],
        "v1": True,
    },
    {
        "id": "sentiment_breakdown",
        "title": "Public Sentiment & Reaction",
        "description": "Negative, neutral, and positive distribution across all monitored posts in the window.",
        "keywords": ["sentiment", "tone", "positivity", "negativity", "mood"],
        "v1": True,
    },
    {
        "id": "platform_distribution",
        "title": "Platform & Source Breakdown",
        "description": "Volume spread across Twitter/X, Instagram, Facebook, YouTube, and other sources.",
        "keywords": ["platforms", "sources", "twitter", "facebook", "instagram", "youtube"],
        "v1": True,
    },
    {
        "id": "engagement_totals",
        "title": "Engagement Totals",
        "description": "Total likes, comments, shares, and views across all monitored posts in the window.",
        "keywords": ["engagement", "likes", "views", "shares", "comments"],
        "v1": True,
    },
]
V1_TRENDING_COMPONENT_IDS = {m["id"] for m in TRENDING_MODULES if m["v1"]}


def get_component_catalog() -> List[Dict[str, Any]]:
    """Loads the curated analytical components catalog (v1 + coming-soon)."""
    return CORE_MODULES


def get_trending_component_catalog() -> List[Dict[str, Any]]:
    """Loads the trending-report component catalog (v1 only, all 5 real)."""
    return TRENDING_MODULES


async def llm_decide_components(query: str, context_summary: str, call_llm_fn) -> List[str]:
    """Uses the LLM to pick the most relevant *v1* component IDs for this
    query — coming-soon ids are never offered as recommendations since
    report_builder can't actually render them yet."""
    v1_catalog = [item for item in CORE_MODULES if item["v1"]]
    catalog_summary = [
        {"id": item["id"], "name": item["title"], "description": item["description"]}
        for item in v1_catalog
    ]

    prompt = f"""You are a dynamic report component decider for police intelligence analytics.
A user has requested a report or summary:

USER QUERY: {query}
INCIDENT/DATA CONTEXT: {context_summary[:1000]}

AVAILABLE REPORT COMPONENTS:
{json.dumps(catalog_summary, indent=2)}

TASK:
Select 3 to 5 component IDs from the available list that best answer and illustrate the user's inquiry.
Always include 'topic_overview'.

Respond ONLY with a valid JSON array of exact component IDs.
Example: ["topic_overview", "top_posts", "sentiment_breakdown", "platform_distribution"]
"""

    try:
        raw_resp = await call_llm_fn(prompt)
        raw_resp = raw_resp.strip()
        if "```" in raw_resp:
            for part in raw_resp.split("```"):
                cleaned = part.strip()
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].strip()
                if cleaned.startswith("[") and cleaned.endswith("]"):
                    raw_resp = cleaned
                    break

        selected = json.loads(raw_resp)
        if isinstance(selected, list) and len(selected) > 0:
            filtered = [cid for cid in selected if cid in V1_COMPONENT_IDS]
            if filtered:
                if "topic_overview" not in filtered:
                    filtered.insert(0, "topic_overview")
                return filtered
    except Exception as e:
        print(f"[DynamicReportService] LLM Decider fallback due to error: {e}")

    # Sensible default selection — all v1 components.
    return ["topic_overview", "top_posts", "sentiment_breakdown", "platform_distribution", "activity_timeline"]


def generate_claude_picker_card(topic_title: str, catalog: List[Dict[str, Any]], recommended_ids: List[str]) -> str:
    """Renders a markdown multi-selection card. This is the graceful
    plain-text fallback; ollamaagent2.py's dynamic_report_maker step also
    appends a fenced ```json report_picker block to the same answer so the
    frontend can render real checkboxes + a Generate button (see script.js's
    renderChartsAndGraphs) — this markdown stays as the readable version for
    any client that doesn't run that JS."""
    recommended_set = set(recommended_ids)

    card_markdown = f"""### 📄 Intelligence Report Builder: **{topic_title}**

I have analyzed the intelligence data and selected the recommended components for this report:

---

"""

    for item in catalog:
        cid = item["id"]
        title = item.get("title", cid.replace("_", " ").title())
        desc = item.get("description", "")
        if not item.get("v1", True):
            card_markdown += f"- 🔒 **{title}** `[Coming soon]` — *{desc}*\n"
        elif cid in recommended_set:
            card_markdown += f"- [x] **{title}** `[Recommended]` — *{desc}*\n"
        else:
            card_markdown += f"- [ ] **{title}** — *{desc}*\n"

    card_markdown += """
---
👉 **To generate the PDF report, use the button below** (or, if it isn't showing, reply with **`Generate Report`**).
"""
    return card_markdown.strip()


def _safe_json(raw, default):
    """topic.emotional_stats/keywords_cloud/hashtags/mention_id_extraction
    are all stored as JSON text (a dict for the first, arrays for the rest)
    — parses defensively, same tolerance as the existing primary_districts
    JSON-parse in fetch_topic_report_data below."""
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, type(default)) else default
    except (json.JSONDecodeError, TypeError):
        return default


# Reuse the existing MATRIX API authentication/call logic directly through a manually maintained endpoint registry, avoiding discovery and its extra LLM calls to keep PDF generation fast.

REPORT_ENRICHMENT_ENDPOINTS = [
    "/api/data/fetchDistReport",
    "/api/data/fetchTelephonicReport",
]

_ENRICHMENT_KEY_BY_PATH = {
    "/api/data/fetchDistReport": "district_report",
    "/api/data/fetchTelephonicReport": "telephonic_report",
}


def _resolve_enrichment_endpoint_url(path: str) -> Optional[str]:
# Uses bare endpoint paths and matches them against mcp_services’ live, fully resolved URLs, so the domain comes from its existing environment-based configuration.
    for known_url in mcp_services.EXTERNAL_ENDPOINTS:
        if known_url.endswith(path):
            return known_url
    return None


def _fetch_report_enrichment(topic_id: str) -> Dict[str, Any]:
    """Calls mcp_services.call_read_endpoints() for every resolvable path in
    REPORT_ENRICHMENT_ENDPOINTS, keyed by topicId. Returns a dict like
    {"district_report": {...}, "telephonic_report": {...}} with only the
    keys that actually resolved and returned data — never raises, since a
    report should still build (with genuine gaps, never fabricated fills)
    if enrichment is unavailable.

    fetch_topic_report_data() is a plain sync function that is ALWAYS
    invoked inside a worker thread (build_report()'s own contract — see its
    docstring: "callers MUST invoke this via asyncio.to_thread"), so there
    is never a running event loop in this call stack. asyncio.run() is safe
    here specifically because of that contract — this is not a pattern to
    copy for a call site that might run on the main event loop."""
    selected, resolved_paths = [], []
    for path in REPORT_ENRICHMENT_ENDPOINTS:
        url = _resolve_enrichment_endpoint_url(path)
        if not url:
            print(
                f"[DynamicReportService] Enrichment endpoint {path!r} not found in "
                f"mcp_services.EXTERNAL_ENDPOINTS — skipping (is MATRIX_API_BASE_URL set, "
                f"and is the endpoint still registered in external_endpoints.json?)"
            )
            continue
        selected.append({"endpoint": url, "method": "GET", "payload": {"topicId": topic_id}})
        resolved_paths.append(path)

    if not selected:
        return {}

    try:
        results = asyncio.run(mcp_services.call_read_endpoints(selected))
    except Exception as exc:
        print(f"[DynamicReportService] Report enrichment call failed for topic {topic_id}: {exc}")
        return {}

    enrichment: Dict[str, Any] = {}
    for path, result in zip(resolved_paths, results):
        if result.get("error"):
            print(f"[DynamicReportService] Enrichment endpoint {path!r} returned an error: {result['error']}")
            continue
        payload = mcp_services.extract_payload(result.get("body"))
        if payload is None:
            continue  # genuinely no data — leave the key absent, never fill with a placeholder
        enrichment[_ENRICHMENT_KEY_BY_PATH.get(path, path)] = payload

    return enrichment


def fetch_topic_report_data(topic_id: str, asset_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Fetches fresh, real data for every v1 component, keyed on
    unique_topic_id. Called at PDF-build time (not at picker-offer time) —
    see the "why re-fetch" note in ollamaagent2.py's report_builder_node:
    the confirm turn is a brand-new HTTP request with no memory of the
    original turn's SQL rows, so this can't reuse anything in-memory."""
    topic_rows = run_query(
        "SELECT topic_title, primary_districts, sub_category, total_no_of_post, created_at, "
        "emotional_stats, keywords_cloud, hashtags, mention_id_extraction "
        "FROM topic WHERE unique_topic_id = %s LIMIT 1",
        (topic_id,),
    )
    topic_row = topic_rows[0] if topic_rows else {}

    sentiment_rows = run_query(
        "SELECT sentiment_label, COUNT(*) AS cnt FROM analyzed_data "
        "WHERE unique_topic_id = %s GROUP BY sentiment_label",
        (topic_id,),
    )
    platform_rows = run_query(
        "SELECT post_bank_core_source AS platform, COUNT(*) AS cnt FROM analyzed_data "
        "WHERE unique_topic_id = %s AND post_bank_core_source IS NOT NULL "
        "GROUP BY post_bank_core_source ORDER BY cnt DESC",
        (topic_id,),
    )
    timeline_rows = run_query(
        "SELECT DATE(created_at) AS day, COUNT(*) AS cnt FROM analyzed_data "
        "WHERE unique_topic_id = %s GROUP BY DATE(created_at) ORDER BY day",
        (topic_id,),
    )
    top_post_rows = run_query(
        "SELECT a.id, a.dump_table_id, a.input_text, a.post_bank_post_url, "
        "a.post_bank_author_name, a.post_bank_author_username, a.sentiment_label, "
        "a.created_at, pb.post_snippet, pb.photo_attachment, pb.video_attachment, "
        "pb.attachments, pb.likes, pb.comments, pb.retweets, pb.views "
        "FROM analyzed_data a LEFT JOIN post_bank pb ON a.dump_table_id = pb.id "
        "WHERE a.unique_topic_id = %s ORDER BY a.created_at DESC LIMIT 5",
        (topic_id,),
    )
    for post in top_post_rows:
        post["attachment_rows"] = _fetch_attachment_rows(post.get("id"), post.get("dump_table_id"))
        if not post.get("post_snippet"):
            post["post_snippet"] = post.get("input_text")
        _hydrate_post_media(post, asset_dir)
    total_posts_row = run_query(
        "SELECT COUNT(*) AS cnt FROM analyzed_data WHERE unique_topic_id = %s",
        (topic_id,),
    )
    total_posts = total_posts_row[0]["cnt"] if total_posts_row else 0

    # analyzed_data has no direct FK to engagement_metric — it joins via
    # dump_table_id = post_bank.id, then engagement_metric via post_bank_id
    # (same join fetch_trending_report_data uses, just scoped to one topic
    # instead of a date range).
    engagement_rows = run_query(
        "SELECT SUM(em.likes) AS total_likes, SUM(em.comments) AS total_comments, "
        "SUM(em.shares) AS total_shares, SUM(em.views) AS total_views "
        "FROM analyzed_data a "
        "JOIN post_bank pb ON a.dump_table_id = pb.id "
        "JOIN engagement_metric em ON em.post_bank_id = pb.id "
        "WHERE a.unique_topic_id = %s",
        (topic_id,),
    )
    engagement = engagement_rows[0] if engagement_rows else {}

    # Distinct from `mentions` (topic.mention_id_extraction — every raw
    # @-mention found in this topic's posts, freeform). This is the curated
    # subset: which of the specifically MONITORED accounts (govt/political/
    # news, per monitor_profiles) were tagged, and how often. Join rule is
    # the one documented against monitor_profiles in DB_SCHEMA_YAML — match
    # analyzed_data.mention_ids_extracted against monitor_profiles.user_name,
    # case-insensitive, leading '@' stripped. No FK, so the JOIN is a LIKE
    # rather than an ON id = id (same caveat the schema docs call out).
    monitored_handle_rows = run_query(
        "SELECT mp.user_name AS handle, mp.category AS category, mp.platform AS platform, "
        "COUNT(*) AS mention_count "
        "FROM analyzed_data a "
        "JOIN monitor_profiles mp "
        "  ON LOWER(a.mention_ids_extracted) LIKE CONCAT('%', LOWER(TRIM(LEADING '@' FROM mp.user_name)), '%') "
        "WHERE a.unique_topic_id = %s "
        "GROUP BY mp.user_name, mp.category, mp.platform "
        "ORDER BY mention_count DESC LIMIT 20",
        (topic_id,),
    )

    hourly_rows = run_query(
        "SELECT HOUR(created_at) AS hr, COUNT(*) AS cnt FROM analyzed_data "
        "WHERE unique_topic_id = %s GROUP BY hr ORDER BY hr",
        (topic_id,),
    )
    weekday_rows = run_query(
        "SELECT DAYOFWEEK(created_at) AS dow, COUNT(*) AS cnt FROM analyzed_data "
        "WHERE unique_topic_id = %s GROUP BY dow ORDER BY dow",
        (topic_id,),
    )
    # MySQL DAYOFWEEK(): 1=Sunday .. 7=Saturday.
    _WEEKDAY_NAMES = ["", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

    # topic.primary_districts is a JSON array; the DB schema's documented
    # rule (see DB_SCHEMA_YAML in ollamaagent2.py) is that only the FIRST
    # element is the topic's actual primary district — the rest are
    # secondary/associated districts and must not be treated as equally
    # relevant (a "लखनऊ - अन्य"-style catch-all topic can list dozens).
    districts_raw = topic_row.get("primary_districts") or ""
    districts = districts_raw
    try:
        parsed = json.loads(districts_raw) if districts_raw else []
        if isinstance(parsed, list) and parsed:
            districts = str(parsed[0])
    except (json.JSONDecodeError, TypeError):
        pass

#   Fetches live MATRIX data to fill genuine gaps, keeps it separately namespaced for clear data provenance, and never lets enrichment failures break the report generation.
    enrichment = _fetch_report_enrichment(topic_id)

  
    viral_alert_rows = run_query(
        "SELECT type, alert_level, viral_score, posts_5min, posts_10min, posts_1hour, "
        "velocity_per_hour, spike_multiplier, accel_5min, platforms_count, primary_district, "
        "engagement_total, telegram_sent, created_at "
        "FROM viral_alerts WHERE unique_topic_id = %s ORDER BY created_at DESC",
        (topic_id,),
    )

    # UNIQUE-keyed — exactly one row per topic (see plan §5), not list-shaped.
    viral_alert_performance_rows = run_query(
        "SELECT first_alert_level, first_alert_time, first_alert_posts, peak_alert_level, "
        "peak_alert_time, peak_posts, time_to_peak_minutes, total_alerts_sent, "
        "final_post_count, was_truly_viral "
        "FROM viral_alert_performance WHERE unique_topic_id = %s LIMIT 1",
        (topic_id,),
    )
    viral_alert_performance = viral_alert_performance_rows[0] if viral_alert_performance_rows else None

    topic_velocity_snapshot_rows = run_query(
        "SELECT snapshot_time, posts_5min, posts_10min, posts_15min, posts_30min, posts_1hour, "
        "accel_5min, accel_10min, velocity_per_hour, spike_multiplier, viral_score, "
        "platforms_count, engagement_total "
        "FROM topic_velocity_snapshots WHERE unique_topic_id = %s ORDER BY snapshot_time",
        (topic_id,),
    )

    news_paper_cutting_rows = run_query(
        "SELECT file_path, news_paper_name, district, eidition_name, eidition_city, "
        "published_date, published_by, remarks, analysis_status "
        "FROM news_paper_cutting WHERE unique_topic_id = %s ORDER BY published_date DESC",
        (topic_id,),
    )

    # No direct unique_topic_id column — one-hop join via analyzed_data_id ->
    # analyzed_data.id -> analyzed_data.unique_topic_id 
    # db_schema_introspect.topic_join_path, which resolves this the same way
    # mechanically for the reskin engine's no_topic_join check).
    sentiment_entity_rows = run_query(
        "SELECT se.entity_name, se.entity_type, se.stance, se.confidence, se.reasoning, se.source "
        "FROM sentiment_entities se "
        "JOIN analyzed_data a ON se.analyzed_data_id = a.id "
        "WHERE a.unique_topic_id = %s",
        (topic_id,),
    )

    return {
        "topic_title": topic_row.get("topic_title", ""),
        "districts": districts or "Not specified",
        "sub_category": topic_row.get("sub_category", "Uncategorized"),
        "created_at": str(topic_row.get("created_at", "")),
        "total_posts": total_posts,
        "sentiment_counts": {r["sentiment_label"] or "Unclassified": r["cnt"] for r in sentiment_rows},
        "platform_counts": {r["platform"]: r["cnt"] for r in platform_rows},
        "timeline": [{"day": str(r["day"]), "cnt": r["cnt"]} for r in timeline_rows],
        "top_posts": top_post_rows,
        "engagement_totals": {
            "likes": int(engagement.get("total_likes") or 0),
            "comments": int(engagement.get("total_comments") or 0),
            "shares": int(engagement.get("total_shares") or 0),
            "views": int(engagement.get("total_views") or 0),
        },
        "hourly_counts": [{"hour": f"{r['hr']:02d}:00", "cnt": r["cnt"]} for r in hourly_rows],
        "weekday_counts": [{"day": _WEEKDAY_NAMES[r["dow"]], "cnt": r["cnt"]} for r in weekday_rows],
        "emotion_counts": _safe_json(topic_row.get("emotional_stats"), {}),
        "keywords": _safe_json(topic_row.get("keywords_cloud"), []),
        "hashtags": _safe_json(topic_row.get("hashtags"), []),
        "mentions": _safe_json(topic_row.get("mention_id_extraction"), []),
        "monitored_handle_mentions": [
            {
                "handle": r["handle"],
                "category": r["category"] or "Uncategorized",
                "platform": r["platform"] or "Unknown",
                "mention_count": r["mention_count"],
            }
            for r in monitored_handle_rows
        ],
        "district_report": enrichment.get("district_report"),
        "telephonic_report": enrichment.get("telephonic_report"),
        "viral_alerts": viral_alert_rows,
        "viral_alert_performance": viral_alert_performance,
        "topic_velocity_snapshots": topic_velocity_snapshot_rows,
        "news_paper_cutting": news_paper_cutting_rows,
        "sentiment_entities": sentiment_entity_rows,
    }


# "असाइन नहीं की गई पोस्ट" ("unassigned posts") / "NOT RELEVANT POST" are
# placeholder/catch-all topics the ingestion pipeline uses for posts that
# don't belong to a real incident — always excluded from ranked/aggregate
# views (same exclusion ollamaagent2.py's generate_sql applies via
# _inject_unassigned_exclusion).
_JUNK_TOPIC_TITLES = ("असाइन नहीं की गई पोस्ट", "NOT RELEVANT POST")


def fetch_trending_report_data(
    date_from: str,
    date_to: str,
    asset_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Fetches real, date-range-scoped (not topic-scoped) data for every
    trending-report component — the aggregate counterpart to
    fetch_topic_report_data, modeled on matrix_website's
    /sc/trendReportOneView page. `date_from`/`date_to` are 'YYYY-MM-DD'.

    IMPORTANT: created_at is a DATETIME column, but date_from/date_to only
    carry a date (no time). `BETWEEN date_from AND date_to` used to get
    both bounds coerced by MySQL to midnight (date_to 00:00:00) — so a
    same-day window (date_from == date_to, e.g. "today's" trending report)
    matched NOTHING except rows at exactly midnight, silently producing an
    empty report even on days with real posts. Fixed by using a half-open
    range instead: created_at >= start-of-day(date_from) AND
    created_at < start-of-day(date_to + 1 day) — this covers every second
    of every day in the range regardless of time-of-day, and behaves
    identically whether the window is one day or many."""
    placeholders = ", ".join(["%s"] * len(_JUNK_TOPIC_TITLES))
    range_start = datetime.strptime(date_from, "%Y-%m-%d")
    range_end_exclusive = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)

    ranked_rows = run_query(
        f"SELECT topic_title, primary_districts, sub_category, total_no_of_post FROM topic "
        f"WHERE created_at >= %s AND created_at < %s AND topic_title NOT IN ({placeholders}) "
        f"ORDER BY total_no_of_post DESC LIMIT 15",
        (range_start, range_end_exclusive, *_JUNK_TOPIC_TITLES),
    )

    category_rows = run_query(
        f"SELECT JSON_UNQUOTE(JSON_EXTRACT(sub_category, '$[0]')) AS category, COUNT(*) AS cnt "
        f"FROM topic WHERE created_at >= %s AND created_at < %s AND sub_category IS NOT NULL "
        f"AND topic_title NOT IN ({placeholders}) "
        f"GROUP BY category ORDER BY cnt DESC LIMIT 15",
        (range_start, range_end_exclusive, *_JUNK_TOPIC_TITLES),
    )

    sentiment_rows = run_query(
        "SELECT sentiment_label, COUNT(*) AS cnt FROM analyzed_data "
        "WHERE created_at >= %s AND created_at < %s GROUP BY sentiment_label",
        (range_start, range_end_exclusive),
    )

    platform_rows = run_query(
        "SELECT post_bank_core_source AS platform, COUNT(*) AS cnt FROM analyzed_data "
        "WHERE created_at >= %s AND created_at < %s AND post_bank_core_source IS NOT NULL "
        "GROUP BY post_bank_core_source ORDER BY cnt DESC",
        (range_start, range_end_exclusive),
    )

    # analyzed_data is a denormalized copy of post_bank with no direct FK —
    # it joins via dump_table_id = post_bank.id (see DB_SCHEMA_YAML's
    # post_hub relationship note in ollamaagent2.py); engagement_metric then
    # joins post_bank via post_bank_id. Verified against the live schema.
    engagement_rows = run_query(
        "SELECT SUM(em.likes) AS total_likes, SUM(em.comments) AS total_comments, "
        "SUM(em.shares) AS total_shares, SUM(em.views) AS total_views "
        "FROM analyzed_data a "
        "JOIN post_bank pb ON a.dump_table_id = pb.id "
        "JOIN engagement_metric em ON em.post_bank_id = pb.id "
        "WHERE a.created_at >= %s AND a.created_at < %s",
        (range_start, range_end_exclusive),
    )
    engagement = engagement_rows[0] if engagement_rows else {}

    total_posts_row = run_query(
        "SELECT COUNT(*) AS cnt FROM analyzed_data WHERE created_at >= %s AND created_at < %s",
        (range_start, range_end_exclusive),
    )
    total_posts = total_posts_row[0]["cnt"] if total_posts_row else 0

    top_post_rows = run_query(
        "SELECT a.id, a.dump_table_id, a.unique_topic_id, a.input_text, "
        "a.post_bank_post_url, a.post_bank_author_name, a.post_bank_author_username, "
        "a.sentiment_label, a.created_at, pb.post_snippet, pb.photo_attachment, "
        "pb.video_attachment, pb.attachments, pb.likes, pb.comments, pb.retweets, pb.views "
        "FROM analyzed_data a LEFT JOIN post_bank pb ON a.dump_table_id = pb.id "
        "WHERE a.created_at >= %s AND a.created_at < %s "
        "ORDER BY COALESCE(pb.likes, 0) + COALESCE(pb.views, 0) DESC LIMIT 10",
        (range_start, range_end_exclusive),
    )
    for post in top_post_rows:
        post["attachment_rows"] = _fetch_attachment_rows(post.get("id"), post.get("dump_table_id"))
        if not post.get("post_snippet"):
            post["post_snippet"] = post.get("input_text")
        _hydrate_post_media(post, asset_dir)

    def _first_district(raw: str) -> str:
        try:
            parsed = json.loads(raw) if raw else []
            return str(parsed[0]) if isinstance(parsed, list) and parsed else "Not specified"
        except (json.JSONDecodeError, TypeError):
            return "Not specified"

    return {
        "date_from": date_from,
        "date_to": date_to,
        "total_posts": total_posts,
        "ranked_topics": [
            {
                "title": r["topic_title"],
                "district": _first_district(r.get("primary_districts")),
                "post_count": r["total_no_of_post"],
            }
            for r in ranked_rows
        ],
        "category_counts": {r["category"] or "Uncategorized": r["cnt"] for r in category_rows},
        "sentiment_counts": {r["sentiment_label"] or "Unclassified": r["cnt"] for r in sentiment_rows},
        "platform_counts": {r["platform"]: r["cnt"] for r in platform_rows},
        "engagement_totals": {
            "likes": int(engagement.get("total_likes") or 0),
            "comments": int(engagement.get("total_comments") or 0),
            "shares": int(engagement.get("total_shares") or 0),
            "views": int(engagement.get("total_views") or 0),
        },
        "top_posts": top_post_rows,
    }


# Semantic colors — sentiment is meaning-coded (green/slate/red), independent
# of the indigo/purple brand accent used everywhere else. Devanagari topic
# titles/post text never flow through these charts (only sentiment labels,
# platform names, and dates do, all Latin/numeric), but rendering bars as
# real HTML/CSS rather than matplotlib PNGs sidesteps that risk entirely
# while also giving crisp, on-brand output instead of matplotlib's default
# Arial-and-black-axes look.
_SENTIMENT_COLORS = {
    "positive": "#16a34a", "neutral": "#64748b", "negative": "#dc2626",
}
_PLATFORM_COLORS = {
    "twitter": "#1d9bf0", "x": "#1d9bf0", "facebook": "#1877f2",
    "instagram": "#c1339a", "youtube": "#ff0000", "whatsapp": "#25d366",
    "news": "#d97706",
}
# Cycled for open-ended label sets (report categories) with no fixed meaning.
_CATEGORICAL_PALETTE = ["#4F46E5", "#9333EA", "#0f766e", "#d97706", "#db2777", "#0284c7", "#65a30d", "#dc2626"]


def _sentiment_color(label: str) -> str:
    return _SENTIMENT_COLORS.get(str(label or "").strip().lower(), "#94a3b8")


def _platform_color(label: str) -> str:
    return _PLATFORM_COLORS.get(str(label or "").strip().lower(), _ACCENT)


def _badge_html(label: str, color: str) -> str:
    return f'<span class="badge-pill" style="background:{color}1a;color:{color};">{label}</span>'


def _bar_list_html(pairs: List[Tuple[str, int]], color_fn=None, show_share: bool = True) -> str:
    """Renders a horizontal bar-list card in pure HTML/CSS — the report's
    stand-in for a chart image. Each row: label, a proportional gradient
    bar (relative to the largest value), and the raw count (+ share of
    total, when show_share). `color_fn(label) -> css color`; defaults to
    the brand accent for every row."""
    pairs = [(str(label), int(count)) for label, count in pairs if count]
    if not pairs:
        return '<p class="empty-note">No data available for this section.</p>'
    color_fn = color_fn or (lambda _label: _ACCENT)
    max_val = max(count for _, count in pairs) or 1
    total = sum(count for _, count in pairs) or 1
    rows = []
    for label, count in pairs:
        pct_of_max = round(count / max_val * 100)
        share = round(count / total * 100)
        color = color_fn(label)
        share_html = f'<span class="bar-share">{share}%</span>' if show_share else ""
        rows.append(f"""
        <div class="bar-row">
            <div class="bar-label" title="{label}">{label}</div>
            <div class="bar-track"><div class="bar-fill" style="width:{pct_of_max}%;background:{color};"></div></div>
            <div class="bar-value">{count:,}{share_html}</div>
        </div>""")
    return f'<div class="bar-chart">{"".join(rows)}</div>'


def _stat_tiles_html(tiles: List[Tuple[str, str]]) -> str:
    """Small KPI-tile row — label/value pairs rendered as cards instead of
    a plain key-value table, for pages that lead with a handful of headline
    numbers (e.g. topic_overview)."""
    cells = "".join(
        f'<div class="stat-tile"><div class="stat-tile-val">{value}</div><div class="stat-tile-lbl">{label}</div></div>'
        for label, value in tiles
    )
    return f'<div class="stat-tiles">{cells}</div>'


# A bar-list already shows every row's exact label, count, and share inline —
# rendering the same rows again as a full detail table underneath is only
# safe for short lists. Past this many rows the pairing can push a single
# A4 page's content past one physical page (confirmed empirically: a 15-row
# category_breakdown overflowed even after tightening card/row spacing),
# which desyncs every later page's hardcoded "Page X of Y" from where
# Chromium actually breaks. Past the threshold, skip the redundant table —
# no data is lost, it's still fully visible (and exact) in the chart card.
_TABLE_DUPLICATE_THRESHOLD = 10


def _table_or_note(row_count: int, table_html: str) -> str:
    if row_count <= _TABLE_DUPLICATE_THRESHOLD:
        return table_html
    return '<p class="chart-note">Full exact counts for every row are shown in the chart above.</p>'


# icon/color per engagement metric — colorful by design (distinct from the
# indigo .stat-tile used elsewhere), matching matrix_website's dashboard
# treatment of this row (see the report-style-matching plan).
_ENGAGEMENT_ICONS = [
    ("likes", "❤️", "#e11d48"),
    ("comments", "💬", "#2563eb"),
    ("shares", "🔁", "#0d9488"),
    ("views", "👁️", "#d97706"),
]


def _icon_stat_tiles_html(totals: Dict[str, int]) -> str:
    tiles = "".join(
        f'<div class="icon-stat-tile" style="--tile-color:{color};">'
        f'<div class="icon-stat-badge">{icon}</div>'
        f'<div class="icon-stat-val">{totals.get(key, 0):,}</div>'
        f'<div class="icon-stat-lbl">{key.title()}</div>'
        f'</div>'
        for key, icon, color in _ENGAGEMENT_ICONS
    )
    return f'<div class="icon-stat-tiles">{tiles}</div>'


# emoji + pastel color per emotion label — keys match topic.emotional_stats'
# JSON keys (Happy/Sad/Angry/Fearful/Disgusted/Surprised/Neutral/Frustrated),
# matched case-insensitively since upstream casing isn't guaranteed.
_EMOTION_STYLE = {
    "happy": ("😊", "#f59e0b"),
    "sad": ("😢", "#3b82f6"),
    "angry": ("😠", "#ef4444"),
    "fearful": ("😨", "#8b5cf6"),
    "disgusted": ("🤢", "#22c55e"),
    "surprised": ("😲", "#f97316"),
    "neutral": ("😐", "#94a3b8"),
    "frustrated": ("😤", "#db2777"),
}


def _emotion_style(label: str):
    return _EMOTION_STYLE.get(str(label or "").strip().lower(), ("🙂", "#94a3b8"))


def _emotion_grid_html(emotion_counts: Dict[str, int]) -> str:
    items = [(label, cnt) for label, cnt in (emotion_counts or {}).items() if cnt]
    if not items:
        return '<p class="empty-note">No emotion data available for this topic.</p>'
    items.sort(key=lambda pair: pair[1], reverse=True)
    total = sum(cnt for _, cnt in items) or 1
    tiles = []
    for label, cnt in items:
        emoji, color = _emotion_style(label)
        share = round(cnt / total * 100)
        tiles.append(
            f'<div class="emotion-tile" style="background:{color}1a;">'
            f'<div class="emotion-emoji">{emoji}</div>'
            f'<div class="emotion-val">{cnt:,}</div>'
            f'<div class="emotion-lbl">{label}</div>'
            f'<div class="emotion-pct">{share}%</div>'
            f'</div>'
        )
    return f'<div class="emotion-grid">{"".join(tiles)}</div>'


# Word-cloud stand-in: topic.keywords_cloud/hashtags/mention_id_extraction are
# plain JSON arrays with no per-item frequency, so there's no honest basis for
# sizing chips by weight — rendered as a flowing chip cloud instead. Capped
# per variant (keywords/hashtags run long; mentions less so) for the same
# reason _table_or_note caps long tables: an unbounded chip list can still
# push a page past one physical A4 sheet.
_TAG_CLOUD_CAPS = {"keyword": 30, "hashtag": 25, "mention": 20}


def _tag_cloud_html(items: List[str], variant: str) -> str:
    items = [str(i).strip() for i in (items or []) if str(i).strip()]
    if not items:
        return '<p class="empty-note">No data available for this section.</p>'
    cap = _TAG_CLOUD_CAPS.get(variant, 25)
    shown, remaining = items[:cap], max(0, len(items) - cap)
    chips = "".join(f'<span class="tag-chip {variant}">{i}</span>' for i in shown)
    more_note = f'<p class="chart-note">+{remaining} more not shown.</p>' if remaining else ""
    return f'<div class="tag-cloud">{chips}</div>{more_note}'


def render_html_page(title: str, content_html: str, page_num: int, total_pages: int) -> str:
    """Renders an individual printable A4 report page."""
    return f"""
    <div class="report-page">
        <div class="header">
            <table width="100%">
                <tr>
                    <td class="header-left">UP POLICE MATRIX — INTELLIGENCE REPORT</td>
                    <td class="header-right">STRICTLY CONFIDENTIAL</td>
                </tr>
            </table>
            <div class="header-line"></div>
        </div>

        <div class="page-title-box">
            <h2>{title.upper()}</h2>
            <span class="page-title-num">{page_num:02d} / {total_pages:02d}</span>
        </div>

        <div class="content-body">
            {content_html}
        </div>

        <div class="footer">
            <div class="footer-line"></div>
            <table width="100%">
                <tr>
                    <td class="footer-left">UP Police Social Media & Cyber Command Centre</td>
                    <td class="footer-right">Page {page_num} of {total_pages}</td>
                </tr>
            </table>
        </div>
    </div>
    """


# A "make a report on all these topics" request (e.g. off a top-10 trending
# list) shouldn't be able to generate an unbounded PDF — cap how many topics
# one report covers; report_builder_node also enforces this on the incoming
# selection, this is the belt-and-suspenders limit at render time.
MAX_TOPICS_PER_REPORT = 15


def _render_component_body(cid: str, topic_data: dict, display_title: str, catalog_map: dict) -> tuple:
    """Renders one component's page title + body HTML for one topic's data.
    Factored out of compile_pdf_report so both the single-topic and
    multi-topic (one report covering several topics) paths can call it once
    per (topic, component) pair instead of duplicating the branch logic."""
    comp = catalog_map.get(cid, {})
    cname = comp.get("title", cid.replace("_", " ").title())
    cdesc = comp.get("description", "")
    body_html = f'<p class="desc-text">{cdesc}</p>'

    if cid == "topic_overview":
        body_html += _stat_tiles_html([
            ("Verified Posts", f"{topic_data['total_posts']:,}"),
            ("Primary District", topic_data['districts']),
            ("First Observed", (topic_data['created_at'] or 'Unknown').split(" ")[0] or 'Unknown'),
        ])
        body_html += f"""
        <div class="table-card">
        <table class="data-table" width="100%">
            <tr><th>Key Parameter</th><th>Verified Metric</th></tr>
            <tr><td>Subject Matter</td><td>{display_title}</td></tr>
            <tr><td>Category</td><td>{topic_data['sub_category']}</td></tr>
            <tr><td>Jurisdiction / District(s)</td><td>{topic_data['districts']}</td></tr>
            <tr><td>Total Social Volume Captured</td><td>{topic_data['total_posts']:,} Verified Posts</td></tr>
            <tr><td>First Observed</td><td>{topic_data['created_at'] or 'Unknown'}</td></tr>
        </table>
        </div>
        """

    elif cid == "top_posts":
        top_posts = topic_data.get("top_posts", [])
        if top_posts:
            posts_html = "".join(_post_card_html(p, idx) for idx, p in enumerate(top_posts, 1))
        else:
            posts_html = '<p class="empty-note">No individual posts found for this topic.</p>'
        body_html += f'<div class="post-list">{posts_html}</div>'

    elif cid == "sentiment_breakdown":
        counts = topic_data.get("sentiment_counts", {})
        total_s = sum(counts.values()) or 1
        table_html = f"""
        <div class="table-card">
        <table class="data-table" width="100%">
            <tr><th>Sentiment</th><th>Post Count</th><th>Share</th></tr>
            {"".join(f'<tr><td>{_badge_html(label, _sentiment_color(label))}</td><td>{cnt:,}</td><td>{round(cnt / total_s * 100)}%</td></tr>' for label, cnt in counts.items()) or "<tr><td colspan='3'>No sentiment data available.</td></tr>"}
        </table>
        </div>
        """
        body_html += f"""
        <div class="chart-card">
            <h3>Sentiment Distribution</h3>
            {_bar_list_html(list(counts.items()), color_fn=_sentiment_color)}
        </div>
        {_table_or_note(len(counts), table_html)}
        """

    elif cid == "platform_distribution":
        counts = topic_data.get("platform_counts", {})
        total_p = sum(counts.values()) or 1
        table_html = f"""
        <div class="table-card">
        <table class="data-table" width="100%">
            <tr><th>Platform</th><th>Post Count</th><th>Share</th></tr>
            {"".join(f'<tr><td>{_badge_html(platform, _platform_color(platform))}</td><td>{cnt:,}</td><td>{round(cnt / total_p * 100)}%</td></tr>' for platform, cnt in counts.items()) or "<tr><td colspan='3'>No platform data available.</td></tr>"}
        </table>
        </div>
        """
        body_html += f"""
        <div class="chart-card">
            <h3>Platform Spread</h3>
            {_bar_list_html(list(counts.items()), color_fn=_platform_color)}
        </div>
        {_table_or_note(len(counts), table_html)}
        """

    elif cid == "activity_timeline":
        timeline = topic_data.get("timeline", [])
        peak = max(timeline, key=lambda t: t["cnt"]) if timeline else None
        peak_note = (
            f'<p class="chart-note">Activity spanned {len(timeline)} day(s), peaking on <strong>{peak["day"]}</strong> with <strong>{peak["cnt"]}</strong> posts.</p>'
            if peak else ""
        )
        table_html = f"""
        <div class="table-card">
        <table class="data-table" width="100%">
            <tr><th>Date</th><th>Posts</th></tr>
            {"".join(f"<tr><td>{t['day']}</td><td>{t['cnt']:,}</td></tr>" for t in timeline) or "<tr><td colspan='2'>No timeline data available.</td></tr>"}
        </table>
        </div>
        """
        body_html += f"""
        <div class="chart-card">
            <h3>Daily Post Volume</h3>
            {_bar_list_html([(t["day"], t["cnt"]) for t in timeline], show_share=False)}
            {peak_note}
        </div>
        {_table_or_note(len(timeline), table_html)}
        """

    elif cid == "engagement_breakdown":
        body_html += _icon_stat_tiles_html(topic_data.get("engagement_totals", {}))

    elif cid == "primary_emotions":
        body_html += f"""
        <div class="chart-card">
            <h3>Primary Emotions</h3>
            {_emotion_grid_html(topic_data.get("emotion_counts", {}))}
        </div>
        """

    elif cid == "posting_pattern":
        hourly = topic_data.get("hourly_counts", [])
        weekday = topic_data.get("weekday_counts", [])
        body_html += f"""
        <div class="chart-card">
            <h3>Post Volume by Hour of Day</h3>
            {_bar_list_html([(h["hour"], h["cnt"]) for h in hourly], show_share=False)}
        </div>
        <div class="chart-card">
            <h3>Post Volume by Day of Week</h3>
            {_bar_list_html([(d["day"], d["cnt"]) for d in weekday], show_share=False)}
        </div>
        """

    elif cid == "top_keywords":
        body_html += f"""
        <div class="chart-card">
            <h3>Top Keywords</h3>
            {_tag_cloud_html(topic_data.get("keywords", []), "keyword")}
        </div>
        """

    elif cid == "top_hashtags":
        body_html += f"""
        <div class="chart-card">
            <h3>Top Hashtags</h3>
            {_tag_cloud_html(topic_data.get("hashtags", []), "hashtag")}
        </div>
        """

    elif cid == "top_mentions":
        mentions = [m if str(m).startswith("@") else f"@{m}" for m in topic_data.get("mentions", [])]
        body_html += f"""
        <div class="chart-card">
            <h3>Top Mentions</h3>
            {_tag_cloud_html(mentions, "mention")}
        </div>
        """

    elif cid == "monitored_handle_mentions":
        rows = topic_data.get("monitored_handle_mentions", [])
        table_html = f"""
        <div class="table-card">
        <table class="data-table" width="100%">
            <tr><th>Handle</th><th>Category</th><th>Platform</th><th>Mentions</th></tr>
            {"".join(f'<tr><td>{r["handle"]}</td><td>{_badge_html(r["category"], _ACCENT)}</td><td>{r["platform"]}</td><td>{r["mention_count"]:,}</td></tr>' for r in rows) or "<tr><td colspan='4'>No monitored handles were tagged in these posts.</td></tr>"}
        </table>
        </div>
        """
        body_html += f"""
        <div class="chart-card">
            <h3>Monitored Handles Tagged</h3>
            {_bar_list_html([(r["handle"], r["mention_count"]) for r in rows], show_share=False)}
        </div>
        {_table_or_note(len(rows), table_html)}
        """

    else:
        body_html += '<div class="chart-card"><p class="empty-note">This section isn\'t available yet.</p></div>'

    return cname, body_html


def _post_card_html(p: dict, idx: int) -> str:
    """One evidence-post card for the Key Posts & Evidence section with editorial typography and action pills."""
    author = p.get("post_bank_author_name") or p.get("post_bank_author_username") or "Unknown author"
    platform = p.get("platform") or p.get("post_bank_core_source") or "Social Media"
    raw_text = str(p.get("post_snippet") or p.get("input_text") or "").strip()
    # Keep snippet focused and cleanly wrapped inside its card box
    if len(raw_text) > 750:
        text = raw_text[:750].rstrip() + "..."
    else:
        text = raw_text
    url = p.get("post_bank_post_url") or ""
    sentiment = p.get("sentiment_label") or "Unclassified"
    
    # Platform badge
    platform_badge = f'<span class="evidence-platform-badge">{html.escape(str(platform).upper())}</span>'
    sentiment_badge = _badge_html(html.escape(str(sentiment)), _sentiment_color(sentiment))

    # Media attachments (Images & Video thumbnails)
    media_items = []
    for image_url, asset in (p.get("image_assets") or []):
        media_items.append(
            f'<div class="evidence-media-item">'
            f'<a href="{html.escape(str(image_url), quote=True)}" target="_blank" rel="noopener">'
            f'<img src="{html.escape(asset, quote=True)}" alt="Image evidence {idx}" class="evidence-img" />'
            f'</a></div>'
        )
    for video_url, asset in (p.get("video_assets") or []):
        media_items.append(
            f'<div class="evidence-media-item video-thumb-wrap">'
            f'<a href="{html.escape(str(video_url), quote=True)}" target="_blank" rel="noopener">'
            f'<img src="{html.escape(asset, quote=True)}" alt="Video preview {idx}" class="evidence-img" />'
            f'<span class="video-play-icon">▶</span>'
            f'</a></div>'
        )
    media_html = f'<div class="evidence-media-grid">{"".join(media_items)}</div>' if media_items else ""

    # Action URL Link Rows (Visible full URL for printouts + clickable on screen)
    url_rows = []
    if url:
        url_rows.append(
            f'<div class="evidence-link-item">'
            f'<span class="link-tag source-tag">🔗 Post URL:</span> '
            f'<a class="evidence-url-link" href="{html.escape(str(url), quote=True)}" target="_blank" rel="noopener">'
            f'{html.escape(str(url))}</a>'
            f'</div>'
        )
    for i_idx, image_url in enumerate(p.get("image_urls") or [], 1):
        tag_lbl = "🖼️ Image:" if len(p.get("image_urls") or []) == 1 else f"🖼️ Image {i_idx}:"
        url_rows.append(
            f'<div class="evidence-link-item">'
            f'<span class="link-tag media-tag">{tag_lbl}</span> '
            f'<a class="evidence-url-link" href="{html.escape(str(image_url), quote=True)}" target="_blank" rel="noopener">'
            f'{html.escape(str(image_url))}</a>'
            f'</div>'
        )
    for v_idx, video_url in enumerate(p.get("video_urls") or [], 1):
        tag_lbl = "▶️ Video:" if len(p.get("video_urls") or []) == 1 else f"▶️ Video {v_idx}:"
        url_rows.append(
            f'<div class="evidence-link-item">'
            f'<span class="link-tag video-tag">{tag_lbl}</span> '
            f'<a class="evidence-url-link" href="{html.escape(str(video_url), quote=True)}" target="_blank" rel="noopener">'
            f'{html.escape(str(video_url))}</a>'
            f'</div>'
        )
    actions_html = f'<div class="evidence-urls-container">{"".join(url_rows)}</div>' if url_rows else ""

    # Engagement Metrics Pills
    likes = p.get("likes")
    comments = p.get("comments")
    views = p.get("views")
    metric_pills = []
    if likes is not None:
        metric_pills.append(f'<span class="metric-pill"><span class="m-icon">👍</span> <strong>{int(likes):,}</strong> Likes</span>')
    if comments is not None:
        metric_pills.append(f'<span class="metric-pill"><span class="m-icon">💬</span> <strong>{int(comments):,}</strong> Comments</span>')
    if views is not None:
        metric_pills.append(f'<span class="metric-pill"><span class="m-icon">👁️</span> <strong>{int(views):,}</strong> Views</span>')
    metrics_html = f'<div class="evidence-metrics-row">{"".join(metric_pills)}</div>' if metric_pills else ""

    # Border color based on sentiment
    sent_class = "sent-neutral"
    if str(sentiment).lower() == "negative":
        sent_class = "sent-negative"
    elif str(sentiment).lower() == "positive":
        sent_class = "sent-positive"

    return f"""
    <div class="evidence-post-card {sent_class}">
        <div class="evidence-card-header">
            <div class="header-left">
                <span class="evidence-post-idx">#{idx}</span>
                <strong class="evidence-author">{html.escape(str(author))}</strong>
                {platform_badge}
            </div>
            <div class="header-right">
                {sentiment_badge}
            </div>
        </div>
        <div class="evidence-post-body">
            <div class="post-quote-mark">&ldquo;</div>
            <div class="post-text-content">{html.escape(str(text))}</div>
        </div>
        {media_html}
        <div class="evidence-card-footer">
            {metrics_html}
            {actions_html}
        </div>
    </div>
    """


_EVIDENCE_SECTION_CSS = """
<style id="matrix-evidence-editorial-css">
  .report-evidence {
    margin-top: 36px;
    padding-top: 24px;
    border-top: 2px solid #0f766e;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  .evidence-section-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    margin-bottom: 20px;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 10px;
  }
  .evidence-main-title {
    font-size: 20px;
    font-weight: 800;
    color: #0f172a;
    letter-spacing: -0.02em;
    margin: 0;
  }
  .evidence-sub-title {
    font-size: 12px;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
  }
  .evidence-post-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    margin-bottom: 18px;
    padding: 16px 18px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.03);
    border-left: 5px solid #64748b;
    break-inside: avoid !important;
    page-break-inside: avoid !important;
  }
  .evidence-post-card.sent-negative { border-left-color: #ef4444; }
  .evidence-post-card.sent-positive { border-left-color: #10b981; }
  .evidence-post-card.sent-neutral { border-left-color: #64748b; }
  
  .evidence-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    border-bottom: 1px solid #f1f5f9;
    padding-bottom: 8px;
  }
  .header-left {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .evidence-post-idx {
    font-size: 12px;
    font-weight: 800;
    color: #0f766e;
    background: #ccfbf1;
    padding: 2px 7px;
    border-radius: 4px;
  }
  .evidence-author {
    font-size: 14px;
    color: #0f172a;
    font-weight: 700;
  }
  .evidence-platform-badge {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.04em;
    color: #475569;
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    padding: 2px 6px;
    border-radius: 4px;
  }
  .evidence-post-body {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
  }
  .post-quote-mark {
    font-size: 28px;
    line-height: 1;
    color: #94a3b8;
    font-family: Georgia, serif;
    font-weight: bold;
    user-select: none;
  }
  .post-text-content {
    font-size: 13px;
    line-height: 1.6;
    color: #334155;
    word-break: break-word;
    white-space: pre-wrap;
  }
  .evidence-media-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin: 12px 0;
  }
  .evidence-media-item {
    max-width: 320px;
    max-height: 240px;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid #cbd5e1;
    background: #f8fafc;
    position: relative;
  }
  .evidence-img {
    display: block;
    width: 100%;
    height: auto;
    max-height: 240px;
    object-fit: contain;
  }
  .video-play-icon {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background: rgba(15, 23, 42, 0.75);
    color: #ffffff;
    font-size: 16px;
    padding: 8px 14px;
    border-radius: 50%;
  }
  .evidence-card-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    padding-top: 10px;
    border-top: 1px dashed #e2e8f0;
    margin-top: 8px;
  }
  .evidence-metrics-row {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .metric-pill {
    font-size: 11.5px;
    color: #475569;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    padding: 3px 8px;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .evidence-urls-container {
    display: flex;
    flex-direction: column;
    gap: 5px;
    width: 100%;
    margin-top: 6px;
  }
  .evidence-link-item {
    font-size: 11px;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    padding: 3px 8px;
    border-radius: 6px;
  }
  .link-tag {
    font-weight: 700;
    font-size: 11px;
    border-radius: 4px;
    padding: 1px 4px;
  }
  .link-tag.source-tag { color: #1d4ed8; background: #eff6ff; }
  .link-tag.media-tag { color: #15803d; background: #f0fdf4; }
  .link-tag.video-tag { color: #be185d; background: #fdf2f8; }
  .evidence-url-link {
    color: #0284c7;
    text-decoration: underline;
    word-break: break-all;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 10.5px;
  }
</style>
"""


def _evidence_section_html(posts: List[Dict[str, Any]]) -> str:
    """Provide a deterministic evidence section for template-based reports."""
    if not posts:
        return ""
    cards = "".join(_post_card_html(post, idx) for idx, post in enumerate(posts[:10], 1))
    return f'''
    <section id="matrix-post-evidence" class="report-evidence">
        <div class="evidence-section-header">
            <h2 class="evidence-main-title">Key Social Media & Intelligence Evidence</h2>
            <span class="evidence-sub-title">Grounded Incident Posts & Attachments</span>
        </div>
        <div class="evidence-posts-container">{cards}</div>
    </section>
    '''


def _append_evidence_section(document_html: str, posts: List[Dict[str, Any]]) -> str:
    if not posts or "id=\"matrix-post-evidence\"" in document_html:
        return document_html
    evidence = _evidence_section_html(posts)
    content_to_insert = f"{_EVIDENCE_SECTION_CSS}\n{evidence}"
    return document_html.replace("</body>", f"{content_to_insert}</body>") if "</body>" in document_html else document_html + content_to_insert


def compile_pdf_report(
    report_id: str,
    selected_components: List[str],
    custom_instructions: Optional[str] = None,
    report_type: str = "topic",
    topics: Optional[List[Dict[str, str]]] = None,
    date_range: Optional[Dict[str, str]] = None,
) -> str:
    """Dispatches to the topic-scoped or trending (aggregate/date-range)
    report builder. `report_type="topic"` (default) needs `topics`;
    `report_type="trending"` needs `date_range={"from":...,"to":...}`."""
    if report_type == "trending":
        return _compile_trending_pdf_report(report_id, date_range or {}, selected_components, custom_instructions)
    return _compile_topic_pdf_report(report_id, topics or [], selected_components, custom_instructions)


class ReportValidationError(Exception):
    """Raised by build_report when a selection is missing what
    compile_pdf_report needs (topics/date_range/components) — callers decide
    how to surface it: chat prose for report_builder_node, HTTP 400 for the
    standalone Report Builder page's POST /api/reports/generate."""


def build_report(
    report_type: str,
    components: List[str],
    custom_instructions: str = "",
    topics: Optional[List[Dict[str, str]]] = None,
    date_range: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Shared validation + compile step behind both the chat report-builder
    turn (ollamaagent2.py's report_builder_node) and the standalone Report
    Builder page's POST /api/reports/generate — the two ways a report can be
    requested without re-implementing the same checks twice. Mints a fresh
    report_id server-side (never trust a caller-supplied one — see
    /api/reports/download's _REPORT_ID_RE guard against path traversal).
    Synchronous/blocking (MySQL + Playwright) — callers MUST
    invoke this via asyncio.to_thread. Raises ReportValidationError on a bad
    selection; lets compile_pdf_report's own exceptions propagate."""
    report_type = "trending" if report_type == "trending" else "topic"
    report_id = f"rpt_{uuid.uuid4().hex[:10]}"

    if report_type == "trending":
        date_range = date_range or {}
        if not date_range.get("from") or not components:
            raise ReportValidationError("Missing date_range.from or components for a trending report.")
        pdf_path = compile_pdf_report(report_id, components, custom_instructions, "trending", None, date_range)
        return {
            "report_id": report_id, "pdf_path": pdf_path, "report_type": "trending",
            "components": components, "date_range": date_range,
        }

    topics = [t for t in (topics or []) if t.get("topic_id")][:MAX_TOPICS_PER_REPORT]
    if not topics or not components:
        raise ReportValidationError("Missing topics or components for a topic report.")
    pdf_path = compile_pdf_report(report_id, components, custom_instructions, "topic", topics, None)
    return {
        "report_id": report_id, "pdf_path": pdf_path, "report_type": "topic",
        "components": components, "topics": topics,
    }


def _compile_topic_pdf_report(
    report_id: str,
    topics: List[Dict[str, str]],
    selected_components: List[str],
    custom_instructions: Optional[str] = None,
) -> str:
    """Compiles a multi-page PDF intelligence report via headless Chromium
    (see _render_pdf_from_pages), with real, freshly-fetched data for every
    page (see fetch_topic_report_data — nothing here is fabricated/placeholder).

    `topics` is a list of {"topic_id","topic_title"} — one report can cover
    several topics (e.g. "report on all these trending topics"), each
    getting the full set of `selected_components` (so an N-topic report has
    N * len(selected_components) content pages). A single-topic report is
    just the len(topics) == 1 case of the same code path."""
    # Safety net: never render a component the picker shouldn't have offered,
    # even if a client sent one anyway.
    selected_components = [c for c in selected_components if c in V1_COMPONENT_IDS] or ["topic_overview"]
    topics = (topics or [{"topic_id": "", "topic_title": "Untitled Topic"}])[:MAX_TOPICS_PER_REPORT]
    is_multi = len(topics) > 1

    catalog_map = {item["id"]: item for item in CORE_MODULES}
    report_dir = REPORTS_DIR / report_id
    report_dir.mkdir(parents=True, exist_ok=True)
    pdf_output_path = report_dir / "report.pdf"
    generated_at = datetime.now().strftime("%d %B %Y | %H:%M IST")

    # Fetch every topic's data up front — needed for the cover page's
    # combined totals as well as each topic's own component pages below.
    resolved_topics = []  # list of (display_title, topic_data)
    for t in topics:
        data = fetch_topic_report_data(t.get("topic_id", ""), report_dir / "assets")
        display_title = data.get("topic_title") or t.get("topic_title") or "Untitled Topic"
        resolved_topics.append((display_title, data))

    combined_posts = sum(data["total_posts"] for _, data in resolved_topics)
    combined_districts = ", ".join(sorted({
        data["districts"] for _, data in resolved_topics if data.get("districts")
    })) or "Not specified"
    cover_title = resolved_topics[0][0] if not is_multi else f"{len(topics)} Topics — Combined Intelligence Report"
    total_pages = 1 + len(resolved_topics) * len(selected_components)

    # 1. Render Cover Page (Page 1)
    cover_html = f"""
    <div class="report-page cover-page">
        <div class="header">
            <table width="100%">
                <tr>
                    <td class="header-left">UP POLICE MATRIX CYBER COMMAND</td>
                    <td class="header-right">STRICTLY CONFIDENTIAL</td>
                </tr>
            </table>
            <div class="header-line"></div>
        </div>

        <div class="cover-header">
            <div class="badge">SPECIAL INTELLIGENCE BRIEFING</div>
            <h1>{cover_title}</h1>
            <p class="subtitle">AUTOMATED SOCIAL INTELLIGENCE & INCIDENT REPORT</p>
        </div>

        {_stat_tiles_html([
            ("Total Monitored Posts", f"{combined_posts:,}"),
            ("Primary District(s)", combined_districts),
            ("Topics Covered", str(len(resolved_topics))),
            ("Modules / Topic", str(len(selected_components))),
        ])}

        <div class="cover-meta-box">
            <table class="meta-table" width="100%">
                <tr>
                    <td class="lbl" width="35%">REPORT REFERENCE ID:</td>
                    <td class="val">{report_id}</td>
                </tr>
                <tr>
                    <td class="lbl">GENERATION TIMESTAMP:</td>
                    <td class="val">{generated_at}</td>
                </tr>
                <tr>
                    <td class="lbl">DIRECTIVES / FOCUS:</td>
                    <td class="val">{custom_instructions if custom_instructions else "Comprehensive Intelligence Assessment"}</td>
                </tr>
            </table>
        </div>

        <div class="toc-box">
            <h3>TABLE OF CONTENTS</h3>
            <ol>
    """
    page_counter = 1
    for display_title, _ in resolved_topics:
        if is_multi:
            cover_html += f"<li><strong>{display_title}</strong>"
            cover_html += "<ol>"
        for cid in selected_components:
            page_counter += 1
            comp = catalog_map.get(cid, {})
            cname = comp.get("title", cid.replace("_", " ").title())
            if is_multi:
                cover_html += f"<li>{cname} (Page {page_counter})</li>"
            else:
                cover_html += f"<li><strong>{cname}</strong> (Page {page_counter})</li>"
        if is_multi:
            cover_html += "</ol></li>"

    cover_html += f"""
            </ol>
        </div>

        <div class="footer">
            <div class="footer-line"></div>
            <table width="100%">
                <tr>
                    <td class="footer-left">UP Police Social Media & Cyber Command Centre</td>
                    <td class="footer-right">Page 1 of {total_pages}</td>
                </tr>
            </table>
        </div>
    </div>
    """

    all_pages_html = [cover_html]

    # 2. Render each topic's component pages from real data
    page_num = 1
    for display_title, topic_data in resolved_topics:
        for cid in selected_components:
            page_num += 1
            cname, body_html = _render_component_body(cid, topic_data, display_title, catalog_map)
            # In a multi-topic report, prefix every page title with which
            # topic it belongs to — otherwise "Sentiment Distribution" ×10
            # is meaningless once the pages are out of the cover's context.
            page_title = f"{display_title} — {cname}" if is_multi else cname
            page_html = render_html_page(page_title, body_html, page_num, total_pages)
            all_pages_html.append(page_html)

    _render_pdf_from_pages(pdf_output_path, cover_title, all_pages_html)
    return str(pdf_output_path)


def _render_trending_component_body(cid: str, trending_data: dict, catalog_map: dict) -> tuple:
    """Renders one trending-report component's page title + body HTML from
    date-range-scoped aggregate data (see fetch_trending_report_data).
    Mirrors _render_component_body's shape but operates on aggregate counts
    instead of one topic's data."""
    comp = catalog_map.get(cid, {})
    cname = comp.get("title", cid.replace("_", " ").title())
    cdesc = comp.get("description", "")
    body_html = f'<p class="desc-text">{cdesc}</p>'

    if cid == "trending_topics_ranked":
        ranked = trending_data.get("ranked_topics", [])
        rows_html = "".join(
            f'<tr><td><span class="rank-chip">{idx}</span></td><td>{t["title"]}</td>'
            f'<td>{_badge_html(t["district"], _CATEGORICAL_PALETTE[idx % len(_CATEGORICAL_PALETTE)])}</td>'
            f'<td>{t["post_count"]:,}</td></tr>'
            for idx, t in enumerate(ranked, 1)
        ) or "<tr><td colspan='4'>No trending topics found in this window.</td></tr>"
        body_html += f"""
        <div class="table-card">
        <table class="data-table" width="100%">
            <tr><th>#</th><th>Topic</th><th>District</th><th>Posts</th></tr>
            {rows_html}
        </table>
        </div>
        """

    elif cid == "category_breakdown":
        counts = trending_data.get("category_counts", {})
        color_fn = lambda label: _CATEGORICAL_PALETTE[hash(label) % len(_CATEGORICAL_PALETTE)]
        table_html = f"""
        <div class="table-card">
        <table class="data-table" width="100%">
            <tr><th>Category</th><th>Topic Count</th></tr>
            {"".join(f"<tr><td>{cat}</td><td>{cnt:,}</td></tr>" for cat, cnt in counts.items()) or "<tr><td colspan='2'>No category data available.</td></tr>"}
        </table>
        </div>
        """
        body_html += f"""
        <div class="chart-card">
            <h3>Category Breakdown</h3>
            {_bar_list_html(list(counts.items()), color_fn=color_fn, show_share=False)}
        </div>
        {_table_or_note(len(counts), table_html)}
        """

    elif cid == "sentiment_breakdown":
        counts = trending_data.get("sentiment_counts", {})
        total_s = sum(counts.values()) or 1
        table_html = f"""
        <div class="table-card">
        <table class="data-table" width="100%">
            <tr><th>Sentiment</th><th>Post Count</th><th>Share</th></tr>
            {"".join(f'<tr><td>{_badge_html(label, _sentiment_color(label))}</td><td>{cnt:,}</td><td>{round(cnt / total_s * 100)}%</td></tr>' for label, cnt in counts.items()) or "<tr><td colspan='3'>No sentiment data available.</td></tr>"}
        </table>
        </div>
        """
        body_html += f"""
        <div class="chart-card">
            <h3>Sentiment Distribution</h3>
            {_bar_list_html(list(counts.items()), color_fn=_sentiment_color)}
        </div>
        {_table_or_note(len(counts), table_html)}
        """

    elif cid == "platform_distribution":
        counts = trending_data.get("platform_counts", {})
        total_p = sum(counts.values()) or 1
        table_html = f"""
        <div class="table-card">
        <table class="data-table" width="100%">
            <tr><th>Platform</th><th>Post Count</th><th>Share</th></tr>
            {"".join(f'<tr><td>{_badge_html(platform, _platform_color(platform))}</td><td>{cnt:,}</td><td>{round(cnt / total_p * 100)}%</td></tr>' for platform, cnt in counts.items()) or "<tr><td colspan='3'>No platform data available.</td></tr>"}
        </table>
        </div>
        """
        body_html += f"""
        <div class="chart-card">
            <h3>Platform Spread</h3>
            {_bar_list_html(list(counts.items()), color_fn=_platform_color)}
        </div>
        {_table_or_note(len(counts), table_html)}
        """

    elif cid == "engagement_totals":
        totals = trending_data.get("engagement_totals", {})
        body_html += _stat_tiles_html([
            (label.title(), f"{value:,}") for label, value in totals.items()
        ] or [("Engagement", "No data")])

    else:
        body_html += '<div class="chart-card"><p class="empty-note">This section isn\'t available yet.</p></div>'

    return cname, body_html


def _compile_trending_pdf_report(
    report_id: str,
    date_range: Dict[str, str],
    selected_components: List[str],
    custom_instructions: Optional[str] = None,
) -> str:
    """Compiles an aggregate/trending PDF report — a single set of pages
    summarizing everything in a date window, not scoped to any specific
    topic. Modeled on matrix_website's /sc/trendReportOneView page (see the
    report-type-selection plan)."""
    selected_components = [c for c in selected_components if c in V1_TRENDING_COMPONENT_IDS] or ["trending_topics_ranked"]
    date_from = date_range.get("from") or datetime.now().strftime("%Y-%m-%d")
    date_to = date_range.get("to") or date_from

    catalog_map = {item["id"]: item for item in TRENDING_MODULES}
    report_dir = REPORTS_DIR / report_id
    report_dir.mkdir(parents=True, exist_ok=True)
    pdf_output_path = report_dir / "report.pdf"
    generated_at = datetime.now().strftime("%d %B %Y | %H:%M IST")

    trending_data = fetch_trending_report_data(date_from, date_to)
    cover_title = f"Trending Report — {date_from}" if date_from == date_to else f"Trending Report — {date_from} to {date_to}"
    total_pages = 1 + len(selected_components)

    cover_html = f"""
    <div class="report-page cover-page">
        <div class="header">
            <table width="100%">
                <tr>
                    <td class="header-left">UP POLICE MATRIX CYBER COMMAND</td>
                    <td class="header-right">STRICTLY CONFIDENTIAL</td>
                </tr>
            </table>
            <div class="header-line"></div>
        </div>

        <div class="cover-header">
            <div class="badge">TRENDING INTELLIGENCE BRIEFING</div>
            <h1>{cover_title}</h1>
            <p class="subtitle">AGGREGATE SOCIAL INTELLIGENCE REPORT</p>
        </div>

        {_stat_tiles_html([
            ("Total Monitored Posts", f"{trending_data['total_posts']:,}"),
            ("Window", f"{date_from} to {date_to}" if date_from != date_to else date_from),
            ("Analytical Modules", str(len(selected_components))),
        ])}

        <div class="cover-meta-box">
            <table class="meta-table" width="100%">
                <tr>
                    <td class="lbl" width="35%">REPORT REFERENCE ID:</td>
                    <td class="val">{report_id}</td>
                </tr>
                <tr>
                    <td class="lbl">GENERATION TIMESTAMP:</td>
                    <td class="val">{generated_at}</td>
                </tr>
                <tr>
                    <td class="lbl">DIRECTIVES / FOCUS:</td>
                    <td class="val">{custom_instructions if custom_instructions else "Comprehensive Trend Assessment"}</td>
                </tr>
            </table>
        </div>

        <div class="toc-box">
            <h3>TABLE OF CONTENTS</h3>
            <ol>
    """
    for idx, cid in enumerate(selected_components, 1):
        comp = catalog_map.get(cid, {})
        cname = comp.get("title", cid.replace("_", " ").title())
        cover_html += f"<li><strong>{cname}</strong> (Page {idx + 1})</li>"

    cover_html += f"""
            </ol>
        </div>

        <div class="footer">
            <div class="footer-line"></div>
            <table width="100%">
                <tr>
                    <td class="footer-left">UP Police Social Media & Cyber Command Centre</td>
                    <td class="footer-right">Page 1 of {total_pages}</td>
                </tr>
            </table>
        </div>
    </div>
    """

    all_pages_html = [cover_html]
    for idx, cid in enumerate(selected_components, 1):
        cname, body_html = _render_trending_component_body(cid, trending_data, catalog_map)
        page_html = render_html_page(cname, body_html, idx + 1, total_pages)
        all_pages_html.append(page_html)

    _render_pdf_from_pages(pdf_output_path, cover_title, all_pages_html)
    return str(pdf_output_path)


def _render_pdf_from_pages(pdf_output_path: Path, title_for_head: str, all_pages_html: List[str]) -> None:
    """Shared tail for both the topic and trending report builders: wraps
    the already-rendered page fragments in one HTML document with the report
    CSS, then rasterizes it to `pdf_output_path` via headless Chromium.

    Rendered via real headless Chromium (not xhtml2pdf/reportlab) because
    reportlab has no complex-script text shaping engine — it cannot draw
    Devanagari correctly no matter which font it's given (conjuncts/matra
    reordering need real OpenType shaping). Chromium's own text layout
    handles this correctly, same as any browser. This function is sync and
    is always called via asyncio.to_thread from report_builder_node, which
    is the supported way to use Playwright's sync API from async code."""
    # The @font-face block is built separately (not as part of the big plain
    # CSS string below, which is full of literal { } that would collide with
    # an f-string) so only this small piece needs the font file paths
    # interpolated in. Path.as_uri() (not a hand-rolled "file:///" + posix
    # path) so this comes out correct on both Windows (file:///C:/...) and
    # Linux (file:///home/...) — the slash-count differs between the two.
    font_face_css = f"""
        @font-face {{
            font-family: 'NotoSansDevanagari';
            src: url({_NOTO_REGULAR.as_uri()});
        }}
        @font-face {{
            font-family: 'NotoSansDevanagari';
            font-weight: bold;
            src: url({_NOTO_BOLD.as_uri()});
        }}
    """
    css_styles = """
    <style>
    """ + font_face_css + f"""
        * {{
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
            box-sizing: border-box;
        }}
        @page {{
            size: a4 portrait;
            margin: 1.2cm;
        }}
        body {{
            font-family: 'NotoSansDevanagari', Helvetica, Arial, sans-serif;
            color: #1e293b;
            font-size: 10pt;
            line-height: 1.5;
        }}
        .report-page {{
            page-break-after: always;
        }}
        .header {{
            margin-bottom: 15px;
        }}
        .header-left {{
            font-size: 8.5pt;
            font-weight: bold;
            color: {_ACCENT};
            letter-spacing: 0.4px;
        }}
        .header-right {{
            font-size: 8pt;
            color: #dc2626;
            text-align: right;
            font-weight: bold;
            letter-spacing: 0.5px;
        }}
        .header-line {{
            border-bottom: 1.5pt solid {_ACCENT};
            margin-top: 4px;
            margin-bottom: 12px;
        }}
        .cover-header {{
            text-align: center;
            margin-top: 26px;
            margin-bottom: 22px;
        }}
        .cover-header .badge {{
            display: inline-block;
            background: {_ACCENT_GRADIENT};
            color: #ffffff;
            font-size: 8.5pt;
            font-weight: bold;
            padding: 5px 14px;
            margin-bottom: 12px;
            letter-spacing: 1px;
            border-radius: 999px;
            box-shadow: 0 4px 12px rgba(79, 70, 229, 0.28);
        }}
        .cover-header h1 {{
            font-size: 20pt;
            font-weight: 700;
            color: {_ACCENT};
            margin: 0 0 8px;
            line-height: 1.3;
            letter-spacing: -0.2px;
        }}
        .cover-header .subtitle {{
            font-size: 10pt;
            color: #64748b;
            letter-spacing: 1.5px;
            font-weight: 700;
        }}
        .stat-tiles {{
            display: flex;
            gap: 10px;
            margin: 14px 0;
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        .stat-tile {{
            flex: 1;
            text-align: center;
            background: #ffffff;
            border: 1pt solid #e5e7eb;
            border-radius: 10px;
            padding: 10px 8px;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
        }}
        .stat-tile-val {{
            font-size: 14pt;
            font-weight: 700;
            color: {_ACCENT};
            line-height: 1.2;
        }}
        .stat-tile-lbl {{
            font-size: 7.5pt;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.4px;
            font-weight: 600;
            margin-top: 3px;
        }}
        .cover-meta-box {{
            background-color: #f8fafc;
            border: 1pt solid #e5e7eb;
            border-radius: 10px;
            padding: 12px 14px;
            margin-bottom: 18px;
        }}
        .meta-table td {{
            padding: 5px;
            font-size: 9.5pt;
        }}
        .meta-table .lbl {{
            font-weight: bold;
            color: #334155;
            letter-spacing: 0.2px;
        }}
        .toc-box {{
            border: 1pt solid #e5e7eb;
            border-radius: 10px;
            background-color: #ffffff;
            padding: 14px 16px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
        }}
        .toc-box h3 {{
            color: {_ACCENT};
            font-size: 11pt;
            margin-top: 0;
            margin-bottom: 10px;
            border-bottom: 1pt solid #e5e7eb;
            padding-bottom: 6px;
            letter-spacing: 0.4px;
        }}
        .toc-box ol {{
            margin-left: 20px;
            font-size: 9.5pt;
        }}
        .toc-box li {{
            margin-bottom: 6px;
        }}
        .toc-box li::marker {{
            color: {_ACCENT_2};
            font-weight: 700;
        }}
        .page-title-box {{
            background: {_ACCENT_GRADIENT};
            color: #ffffff;
            padding: 10px 16px;
            margin-bottom: 16px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            box-shadow: 0 4px 14px rgba(79, 70, 229, 0.22);
        }}
        .page-title-box h2 {{
            margin: 0;
            font-size: 12.5pt;
            color: #ffffff;
            letter-spacing: 0.3px;
        }}
        .page-title-num {{
            background: rgba(255, 255, 255, 0.2);
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 8pt;
            font-weight: 700;
            letter-spacing: 0.4px;
            white-space: nowrap;
        }}
        .desc-text {{
            font-size: 9pt;
            color: #64748b;
            margin: 0 0 10px;
            padding-left: 10px;
            border-left: 2pt solid #e2e8f0;
            font-style: italic;
        }}
        .chart-card, .table-card {{
            background-color: #ffffff;
            border: 1pt solid #e5e7eb;
            border-radius: 12px;
            margin-bottom: 12px;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
        }}
        .chart-card {{
            padding: 10px 14px 12px;
        }}
        .chart-card h3 {{
            margin-top: 0;
            margin-bottom: 8px;
            font-size: 10.5pt;
            color: {_ACCENT};
            letter-spacing: 0.2px;
        }}
        .chart-note {{
            font-size: 8.5pt;
            color: #64748b;
            margin: 8px 0 0;
        }}
        .empty-note {{
            font-size: 9pt;
            color: #94a3b8;
            font-style: italic;
            text-align: center;
            padding: 10px 0;
        }}
        .bar-chart {{
            display: flex;
            flex-direction: column;
            gap: 5px;
        }}
        .bar-row {{
            display: flex;
            align-items: center;
            gap: 10px;
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        .bar-label {{
            flex: 0 0 100px;
            font-size: 8.5pt;
            color: #334155;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .bar-track {{
            flex: 1;
            height: 9px;
            background: #f1f5f9;
            border-radius: 999px;
            overflow: hidden;
        }}
        .bar-fill {{
            height: 100%;
            border-radius: 999px;
        }}
        .bar-value {{
            flex: 0 0 auto;
            font-size: 8.5pt;
            font-weight: 700;
            color: #1e293b;
            min-width: 34px;
            text-align: right;
        }}
        .bar-share {{
            font-weight: 500;
            color: #94a3b8;
            margin-left: 4px;
        }}
        .badge-pill {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 999px;
            font-size: 7.5pt;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.3px;
        }}
        .rank-chip {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: {_ACCENT_GRADIENT};
            color: #ffffff;
            font-size: 7.5pt;
            font-weight: 700;
        }}
        .data-table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .data-table th {{
            background-color: {_ACCENT};
            color: #ffffff;
            padding: 6px 10px;
            font-size: 8.5pt;
            text-align: left;
            letter-spacing: 0.2px;
        }}
        .data-table td {{
            padding: 6px 10px;
            border-bottom: 1pt solid #f1f5f9;
            font-size: 9pt;
        }}
        .data-table tr {{
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        .data-table tr:last-child td {{
            border-bottom: none;
        }}
        .data-table tr:nth-child(even) td {{
            background-color: #f8fafc;
        }}
        .post-list {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        .post-item {{
            background-color: #ffffff;
            border: 1pt solid #e5e7eb;
            border-radius: 10px;
            padding: 10px 14px;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        .post-header {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
        }}
        .post-index {{
            font-size: 8pt;
            font-weight: 700;
            color: {_ACCENT_2};
        }}
        .post-author {{
            font-size: 9pt;
            color: #1e293b;
            flex: 1;
        }}
        .post-body {{
            font-size: 8.75pt;
            color: #334155;
            margin-bottom: 8px;
            font-style: italic;
            line-height: 1.55;
        }}
        .post-footer {{
            display: flex;
        }}
        .source-link {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 6px;
            background: {_ACCENT}1a;
            color: {_ACCENT};
            font-size: 7.5pt;
            font-weight: 700;
            text-decoration: none;
        }}
        .source-link.disabled {{
            background: #f1f5f9;
            color: #94a3b8;
        }}
        .icon-stat-tiles {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin: 4px 0 14px;
        }}
        .icon-stat-tile {{
            flex: 1;
            min-width: 100px;
            text-align: center;
            background: #ffffff;
            border: 1pt solid #e5e7eb;
            border-top: 3pt solid var(--tile-color, {_ACCENT});
            border-radius: 12px;
            padding: 12px 8px 10px;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        .icon-stat-badge {{
            font-size: 16pt;
            line-height: 1;
            margin-bottom: 6px;
        }}
        .icon-stat-val {{
            font-size: 14pt;
            font-weight: 700;
            color: var(--tile-color, {_ACCENT});
            line-height: 1.2;
        }}
        .icon-stat-lbl {{
            font-size: 7.5pt;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.4px;
            font-weight: 600;
            margin-top: 3px;
        }}
        .emotion-grid {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }}
        .emotion-tile {{
            flex: 1 1 90px;
            min-width: 90px;
            text-align: center;
            border-radius: 12px;
            padding: 10px 6px;
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        .emotion-emoji {{
            font-size: 18pt;
            line-height: 1;
        }}
        .emotion-val {{
            font-size: 11pt;
            font-weight: 700;
            color: #1e293b;
            margin-top: 4px;
        }}
        .emotion-lbl {{
            font-size: 7.5pt;
            color: #475569;
            text-transform: capitalize;
            font-weight: 600;
            margin-top: 1px;
        }}
        .emotion-pct {{
            font-size: 7pt;
            color: #64748b;
            margin-top: 1px;
        }}
        .tag-cloud {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }}
        .tag-chip {{
            display: inline-block;
            padding: 4px 11px;
            border-radius: 999px;
            font-size: 8pt;
            font-weight: 600;
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        .tag-chip.keyword {{
            background: #fff7ed;
            color: #c2410c;
            border: 1pt solid #fed7aa;
        }}
        .tag-chip.hashtag {{
            background: #eff6ff;
            color: #1d4ed8;
            border: 1pt solid #bfdbfe;
        }}
        .tag-chip.mention {{
            background: #f5f3ff;
            color: #6d28d9;
            border: 1pt solid #ddd6fe;
        }}
        .footer {{
            margin-top: 20px;
        }}
        .footer-line {{
            border-top: 1pt solid #e5e7eb;
            margin-bottom: 6px;
        }}
        .footer-left {{
            font-size: 8pt;
            color: #94a3b8;
        }}
        .footer-right {{
            font-size: 8pt;
            color: #94a3b8;
            text-align: right;
            font-weight: bold;
        }}
    </style>
    """

    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Intelligence Report - {title_for_head}</title>
        {css_styles}
    </head>
    <body>
        {''.join(all_pages_html)}
    </body>
    </html>
    """

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(full_html, wait_until="load")
            page.pdf(path=str(pdf_output_path), print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()

    print(f"[DynamicReportService] Successfully compiled PDF at: {pdf_output_path}")


# =========================
# CUSTOM TEMPLATE REPORTS — user uploads an arbitrary self-contained HTML
# report (built for some other topic, with its own CSS/JS/charts), and we
# reskin it with real data for a topic they pick. Unlike every report path
# above, there's no fixed set of placeholders to fill (the template is
# unknown ahead of time), so an LLM rewrite step is the only way to
# "understand" an arbitrary template well enough to repopulate it.
# =========================

class TemplateRenderError(Exception):
    """Raised when the LLM's rewritten template isn't usable — caller should
    surface this as a clear error rather than handing a broken HTML string
    to Playwright."""


_TEMPLATE_SYSTEM_PROMPT = """You are reskinning an HTML intelligence report template with real data.

You will be given:
1. TEMPLATE_HTML — a complete, self-contained HTML report (inline CSS and, likely, inline/CDN-loaded JS for charts) that was originally built for a DIFFERENT topic, with sample/placeholder content.
2. REAL_DATA_JSON — verified real data for a NEW topic that must replace every piece of sample content.

Rules:
- Preserve the template's overall visual structure, layout, CSS, and chart library usage exactly as given — this is a reskin, not a redesign.
- Replace every piece of sample/placeholder text, numbers, and chart data (including values inside <script> chart-config blocks) with the real data from REAL_DATA_JSON. Update chart labels/series to match.
- NEVER invent a number, name, or fact that is not present in REAL_DATA_JSON. If the template has a section with no corresponding field in REAL_DATA_JSON, either remove that section or clearly mark it "Not available" — do not fabricate a plausible-looking substitute.
- Keep every existing external resource reference (font links, chart library <script src="...">, stylesheet links) byte-for-byte unchanged — do not add, remove, or swap CDN URLs.
- Output ONLY the complete raw HTML document, starting with <!DOCTYPE html>. No markdown code fences, no commentary before or after."""


def _extract_html(text: str) -> str:
    """Strip markdown code fences / stray commentary around the model's HTML
    response, mirroring _extract_sql's tolerance for a chatty model."""
    match = re.search(r"```(?:html)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else text).strip()


def _trim_topic_data_for_llm(topic_data: Dict[str, Any], cap: int) -> Dict[str, Any]:
    """Trims topic_data before sending it into the LLM prompt to avoid
    exceeding model context windows while retaining all key metrics."""
    trimmed = dict(topic_data)
    trimmed["keywords"] = trimmed.get("keywords", [])[:cap]
    trimmed["hashtags"] = trimmed.get("hashtags", [])[:cap]
    trimmed["mentions"] = trimmed.get("mentions", [])[:cap]
    top_posts = []
    for p in trimmed.get("top_posts", [])[: max(2, min(5, cap // 2))]:
        if isinstance(p, dict):
            post_copy = {
                "author": p.get("post_bank_author_name") or p.get("post_bank_author_username") or "User",
                "platform": p.get("platform") or p.get("post_bank_core_source") or "Social Media",
                "text": str(p.get("post_snippet") or p.get("input_text") or "")[:250],
                "sentiment": p.get("sentiment_label") or "Neutral",
                "likes": p.get("likes", 0),
                "comments": p.get("comments", 0),
                "retweets": p.get("retweets", 0),
                "views": p.get("views", 0),
                "date": str(p.get("created_at") or ""),
            }
            top_posts.append(post_copy)
    trimmed["top_posts"] = top_posts
    trimmed.pop("attachment_rows", None)
    trimmed.pop("raw_rows", None)
    return trimmed


def _completion_budget(prompt: str, system_prompt: str = "", requested: int = 8192) -> int:
    """Keep prompt plus completion safely inside the vLLM model context window.
    Uses conservative ~1.6 chars/token estimation with safety buffer."""
    estimated_prompt_tokens = int(len(prompt + system_prompt) / 1.6) + 2048
    available = VLLM_MAX_CONTEXT - estimated_prompt_tokens
    if available < 1024:
        return 1024
    return min(requested, available)


def _call_template_llm(template_html: str, topic_data: Dict[str, Any], custom_instructions: str, cap: int) -> str:
    """One attempt at the template rewrite at a given data-trim level.
    Returns the raw (un-validated) model response text."""
    user_content = (
        f"TEMPLATE_HTML:\n{template_html}\n\n"
        f"REAL_DATA_JSON:\n{json.dumps(_trim_topic_data_for_llm(topic_data, cap), ensure_ascii=False, default=str)}\n"
    )
    if custom_instructions:
        user_content += f"\nADDITIONAL INSTRUCTIONS FROM THE REQUESTER:\n{custom_instructions}\n"

    max_tokens = _completion_budget(user_content, _TEMPLATE_SYSTEM_PROMPT)
    request_payload = {
        "model": VLLM_MODEL_NAME,
        "messages": [
            {"role": "system", "content": _TEMPLATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    response = requests.post(
        f"{VLLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
        json=request_payload,
        timeout=300,
    )
    if response.status_code == 400 and ("maximum context length" in response.text or "input_tokens" in response.text):
        m = re.search(r"value=(\d+)", response.text)
        if m:
            input_tokens = int(m.group(1))
            safe_max = max(512, VLLM_MAX_CONTEXT - input_tokens - 128)
            if safe_max >= 512:
                print(f"[DynamicReportService] Retrying template LLM call with safe max_tokens={safe_max} (input={input_tokens})")
                request_payload["max_tokens"] = safe_max
                response = requests.post(
                    f"{VLLM_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
                    json=request_payload,
                    timeout=300,
                )
    if response.status_code >= 400:
        raise TemplateRenderError(
            f"LLM request rejected ({response.status_code}): {response.text[:500]}"
        )
    response.raise_for_status()
    body = response.json()
    choice = body["choices"][0]
    finish_reason = choice.get("finish_reason")
    content = choice["message"]["content"] or ""
    if finish_reason != "stop" or len(content) < 500:
        print(
            f"[DynamicReportService] Template LLM call: finish_reason={finish_reason!r}, "
            f"template_bytes={len(template_html)}, response_chars={len(content)}, "
            f"preview={content[:200]!r}"
        )
    return content


def _looks_like_html_document(html: str) -> bool:
    return (
        len(html) >= 500
        and (re.match(r"^\s*<!doctype html", html, re.IGNORECASE) or "<html" in html.lower()[:500])
    )


_LARGE_TEMPLATE_BYTES = 50 * 1024  # see the note below on why this is worth calling out separately



# The pre-filter should ignore CSS/JS formatting values (units, colors, and chart-config numbers) so they aren’t falsely flagged as factual claims.
_CSS_NUMBER_UNIT_RE = re.compile(
    r"\b\d[\d,]*\.?\d*(?:px|em|rem|vh|vw|vmin|vmax|deg|ms|fr|%)\b", re.IGNORECASE
)
_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGBA_RE = re.compile(r"rgba?\([^)]*\)")

# CSS url(...) functions and variable-font weight-axis lists (e.g. Google
# Fonts' "family=IBM+Plex+Mono:wght@100;400;500;600;700;800;900&display=swap")
# aren't covered by _CSS_NUMBER_UNIT_RE (no px/em/% suffix on those numbers),
# so a font's weight list was previously extracted as if it were a set of
# standalone factual numbers. Stripped separately here so they're never
# candidates in the first place — see also _split_tags_and_text below, which
# independently keeps this content out of scanning by living inside a tag
# attribute, but <style> blocks can contain the same patterns as plain text.
_CSS_URL_FUNC_RE = re.compile(r"url\([^)]*\)", re.IGNORECASE)
_FONT_WEIGHT_AXIS_RE = re.compile(r"\bwght@[\d;,.]+", re.IGNORECASE)

# Check only standalone 3+ digit numbers that aren’t part of CSS units, colors, or functions—e.g., “1,284 posts” or “arrests: 7342,” but ignore “12px,” “#3b82f6,” and “100%.”
_STANDALONE_NUMBER_RE = re.compile(r"(?<![#.\w])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![.\w])|(?<![#.\w])\d{3,}(?:\.\d+)?(?![.\w%])")

# Flag two or more consecutive capitalized words as possible proper names that may be invented or leftover template content.
_NAMED_PHRASE_RE = re.compile(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+\b")

# Generic template chrome and common report terminology that look like a "named phrase"
# but aren't claims about the topic — flagging these would just cause false redactions.
_NAMED_PHRASE_STOPLIST = {
    "Intelligence Report", "Executive Summary", "Executive Overview", "Table Of Contents",
    "Not Available", "Sentiment Analysis", "Top Posts", "Recent Posts", "United Provinces",
    "Uttar Pradesh", "UP Police", "Platform Distribution", "Engagement Metrics",
    "Trending Topics", "Trending Hashtags", "Emerging Trends", "Intelligence Summary",
    "Confidential Report", "Public Safety", "Community Safety", "Law Enforcement",
    "Total Mentions", "Total Posts", "Total Likes", "Total Comments", "Total Shares", "Total Views",
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "Real-time", "Social Media", "Official Handle",
    "View source", "Open video", "Open image", "Jurisdiction", "Mention Volume",
    "Key Metrics", "Case Status", "Next Steps", "Police Intelligence", "Last 24", "Last 7",
    "All Rights Reserved", "Sentiment Ratio", "Sentiment Breakdown", "Signal Sentiment",
    "Negative Sentiment", "Positive Sentiment", "Neutral Sentiment", "Negative", "Positive", "Neutral",
    "Twitter", "Twitter/X", "Instagram", "Facebook", "YouTube", "WhatsApp", "News",
}

# Matches an HTML tag (anything from "<" to the next ">"), used to split a
# document into alternating (text, tag, text, tag, ...) segments.
_TAG_OR_TEXT_RE = re.compile(r"(<[^>]*>)")


def _split_tags_and_text(html: str) -> List[str]:
    """Splits html on tag boundaries."""
    return _TAG_OR_TEXT_RE.split(html)


def extract_numeric_and_named_tokens(html: str) -> set:
    """Regex-extracts standalone numbers, percentages, and capitalized
    multi-word phrases from rendered HTML — candidate factual claims that
    should trace back to real topic_data.
    Protects user post quotes, feeds, and evidence blocks from being audited."""
    soup = BeautifulSoup(html, "html.parser")
    protected_classes = {
        "post-card", "feed-card", "post-text", "post-meta", "post-snippet",
        "post-evidence", "evidence-card", "evidence-section", "raw-quote",
    }
    
    text_pieces = []
    for text_node in soup.find_all(string=True):
        if any(p.get("class") and any(c in protected_classes for c in p.get("class", [])) for p in text_node.parents if isinstance(p, Tag)):
            continue
        if text_node.parent and text_node.parent.name in ("script", "style", "title", "code"):
            continue
        text_pieces.append(str(text_node))

    text_only = " ".join(text_pieces)
    cleaned = _HEX_COLOR_RE.sub(" ", text_only)
    cleaned = _RGBA_RE.sub(" ", cleaned)
    cleaned = _CSS_URL_FUNC_RE.sub(" ", cleaned)
    cleaned = _FONT_WEIGHT_AXIS_RE.sub(" ", cleaned)
    cleaned = _CSS_NUMBER_UNIT_RE.sub(" ", cleaned)

    tokens = set()
    for m in _STANDALONE_NUMBER_RE.finditer(cleaned):
        tokens.add(m.group().replace(",", ""))
    for m in re.finditer(r"\b\d{1,3}(?:\.\d+)?\s?%", cleaned):
        tokens.add(m.group().strip())
    for m in _NAMED_PHRASE_RE.finditer(cleaned):
        phrase = m.group().strip()
        if phrase not in _NAMED_PHRASE_STOPLIST:
            tokens.add(phrase)
    return tokens


def flatten_topic_data_values(topic_data: Dict[str, Any]) -> set:
    """Flattens every value in topic_data (including nested lists/dicts like
    top_posts, keywords, hashtags, engagement_totals) into a comparable set
    of strings and tokens, so candidate facts can be verified. Numbers are
    normalized without commas so '1,284' and '1284' match."""
    values = set()
    curr_year = datetime.now().strftime("%Y")
    for y in (int(curr_year) - 2, int(curr_year) - 1, int(curr_year), int(curr_year) + 1):
        values.add(str(y))

    def _walk(node):
        if node is None:
            return
        if isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                _walk(v)
        else:
            s = str(node).strip()
            if not s:
                return
            values.add(s)
            values.add(s.replace(",", ""))
            # Also extract standalone sub-tokens (words and numbers) from text strings
            # so numbers and names inside post snippets/details are recognized as grounded
            if len(s) > 5:
                for m in re.finditer(r"\b[\w\d.,%-]+\b", s):
                    w = m.group().strip(".,;:!?()[]{}'\"")
                    if w:
                        values.add(w)
                        values.add(w.replace(",", ""))

    _walk(topic_data)
    return values


def _call_section_reskin_llm(section_html: str, section_data: Dict[str, Any], custom_instructions: str = "") -> str:
    """Reskins an individual HTML section snippet with targeted real data."""
    user_content = (
        f"SECTION_HTML:\n{section_html}\n\n"
        f"SECTION_DATA_JSON:\n{json.dumps(section_data, ensure_ascii=False, default=str)}\n"
    )
    if custom_instructions:
        user_content += f"\nADDITIONAL INSTRUCTIONS:\n{custom_instructions}\n"

    max_tokens = min(4096, max(1024, len(section_html) // 2 + 1024))
    request_payload = {
        "model": VLLM_MODEL_NAME,
        "messages": [
            {"role": "system", "content": _SECTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    response = requests.post(
        f"{VLLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
        json=request_payload,
        timeout=120,
    )
    if response.status_code == 400 and ("maximum context length" in response.text or "input_tokens" in response.text):
        m = re.search(r"value=(\d+)", response.text)
        if m:
            input_tokens = int(m.group(1))
            safe_max = max(512, VLLM_MAX_CONTEXT - input_tokens - 128)
            if safe_max >= 512:
                request_payload["max_tokens"] = safe_max
                response = requests.post(
                    f"{VLLM_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
                    json=request_payload,
                    timeout=120,
                )
    if response.status_code >= 400:
        raise TemplateRenderError(f"Section LLM call rejected ({response.status_code}): {response.text[:300]}")
    response.raise_for_status()
    raw = response.json()["choices"][0]["message"]["content"] or ""
    return _extract_html(raw)


_SECTION_SYSTEM_PROMPT = """You are reskinning ONE SECTION / CARD of an HTML intelligence report with verified real data.

You will be given:
1. SECTION_HTML — a clean HTML snippet (e.g. <section>...</section>, <div class="card">...</div>, <header>...</header>, or <div class="kpi-grid">...</div>).
2. SECTION_DATA_JSON — verified real data for the topic that must replace all placeholder text, numbers, metrics, labels, or lists in this snippet.

Rules:
- Preserve all CSS classes, styling attributes, tag names, and structural hierarchy of this snippet exactly.
- Replace all placeholder/sample values, titles, dates (e.g. sample year 2023 -> current date / year), metrics, percentages, and text with real values from SECTION_DATA_JSON.
- For list/card/table sections (e.g. posts, tag clouds, data rows, platform bars), generate items corresponding to the real items in SECTION_DATA_JSON.
- Preserve standard metric and card labels (such as 'Total Posts', 'Total Mentions', 'Negative Sentiment', 'Total Likes', 'Views', 'Platform Distribution', 'Trending Topics', 'Emerging Trends', etc.) — do NOT replace meaningful English labels with 'Not available'.
- If a metric value is not present in SECTION_DATA_JSON, mark the value cleanly or adapt the text neutrally — NEVER invent or hallucinate unverified numbers or facts.
- Output ONLY the rewritten HTML snippet for this section. Do NOT output <!DOCTYPE html>, <html>, <head>, or <body> wrappers. No markdown code fences, no extra commentary."""

_SCRIPT_SYSTEM_PROMPT = """You are updating the Chart.js / JavaScript chart configuration script in an HTML report with verified real data.

You will be given:
1. SCRIPT_JS — the inline <script>...</script> code containing chart configurations, datasets, and labels.
2. CHART_DATA_JSON — real data for charts (e.g. sentiment counts, platform counts, timeline, emotions, hourly distribution).

Rules:
- Preserve all library initialization logic, canvas element IDs, chart types, colors, options, and styling.
- Replace placeholder data arrays and labels with the corresponding real numbers from CHART_DATA_JSON.
- Output ONLY the complete <script>...</script> block. No markdown code fences, no commentary."""


def _call_script_reskin_llm(script_js: str, chart_data: Dict[str, Any]) -> str:
    """Updates chart datasets in inline <script> tags."""
    user_content = (
        f"SCRIPT_JS:\n{script_js}\n\n"
        f"CHART_DATA_JSON:\n{json.dumps(chart_data, ensure_ascii=False, default=str)}\n"
    )
    request_payload = {
        "model": VLLM_MODEL_NAME,
        "messages": [
            {"role": "system", "content": _SCRIPT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
        "max_tokens": 4096,
    }
    try:
        response = requests.post(
            f"{VLLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
            json=request_payload,
            timeout=120,
        )
        if response.status_code == 200:
            raw = response.json()["choices"][0]["message"]["content"] or ""
            extracted = _extract_html(raw)
            if "<script" in extracted:
                return extracted
    except Exception as exc:
        print(f"[DynamicReportService] Warning: Script chart reskin LLM call failed: {exc}")
    return script_js


def _extract_report_sections(soup: BeautifulSoup) -> Tuple[List[Tag], List[Tag]]:
    """Extracts top-level semantic sections and chart scripts from parsed HTML."""
    body = soup.body
    if not body:
        return [], []

    curr = body
    while True:
        child_tags = [c for c in curr.find_all(recursive=False) if isinstance(c, Tag) and c.name != "script"]
        if len(child_tags) == 1 and child_tags[0].name in ("div", "main", "article", "section"):
            inner_tags = [c for c in child_tags[0].find_all(recursive=False) if isinstance(c, Tag) and c.name != "script"]
            if len(inner_tags) >= 2:
                curr = child_tags[0]
                continue
        break

    container = curr
    direct_children = [c for c in container.find_all(recursive=False) if isinstance(c, Tag) and c.name != "script"]
    
    sections = []
    for child in direct_children:
        classes = " ".join(child.get("class", [])).lower()
        if any(g in classes for g in ["grid", "two-column", "2col", "columns", "row", "flex"]) and len(str(child)) > 2500:
            sub_cards = [c for c in child.find_all(recursive=False) if isinstance(c, Tag) and c.name != "script"]
            if len(sub_cards) >= 2:
                sections.extend(sub_cards)
                continue
        sections.append(child)

    scripts = [s for s in body.find_all("script") if s.string and ("Chart(" in s.string or "getContext" in s.string or "series" in s.string or "new Chart" in s.string)]

    return sections, scripts


def _filter_topic_data_for_section(section_str: str, topic_data: Dict[str, Any]) -> Dict[str, Any]:
    """Filters full topic_data into the specific fields relevant to this section without any data loss or artificial truncation."""
    sec_lower = section_str.lower()
    data: Dict[str, Any] = {
        "topic_title": topic_data.get("topic_title"),
        "sub_category": topic_data.get("sub_category"),
        "districts": topic_data.get("districts"),
        "created_at": topic_data.get("created_at") or datetime.now().strftime("%Y-%m-%d"),
        "current_date": datetime.now().strftime("%B %d, %Y"),
        "current_year": datetime.now().strftime("%Y"),
        "total_posts": topic_data.get("total_posts", 0),
    }

    # Posts / Feed / Intercepted Evidence (full data)
    if any(k in sec_lower for k in ["post", "feed", "tweet", "comment", "quote", "viral", "evidence", "author", "snippet"]):
        top_posts = []
        for p in topic_data.get("top_posts", []):
            if isinstance(p, dict):
                top_posts.append({
                    "author": p.get("post_bank_author_name") or p.get("post_bank_author_username") or "User",
                    "platform": p.get("platform") or p.get("post_bank_core_source") or "Social Media",
                    "text": str(p.get("post_snippet") or p.get("input_text") or ""),
                    "sentiment": p.get("sentiment_label") or "Neutral",
                    "likes": p.get("likes", 0),
                    "comments": p.get("comments", 0),
                    "retweets": p.get("retweets", 0),
                    "views": p.get("views", 0),
                    "date": str(p.get("created_at") or ""),
                })
        data["top_posts"] = top_posts

    # Keywords / Hashtags / Mentions (full data)
    if any(k in sec_lower for k in ["keyword", "hashtag", "tag", "chip", "cloud", "topic", "entity", "focal"]):
        data["keywords"] = topic_data.get("keywords", [])
        data["hashtags"] = topic_data.get("hashtags", [])
        data["mentions"] = topic_data.get("mentions", [])
        data["monitored_handle_mentions"] = topic_data.get("monitored_handle_mentions", [])

    # Sentiment & Emotion
    if any(k in sec_lower for k in ["sentiment", "negative", "positive", "neutral", "emotion", "feeling"]):
        data["sentiment_counts"] = topic_data.get("sentiment_counts", {})
        data["emotion_counts"] = topic_data.get("emotion_counts", {})
        data["sentiment_entities"] = topic_data.get("sentiment_entities", [])

    # Platform Breakdown
    if any(k in sec_lower for k in ["platform", "twitter", "youtube", "facebook", "instagram", "whatsapp", "news", "reach", "channel"]):
        data["platform_counts"] = topic_data.get("platform_counts", {})
        data["monitored_handle_mentions"] = topic_data.get("monitored_handle_mentions", [])

    # KPIs / Metrics / Aggregates
    if any(k in sec_lower for k in ["kpi", "metric", "stat", "val", "like", "share", "view", "total", "engagement", "num"]):
        data["engagement_totals"] = topic_data.get("engagement_totals", {})
        data["sentiment_counts"] = topic_data.get("sentiment_counts", {})
        data["platform_counts"] = topic_data.get("platform_counts", {})
        data["viral_alert_performance"] = topic_data.get("viral_alert_performance", {})
        data["hourly_counts"] = topic_data.get("hourly_counts", [])
        data["weekday_counts"] = topic_data.get("weekday_counts", [])

    # Timeline / Velocity
    if any(k in sec_lower for k in ["timeline", "time", "trend", "velocity", "snapshot", "growth", "hour", "day", "date"]):
        data["timeline"] = topic_data.get("timeline", [])
        data["topic_velocity_snapshots"] = topic_data.get("topic_velocity_snapshots", [])
        data["hourly_counts"] = topic_data.get("hourly_counts", [])
        data["weekday_counts"] = topic_data.get("weekday_counts", [])

    # Tables / news / clippings / alerts
    if any(k in sec_lower for k in ["news", "paper", "cutting", "alert", "incident", "handle", "table"]):
        data["news_paper_cutting"] = topic_data.get("news_paper_cutting", [])
        data["viral_alerts"] = topic_data.get("viral_alerts", [])
        data["monitored_handle_mentions"] = topic_data.get("monitored_handle_mentions", [])

    # Summary / narrative
    if any(k in sec_lower for k in ["overview", "summary", "narrative", "brief", "about", "context"]):
        data["sentiment_counts"] = topic_data.get("sentiment_counts", {})
        data["platform_counts"] = topic_data.get("platform_counts", {})
        data["engagement_totals"] = topic_data.get("engagement_totals", {})

    return data


def render_from_template_by_sections(template_html: str, topic_data: Dict[str, Any], custom_instructions: str = "") -> str:
    """Renders a template section-by-section so that large datasets are passed
    without truncation or LLM context window overflow."""
    soup = BeautifulSoup(template_html, "html.parser")
    sections, scripts = _extract_report_sections(soup)
    
    if len(sections) < 2:
        # Not enough distinct sections to batch; return empty to trigger fallback
        return ""

    print(f"[DynamicReportService] Reskinning template section-by-section ({len(sections)} sections, {len(scripts)} scripts)")

    # Reskin each section
    for idx, sec in enumerate(sections):
        sec_html = str(sec)
        sec_data = _filter_topic_data_for_section(sec_html, topic_data)
        try:
            new_sec_html = _call_section_reskin_llm(sec_html, sec_data, custom_instructions=custom_instructions)
            new_soup = BeautifulSoup(new_sec_html, "html.parser")
            first_child = next((c for c in new_soup.children if isinstance(c, Tag)), None)
            if first_child:
                sec.replace_with(first_child)
        except Exception as exc:
            print(f"[DynamicReportService] Warning: Failed to reskin section {idx+1}: {exc}")

    # Reskin chart scripts
    if scripts:
        chart_data = {
            "sentiment_counts": topic_data.get("sentiment_counts", {}),
            "platform_counts": topic_data.get("platform_counts", {}),
            "emotion_counts": topic_data.get("emotion_counts", {}),
            "timeline": topic_data.get("timeline", []),
            "hourly_counts": topic_data.get("hourly_counts", []),
            "weekday_counts": topic_data.get("weekday_counts", []),
        }
        for script_tag in scripts:
            try:
                new_script_html = _call_script_reskin_llm(str(script_tag), chart_data)
                new_script_soup = BeautifulSoup(new_script_html, "html.parser")
                first_script = next((c for c in new_script_soup.children if isinstance(c, Tag)), None)
                if first_script:
                    script_tag.replace_with(first_script)
            except Exception as exc:
                print(f"[DynamicReportService] Warning: Failed to reskin chart script: {exc}")

    # Update document title in <head>
    if soup.title and topic_data.get("topic_title"):
        soup.title.string = f"Intelligence Report - {topic_data['topic_title']}"

    result_html = str(soup)
    if _looks_like_html_document(result_html):
        return result_html
    return ""


def render_from_template(template_html: str, topic_data: Dict[str, Any], custom_instructions: str = "") -> str:
    """Renders a report template with real topic data.
    First attempts Section-by-Section Batching so full database information
    (posts, keywords, hashtags, timeline) is processed without truncation.
    Falls back to single-pass whole-document rewrite if sectioning is not applicable."""
    # Attempt section-by-section batching first
    try:
        sectioned_html = render_from_template_by_sections(template_html, topic_data, custom_instructions=custom_instructions)
        if sectioned_html and _looks_like_html_document(sectioned_html):
            print(f"[DynamicReportService] Section-by-section reskin succeeded ({len(sectioned_html)} chars)")
            return sectioned_html
    except Exception as exc:
        print(f"[DynamicReportService] Section-by-section reskin encountered exception: {exc} — trying fallback")

    # Fallback to whole-document rewrite
    last_error = None
    for cap in (15, 3, 1):
        try:
            raw = _call_template_llm(template_html, topic_data, custom_instructions, cap)
        except Exception as exc:
            last_error = TemplateRenderError(f"LLM call failed: {exc}")
            continue

        html = _extract_html(raw)
        if _looks_like_html_document(html):
            return html
        last_error = TemplateRenderError(
            "The model's response doesn't look like a complete HTML document. "
            + (
                f"This template is {len(template_html) // 1024}KB — reskinning has to regenerate "
                "the entire document, and templates over ~50KB fail this step much more often. "
                "Try a smaller/simpler template."
                if len(template_html) > _LARGE_TEMPLATE_BYTES
                else "Check the server log for the raw model response (see _call_template_llm)."
            )
        )

    raise last_error


# Only these origins are allowed to load when rendering an uploaded
# template's HTML — it may embed arbitrary <script>/<link> tags, and this is
# the only report path this session that executes JS in the render (every
# built-in component deliberately uses static CSS instead, see the
# CSS-charts-not-matplotlib note earlier in this file). Blocking everything
# else keeps that JS from doing anything beyond drawing charts: no SSRF to
# internal hosts, no arbitrary outbound requests.
_ALLOWED_TEMPLATE_NETWORK_HOSTS = (
    "cdn.tailwindcss.com",
    "cdnjs.cloudflare.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
)


def _template_route_handler(route):
    url = route.request.url
    if url.startswith("data:") or any(host in url for host in _ALLOWED_TEMPLATE_NETWORK_HOSTS):
        route.continue_()
    else:
        route.abort()


# Treat any standalone 6+ digit number not found in topic_data as high-confidence fabrication and redact it directly; leave shorter numbers for the LLM audit to avoid false positives.
_HIGH_CONFIDENCE_NUMBER_DIGITS = 6

_UNVERIFIED_MARKER = '<span class="unverified">Not available</span>'


def _redact_tokens(html: str, tokens: List[str]) -> Tuple[str, int]:
    """Word-boundary-safe replace of unverified tokens with the unverified marker.
    Restricted to text nodes, skipping style/script and protected post/evidence nodes."""
    if not tokens:
        return html, 0

    soup = BeautifulSoup(html, "html.parser")
    protected_classes = {
        "post-card", "feed-card", "post-text", "post-meta", "post-snippet",
        "post-evidence", "evidence-card", "evidence-section", "raw-quote",
    }
    
    total = 0
    filtered_tokens = [t for t in tokens if len(t.strip()) > 1 and t not in _NAMED_PHRASE_STOPLIST]
    
    for token in filtered_tokens:
        pattern = re.compile(rf"\b{re.escape(token)}\b")
        token_count = 0
        for text_node in list(soup.find_all(string=True)):
            if not text_node.parent:
                continue
            if any(p.get("class") and any(c in protected_classes for c in p.get("class", [])) for p in text_node.parents if isinstance(p, Tag)):
                continue
            if text_node.parent.name in ("script", "style", "title", "code"):
                continue
            if pattern.search(text_node):
                new_text, n = pattern.subn(_UNVERIFIED_MARKER, text_node)
                if n > 0:
                    token_count += n
                    new_tag = BeautifulSoup(new_text, "html.parser")
                    text_node.replace_with(new_tag)
        total += token_count
        if token_count:
            print(f"[DynamicReportService] Redacted unverified value: {token!r} ({token_count} occurrence(s))")

    return str(soup), total


def _redact_high_confidence_fabrications(html: str, topic_data: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Programmatic pre-filter pass: finds candidate facts in `html` that
    don't trace back to `topic_data`, redacts the high-confidence ones in
    place, and returns (patched_html, lower_confidence_candidates) so the
    latter can be handed to the LLM audit step. No LLM call here — see
    extract_numeric_and_named_tokens/flatten_topic_data_values."""
    candidate_tokens = extract_numeric_and_named_tokens(html)
    real_values = flatten_topic_data_values(topic_data)

    unverified = [t for t in candidate_tokens if t not in real_values]
    if not unverified:
        return html, []

    high_confidence = [
        t for t in unverified
        if t.replace(".", "", 1).isdigit() and len(t) >= _HIGH_CONFIDENCE_NUMBER_DIGITS
    ]
    remaining_candidates = [t for t in unverified if t not in high_confidence]

    patched, _ = _redact_tokens(html, high_confidence)
    return patched, remaining_candidates


_AUDIT_CONTEXT_CHARS = 80  # small on purpose — see build_content_audit_prompt


def _context_snippet(html: str, token: str, radius: int = _AUDIT_CONTEXT_CHARS) -> str:
    """Grabs a short window of HTML around the first occurrence of `token`.
    The audit prompt sends THIS, not the full rewritten document — a
    reskinned template can be 1500-3000+ lines, and resending all of it
    just to classify a handful of leftover candidates would make the audit
    call as expensive as the original reskin. A short snippet is enough
    context for a verdict."""
    idx = html.find(token)
    if idx == -1:
        return token
    start = max(0, idx - radius)
    end = min(len(html), idx + len(token) + radius)
    return html[start:end].replace("\n", " ").strip()


def build_content_audit_prompt(rewritten_html: str, topic_data: Dict[str, Any], candidate_tokens: List[str]) -> str:
    """Builds the audit prompt for candidates the programmatic pre-filter
    couldn't resolve with confidence on its own. No LLM call in this
    function — see _call_content_audit_llm for that, per this file's
    established convention (mirrors _call_template_llm's separation)."""
    snippets = [
        {"value": token, "context": _context_snippet(rewritten_html, token)}
        for token in candidate_tokens
    ]
    # Deliberately NOT using _trim_topic_data_for_llm() here. That helper
    # exists because render_from_template's reskin call has to echo back an
    # entire 1500-3000+ line template, so its prompt genuinely risks
    # overloading the model — trimming keywords/hashtags/mentions/top_posts
    # to a small cap is the fix for THAT problem. This audit prompt has no
    # such problem: it's a handful of short candidate snippets plus the real
    # data, with no document to echo. Reusing that same cap=15 trim here
    # was a latent bug — any real value sitting outside the first 15 of a
    # field (topics commonly have hundreds of keywords/hashtags/mentions)
    # was invisible to the audit, so a genuine number or name could be
    # misclassified "unverified" and wrongly redacted from a correct report.
    real_data_json = json.dumps(topic_data, ensure_ascii=False, default=str)

    return f"""You are auditing a reskinned HTML intelligence report for fabricated content.

Each CANDIDATE below is a number, percentage, or name-like phrase found in the report, with a short snippet of surrounding HTML for context. Decide whether each is actually supported by REAL_DATA_JSON, the only verified source of truth for facts specific to THIS topic.

REAL_DATA_JSON:
{real_data_json}

CANDIDATES:
{json.dumps(snippets, ensure_ascii=False, indent=2)}

For EACH candidate, decide:
- "verified" — genuinely derivable from REAL_DATA_JSON (exact match, an obvious rewording/rounding, or a real value's own label/unit).
- "structural" — NOT a claim about this topic at all: standing page chrome such as a navigation link, section/column header, a fixed category, department, or organization name, a filter/badge label, or other boilerplate that would appear identically on this same report template no matter which topic it was generated for. This is real, legitimate content — it simply isn't the kind of per-topic fact that REAL_DATA_JSON would ever contain, so its absence there is expected and NOT a sign of fabrication. Ask yourself: "would this exact text plausibly appear unchanged if this report were generated for a completely different topic?" — if yes, this is structural.
- "unverified" — presented as if it were a specific fact ABOUT THIS TOPIC (a count, a name, a percentage, a claim tied to this particular incident) but does not appear in REAL_DATA_JSON in any form; looks fabricated or left over from the template's original sample content for a different topic.

Respond ONLY with a JSON array, one entry per candidate:
[{{"value": "<candidate value exactly as given>", "verdict": "verified" | "structural" | "unverified"}}]
No commentary, no markdown fences — JSON only."""


def parse_content_audit_response(raw: str) -> List[Dict[str, str]]:
    """Parses the audit response into [{"value","verdict"}, ...]. Tolerant
    of markdown fences (same fence-stripping shape as llm_decide_components).
    Malformed entries are DROPPED, not guessed at — the caller in
    compile_pdf_report_from_template treats anything missing from this list
    as unverified (fail closed), so dropping here is always the safe
    direction, never the permissive one. "structural" is accepted here as a
    first-class verdict alongside "verified"/"unverified" — dropping it as
    malformed would silently fail it closed into "unverified" too, defeating
    the whole point of giving the model a way to say "this is real static
    page chrome, not a per-topic claim" instead of forcing a binary
    verified-against-REAL_DATA_JSON judgment on text that was never a
    factual claim to begin with."""
    text = raw.strip()
    if "```" in text:
        for part in text.split("```"):
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("[") and cleaned.endswith("]"):
                text = cleaned
                break

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []

    results = []
    if isinstance(parsed, list):
        for entry in parsed:
            if isinstance(entry, dict) and "value" in entry and entry.get("verdict") in ("verified", "structural", "unverified"):
                results.append({"value": str(entry["value"]), "verdict": entry["verdict"]})
    return results


def _call_content_audit_llm(prompt: str) -> str:
    """Sync, direct vLLM call — same calling convention as
    _call_template_llm (this file's established exception to the 'no LLM
    calls in service modules' rule, made because compile_pdf_report_from_
    template always runs inside a worker thread with no event loop, so
    ollamaagent2.py's async call_llm() isn't reachable here). Kept as its
    own function rather than reusing _call_template_llm because this is a
    much smaller completion — a short verdict list, not a full document."""
    response = requests.post(
        f"{VLLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
        json={
            "model": VLLM_MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 2000,
        },
        timeout=60,
    )
    response.raise_for_status()
    body = response.json()
    return body["choices"][0]["message"]["content"] or ""


def _call_layout_llm(prompt: str) -> str:
    """Same sync vLLM call shape as _call_content_audit_llm — used only for slot-mapping, small prompt."""
    response = requests.post(
        f"{VLLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
        json={"model": VLLM_MODEL_NAME, "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 1500},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"] or ""


# only ever invoked for "clean" slots (real table, real columns, real join path,
# no placeholder language — see annotate_slot_status in
# template_reskin_engine.py) that come back with zero matching rows for this
# specific topic. Every other slot status gets the deterministic fallback,
# never this.
_AVAILABILITY_PROMPT_TEMPLATE = """You are writing ONE sentence for a police intelligence report, explaining why a
specific metric has no value for this topic. You are NOT analyzing data — you are
only rephrasing a fact you are given.

GIVEN:
- What this metric measures (verbatim, from the template): "{meaning_text}"
- Fact: a real database lookup for this topic returned zero matching rows in
  {table_name}.

RULES — violating any of these means your output is discarded and the deterministic
fallback string is used instead:
1. Do not state or imply any number, count, percentage, name, district, or date.
2. Do not guess or invent a reason the data is missing (do not say "likely because…",
   "possibly due to…", or speculate about the incident itself).
3. Do not claim the event described did or did not happen — only that this metric
   has no recorded value.
4. One sentence only. No more than 30 words.
5. Do not use the words "error", "failed", "bug", or "unavailable" more than once.
6. If you cannot satisfy all of the above, output exactly: FALLBACK

OUTPUT: the sentence only, nothing else."""

_AVAILABILITY_BANNED_WORDS = ("error", "failed", "bug", "unavailable")
_AVAILABILITY_MAX_WORDS = 30


def _call_availability_phrasing_llm(meaning_text: str, chips: List[str]) -> Optional[str]:
    """Tier-2 'why no data' phrasing call (see template_reskin_engine.fill_
    template's clean-status branch). Returns None — never a partially-broken
    sentence — whenever the call fails, the model opts out with FALLBACK, or
    the RULES above are violated; the caller then uses the deterministic
    fallback string instead. Same sync vLLM call shape as _call_layout_llm,
    kept separate because this one has its own prompt and its own
    self-consistency checks."""
    if not meaning_text:
        return None
    table_name = chips[0].split(".")[0] if chips else "the relevant table"
    prompt = _AVAILABILITY_PROMPT_TEMPLATE.format(
        meaning_text=meaning_text.strip(), table_name=table_name
    )
    try:
        response = requests.post(
            f"{VLLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
            json={
                "model": VLLM_MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 150,
            },
            timeout=30,
        )
        response.raise_for_status()
        text = (response.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:
        print(f"[DynamicReportService] Availability phrasing call failed: {exc} — falling back")
        return None

    if not text or text == "FALLBACK":
        return None
    if len(text.split()) > _AVAILABILITY_MAX_WORDS:
        return None
    lowered = text.lower()
    if any(lowered.count(word) > 1 for word in _AVAILABILITY_BANNED_WORDS):
        return None
    return text


def build_and_cache_layout(template_dir: Path, template_html: str) -> Dict[str, Any]:
    """Upload-time only — builds layout.json once so every later generation skips slot detection entirely."""
    layout = template_reskin_engine.build_slot_layout(template_html, call_llm_fn=_call_layout_llm)
    (template_dir / "layout.json").write_text(json.dumps(layout), encoding="utf-8")
    return layout


# ── Ad-hoc AI-generated report templates  ──────────────
# Sidecar HTML -> existing slot-mapping pipeline (same build_slot_layout()
# the uploaded-template path already uses) -> unconfirmed, preview-only
# template. No DB call, no Playwright, no PDF — real data joins later via
# fill_template() in the Phase 4 confirm step, against the layout.json
# written here.
_PENDING_TEMPLATES_DIR = TEMPLATES_DIR / "_pending"
_PENDING_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

# No existing "confidently mapped enough" signal to reuse for this (see
# plan.md audit note) — annotate_slot_status is about DB-schema
# verification, not mapping coverage, so this threshold is new.
_MIN_MAPPED_SLOT_RATIO = 0.5


def build_adhoc_report_preview(brief: Dict[str, Any]) -> Dict[str, Any]:
    """Phase 2 exit criteria: given a prompt-derived brief, returns HTML +
    a layout.json with slot mappings. If the screenshot-to-code sidecar is offline or
    unreachable, seamlessly falls back to the best-matching curated template layout
    so the user always gets an interactive preview card."""
    design_notes = (brief or {}).get("design_notes", "")
    content_focus = (brief or {}).get("content_focus") or []

    html = None
    try:
        html = adhoc_generation_service.generate_layout_html(design_notes, content_focus)
        if not _looks_like_html_document(html):
            html = None
    except Exception as sidecar_err:
        print(f"[DynamicReportService] Sidecar generation offline ({sidecar_err}). Using curated template fallback.")
        html = None

    if not html:
        _ensure_curated_templates()
        selected_tpl = match_design_brief_to_template(design_notes)
        tpl_path = TEMPLATES_DIR / selected_tpl / "template.html"
        if tpl_path.exists():
            html = tpl_path.read_text(encoding="utf-8")
        else:
            html = "<!DOCTYPE html><html><head><meta charset='UTF-8'><title>Intelligence Report</title></head><body><div class='page'><h1>Trending Intelligence Report</h1><p>Executive Dashboard</p></div></body></html>"

        return {
            "template_id": selected_tpl,
            "preview_html": html,
            "layout_status": "ready",
        }

    template_id = f"tpl_{uuid.uuid4().hex[:10]}"
    template_dir = _PENDING_TEMPLATES_DIR / template_id
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / "template.html").write_text(html, encoding="utf-8")

    layout_status = "ready"
    layout: Optional[Dict[str, Any]] = None
    try:
        layout = template_reskin_engine.build_slot_layout(html, call_llm_fn=_call_layout_llm)
        non_chart_slots = [s for s in layout["slots"] if s["slot_type"] != "chart_series"]
        mapped = [s for s in non_chart_slots if s.get("maps_to")]
        if not non_chart_slots or (len(mapped) / len(non_chart_slots)) < _MIN_MAPPED_SLOT_RATIO:
            layout_status = "fallback_whole_document"
    except Exception as exc:
        # Same trigger as the upload path (server.py's
        # /api/report-templates/upload): a layout-build exception falls
        # back to the whole-document reskin rather than failing outright.
        layout_status = "fallback_whole_document"
        layout = None
        print(f"[DynamicReportService] Slot layout build failed for adhoc {template_id}: {exc}")

    if layout is not None:
        (template_dir / "layout.json").write_text(json.dumps(layout), encoding="utf-8")

    meta = {
        "source": "adhoc_generated",
        "design_notes": design_notes,
        "content_focus": content_focus,
        "created_at": datetime.now().isoformat(),
        "layout_status": layout_status,
    }
    (template_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    return {
        "template_id": template_id,
        "preview_html": html,
        "layout_status": layout_status,
    }


def confirm_adhoc_report(
    template_id: str,
    scope: Optional[Dict[str, Any]] = None,
    topic_id: Optional[str] = None,
    date_range: Optional[Dict[str, str]] = None,
    custom_instructions: str = "",
) -> Dict[str, Any]:
    """Promotes pending template from _pending/ to permanent TEMPLATES_DIR,
    fetches real topic or trending data from MySQL, reskins the whole
    document via the LLM (same approach as Method 2's Custom Template —
    see render_from_template), runs fabrication audit, and compiles final
    PDF via Playwright."""
    report_id = f"rpt_{uuid.uuid4().hex[:10]}"
    if not re.fullmatch(r"^tpl_[0-9a-f]{10}$", template_id):
        raise TemplateRenderError(f"Invalid template_id format: '{template_id}'")

    pending_dir = _PENDING_TEMPLATES_DIR / template_id
    permanent_dir = TEMPLATES_DIR / template_id

    if pending_dir.exists():
        if not permanent_dir.exists():
            try:
                shutil.copytree(pending_dir, permanent_dir)
            except Exception as e:
                print(f"[DynamicReportService] Warning copying pending template {template_id}: {e}")
        template_dir = permanent_dir if permanent_dir.exists() else pending_dir
    elif permanent_dir.exists():
        template_dir = permanent_dir
    else:
        raise TemplateRenderError(f"Template '{template_id}' not found in pending or permanent templates.")

    template_html_path = template_dir / "template.html"
    if not template_html_path.exists():
        raise TemplateRenderError(f"Template HTML file missing for '{template_id}'.")
    template_html = template_html_path.read_text(encoding="utf-8")

    # layout.json (if cached from build_adhoc_report_preview()) is no longer
    # read here — see the whole-document-reskin note below. It's left on
    # disk untouched since build_adhoc_report_preview() still writes it for
    # the preview UI's layout_status display.

    # Determine topic data to ground against
    report_type = "topic"
    resolved_topic_id = topic_id
    if not resolved_topic_id and scope and scope.get("report_type") == "topic" and scope.get("topics"):
        resolved_topic_id = scope["topics"][0].get("topic_id")

    if resolved_topic_id:
        topic_data = fetch_topic_report_data(resolved_topic_id, REPORTS_DIR / report_id / "assets")
        if topic_data.get("total_posts", 0) == 0 and not topic_data.get("top_posts"):
            raise TemplateRenderError(
                "This topic has no verified data to generate a report with "
                "(total_posts is 0 and there are no top posts)."
            )
        report_type = "topic"
    else:
        # Trending data path
        report_type = "trending"
        dr = date_range or (scope.get("date_range") if scope else {}) or {}
        date_from = dr.get("from") or datetime.now().strftime("%Y-%m-%d")
        date_to = dr.get("to") or date_from
        topic_data = fetch_trending_report_data(date_from, date_to, REPORTS_DIR / report_id / "assets")

    # Whole-document LLM reskin — now follows the exact same approach
    # Method 2 (Custom Template) uses via render_from_template(), instead
    # of mechanical slot-tagging (template_reskin_engine.fill_template()).
    #
    # Why: fill_template() only ever touches a node _looks_like_stat()
    # recognized as a slot in the first place — a strict "the whole tag is
    # just a number" match. Any sidecar-generated combined label+value node
    # (e.g. "Complaints: 68%", a decorative "❤️ 42" engagement count) was
    # invisible to that heuristic, so the original AI-invented placeholder
    # number survived untouched into every real report — confirmed on
    # rpt_67ab0f5840. A one-pass whole-document LLM rewrite has no such gap:
    # the model sees and rewrites everything, guided by REAL_DATA_JSON, the
    # same way it already does reliably for uploaded custom templates. The
    # cached layout.json from build_adhoc_report_preview() is still written
    # (and layout_status still shown in the preview UI) but no longer read
    # here — Method 2's own compile_pdf_report_from_template() is untouched
    # and still uses its cached layout, per plan.md's hard constraint.
    #
    # custom_instructions carries an adhoc-only addition below asking the
    # model to neutralize (reword, don't fabricate-then-redact) any section
    # with no real backing field at all — kept out of the shared
    # _TEMPLATE_SYSTEM_PROMPT so Method 2's prompt stays untouched.
    _neutralize_note = (
        "If a section or metric has NO corresponding field in REAL_DATA_JSON "
        "at all (a genuine data-source gap, e.g. this platform does not track "
        "officer-level complaint/commendation counts) — do not leave the "
        "original sample number in place, and do not just drop a bare 'Not "
        "available' marker into what was a numeric visual like a percentage "
        "bar or chart. Instead, reword that section's copy neutrally so it "
        "reads naturally (e.g. a short note that this metric isn't tracked "
        "for this topic) and simplify the accompanying visual accordingly "
        "(e.g. remove a two-color bar fill rather than leave it showing "
        "fabricated proportions). The report should read clean and honest — "
        "never a stray 'Not available' badge sitting where a number used to be."
    )
    adhoc_instructions = (
        f"{custom_instructions}\n\n{_neutralize_note}" if custom_instructions else _neutralize_note
    )
    new_html = render_from_template(template_html, topic_data, custom_instructions=adhoc_instructions)
    new_html, unresolved_candidates = _redact_high_confidence_fabrications(new_html, topic_data)

    if unresolved_candidates:
        try:
            audit_prompt = build_content_audit_prompt(new_html, topic_data, unresolved_candidates)
            raw_audit = _call_content_audit_llm(audit_prompt)
            audit_results = parse_content_audit_response(raw_audit)
        except Exception as exc:
            print(f"[DynamicReportService] Content audit call failed for adhoc report: {exc} — failing closed")
            audit_results = []

        audited_values = {r["value"] for r in audit_results}
        confirmed_unverified = [r["value"] for r in audit_results if r["verdict"] == "unverified"]
        confirmed_unverified += [t for t in unresolved_candidates if t not in audited_values]

        if confirmed_unverified:
            new_html, n = _redact_tokens(new_html, confirmed_unverified)
            print(f"[DynamicReportService] LLM audit redacted {n} unverified occurrence(s) in adhoc report {template_id}.")

    # Append evidence section after audit to preserve raw quote text and media attachments
    new_html = _append_evidence_section(new_html, topic_data.get("top_posts", []))

    report_dir = REPORTS_DIR / report_id
    report_dir.mkdir(parents=True, exist_ok=True)
    pdf_output_path = report_dir / "report.pdf"

    box_break_css = """
    <style id="matrix-pdf-box-rules">
      @media print, screen {
        .card, .kpi-card, .chart-card, .mod-card, .table-card, .ladder, .lad-row,
        .cluster-card, .report-card, .module-blurb, .note, details.dl, .bar-row,
        table, tr, tbody, thead, .post-card, .tile, .tiles, .tag-cloud,
        .insight, .header, .mod-header, .scope-row, .disclaimer,
        .chart-wrap, .ring-grid, .cluster-grid, .report-grid {
          break-inside: avoid !important;
          page-break-inside: avoid !important;
        }
        h1, h2, h3, h4, .section-lbl, .sub {
          break-after: avoid !important;
          page-break-after: avoid !important;
        }
      }
    </style>
    """
    # Adhoc layouts come from the sidecar's own model output — even with
    # the print-safety instructions in adhoc_generation_service.py's system
    # prompt, a generated layout can still lean on viewport-relative sizing
    # or a side-by-side split that only balances when every section has
    # plenty of content. Real topic_data is frequently much sparser than
    # the placeholder data the layout was designed against (a topic can
    # have as little as a single real post), so this normalizes the page
    # to a fixed print width and strips viewport-relative sizing as a
    # defensive second layer, independent of what the model actually did.
    print_normalize_css = """
    <style id="matrix-pdf-print-normalize">
      @media print, screen {
        html, body {
          width: 800px !important;
          max-width: 800px !important;
          height: auto !important;
          min-height: 0 !important;
        }
        [style*="100vh"], [style*="100vw"],
        [class*="min-h-screen"], [class*="h-screen"], [class*="w-screen"] {
          min-height: 0 !important;
          height: auto !important;
          width: auto !important;
          max-width: 100% !important;
        }
      }
    </style>
    """
    if "</head>" in new_html:
        new_html = new_html.replace("</head>", f"{box_break_css}{print_normalize_css}</head>")
    else:
        new_html = f"{box_break_css}{print_normalize_css}{new_html}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.emulate_media(media="screen")
            page.route("**/*", _template_route_handler)
            page.set_content(new_html, wait_until="load", timeout=15000)
            page.wait_for_load_state("networkidle", timeout=15000)
            page.pdf(path=str(pdf_output_path), print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()

    print(f"[DynamicReportService] Successfully compiled adhoc PDF at: {pdf_output_path}")
    return {
        "report_id": report_id,
        "pdf_path": str(pdf_output_path),
        "download_url": f"/api/reports/download/{report_id}",
        "template_id": template_id,
        "report_type": report_type,
    }


def compile_pdf_report_from_template(
    report_id: str,
    template_html: str,
    topic_id: str,
    custom_instructions: str = "",
    layout: Optional[Dict[str, Any]] = None,
) -> str:
    """Fetches real data for topic_id, has the LLM reskin the uploaded
    template with it, then renders the result to PDF via Playwright with
    network access locked down to a small CDN allowlist (see
    _ALLOWED_TEMPLATE_NETWORK_HOSTS) and a hard load timeout, since — unlike
    every other report path — this one executes arbitrary uploaded JS."""
    topic_data = fetch_topic_report_data(topic_id, REPORTS_DIR / report_id / "assets")

    # Reject essentially empty datasets upfront with a clear, actionable error instead of relying on the LLM to return “not available” consistently.
    if topic_data.get("total_posts", 0) == 0 and not topic_data.get("top_posts"):
        raise TemplateRenderError(
            "This topic has no verified data to reskin a template with "
            "(total_posts is 0 and there are no top posts). Choose a topic "
            "with real data, or use a built-in report instead."
        )

    if layout:
        # Slot-fill path — every value is already real or already "Not available", audit pass not needed.
        new_html = template_reskin_engine.fill_template(
            layout, topic_data, call_llm_fn=_call_layout_llm,
            availability_llm_fn=_call_availability_phrasing_llm,
        )
        unresolved_candidates = []
    else:
        new_html = render_from_template(template_html, topic_data, custom_instructions)
        # Pre-filter removes high-confidence fabrications before Playwright; the rest goes to the LLM audit below.
        new_html, unresolved_candidates = _redact_high_confidence_fabrications(new_html, topic_data)

    if unresolved_candidates:
        try:
            audit_prompt = build_content_audit_prompt(new_html, topic_data, unresolved_candidates)
            raw_audit = _call_content_audit_llm(audit_prompt)
            audit_results = parse_content_audit_response(raw_audit)
        except Exception as exc:
            # Fail closed: an audit-call failure means we treat every pending
            # candidate as unverified, not as "couldn't check, ship it anyway."
            print(f"[DynamicReportService] Content audit call failed for report {report_id}: {exc} — failing closed")
            audit_results = []

        audited_values = {r["value"] for r in audit_results}
        confirmed_unverified = [r["value"] for r in audit_results if r["verdict"] == "unverified"]
        confirmed_unverified += [t for t in unresolved_candidates if t not in audited_values]

        if confirmed_unverified:
            new_html, n = _redact_tokens(new_html, confirmed_unverified)
            print(
                f"[DynamicReportService] LLM audit resolved {len(confirmed_unverified)} "
                f"unverified value(s) in report {report_id}; redacted {n} occurrence(s)"
            )

    # Append evidence section after audit to preserve raw quote text and media attachments
    new_html = _append_evidence_section(new_html, topic_data.get("top_posts", []))

    report_dir = REPORTS_DIR / report_id
    report_dir.mkdir(parents=True, exist_ok=True)
    pdf_output_path = report_dir / "report.pdf"

    # Ensure all report boxes, cards, and tables avoid breaking across page boundaries
    box_break_css = """
    <style id="matrix-pdf-box-rules">
      @media print, screen {
        .card, .kpi-card, .chart-card, .mod-card, .table-card, .ladder, .lad-row,
        .cluster-card, .report-card, .module-blurb, .note, details.dl, .bar-row,
        table, tr, tbody, thead, .post-card, .tile, .tiles, .tag-cloud,
        .insight, .header, .mod-header, .scope-row, .disclaimer,
        .chart-wrap, .ring-grid, .cluster-grid, .report-grid {
          break-inside: avoid !important;
          page-break-inside: avoid !important;
        }
        h1, h2, h3, h4, .section-lbl, .sub {
          break-after: avoid !important;
          page-break-after: avoid !important;
        }
      }
    </style>
    """
    if "</head>" in new_html:
        new_html = new_html.replace("</head>", f"{box_break_css}</head>")
    else:
        new_html = f"{box_break_css}{new_html}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.emulate_media(media="screen")
            page.route("**/*", _template_route_handler)
            page.set_content(new_html, wait_until="load", timeout=15000)
            page.wait_for_load_state("networkidle", timeout=15000)
            page.pdf(path=str(pdf_output_path), print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()

    print(f"[DynamicReportService] Successfully compiled template-based PDF at: {pdf_output_path}")
    return str(pdf_output_path)


# =============================================================================
# FREE-FORM PROMPT-DRIVEN REPORTS 
#
# the Topic/Date Resolver  built and tested standalone before any LLM generation exists.
# Nothing above this marker is modified for this feature — paths 1-3
# (CORE_MODULES, build_report, render_from_template, etc.) are untouched.
# =============================================================================

# Matches ID-like tokens (6–64 chars, including a digit) to trigger a DB lookup, avoiding unnecessary queries for normal prose.
_TOPIC_ID_TOKEN_RE = re.compile(r"\b(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{6,64}\b")

# Reuses the existing quoted-title pattern from ollamaagent2.py to detect titles in straight quotes (4–100 characters).
_QUOTED_TITLE_RE = re.compile(r"['\"]([^'\"]{4,100})['\"]")

# Classifies unresolved free-form report requests as aggregate/date-window reports (e.g., trending) versus requests needing clarification, without triggering report detection itself.
_TRENDING_HINT_RE = re.compile(
    r"trending|viral|overall|all topics|across (all )?districts|"
    r"today'?s? posts|this week'?s? posts|daily digest|"
    r"ट्रेंडिंग|वायरल",
    re.IGNORECASE,
)


def _validate_topic_id(topic_id: str) -> Optional[str]:
    # Validates an explicit topic-ID candidate against the DB, returning the stored ID on success or None on miss/error without raising exceptions.
    topic_id = (topic_id or "").strip()
    if not topic_id:
        return None
    try:
        rows = run_query(
            "SELECT unique_topic_id FROM topic WHERE unique_topic_id = %s LIMIT 1",
            (topic_id,),
        )
        if rows:
            return str(rows[0]["unique_topic_id"]).strip()
    except Exception as e:
        print(f"[DynamicReportService] _validate_topic_id error for '{topic_id}': {e}")
    return None


def _topic_title_for_id(topic_id: str) -> str:
    # Best-effort topic-title lookup that returns the title if found, or an empty string on failure so report generation can safely use its default fallback.
    try:
        rows = run_query(
            "SELECT topic_title FROM topic WHERE unique_topic_id = %s LIMIT 1",
            (topic_id,),
        )
        if rows:
            return str(rows[0]["topic_title"]).strip()
    except Exception as e:
        print(f"[DynamicReportService] _topic_title_for_id error for '{topic_id}': {e}")
    return ""


def resolve_report_scope(
    state_ctx: Dict[str, Any],
    prompt_text: str,
    lookup_topic_id_by_title_fn,
    resolve_date_range_fn,
) -> Dict[str, Any]:
    # Deterministically resolves report scope without an LLM:
# 1. Validates an explicit topic_id from the prompt.
# 2. Resolves an explicitly quoted/named topic title.
# 3. Reuses existing state for implicit references like "this topic".
# 4. Selects "trending" for aggregate/date-window requests with no topic.
# 5. Otherwise asks for clarification instead of guessing a topic.
# Uses synchronous DB lookups; LLM fallback is handled later by the caller.
    text = prompt_text or ""
    resolved_topic: Optional[Dict[str, str]] = None

    # --- Step 1: explicit topic-id-shaped token, DB-verified ---
    for candidate in _TOPIC_ID_TOKEN_RE.findall(text):
        verified_id = _validate_topic_id(candidate)
        if verified_id:
            resolved_topic = {"topic_id": verified_id, "topic_title": _topic_title_for_id(verified_id)}
            break

    # --- Step 2: explicit quoted/named topic title ---
    if not resolved_topic:
        m = _QUOTED_TITLE_RE.search(text)
        if m:
            candidate_title = m.group(1).strip()
            topic_id = lookup_topic_id_by_title_fn(candidate_title)
            if topic_id:
                resolved_topic = {"topic_id": topic_id, "topic_title": candidate_title}

    # --- Step 3: implicit reference, reused from picker-flow state ---
    if not resolved_topic:
        implicit_ref = str((state_ctx or {}).get("resolved_topic_reference") or "").strip()
        last_topic_ids = (state_ctx or {}).get("last_topic_ids") or []
        if implicit_ref:
            for t in last_topic_ids:
                if str(t.get("topic_id", "")).strip() == implicit_ref:
                    resolved_topic = {
                        "topic_id": implicit_ref,
                        "topic_title": str(t.get("title", "")).strip(),
                    }
                    break
            if not resolved_topic:
                # resolved_topic_reference was set by an earlier graph step
                # (a real unique_topic_id, not free text) even though it
                # isn't in this turn's last_topic_ids list — still worth a
                # direct verification rather than discarding it outright.
                verified_id = _validate_topic_id(implicit_ref)
                if verified_id:
                    resolved_topic = {"topic_id": verified_id, "topic_title": _topic_title_for_id(verified_id)}
        elif last_topic_ids:
            first = last_topic_ids[0]
            tid = str(first.get("topic_id", "")).strip()
            if tid:
                resolved_topic = {"topic_id": tid, "topic_title": str(first.get("title", "")).strip()}

    date_range = resolve_date_range_fn(text)

    if resolved_topic:
        return {
            "report_type": "topic",
            "topics": [resolved_topic],
            "date_range": date_range,
            "needs_clarification": False,
            "clarification_message": None,
        }

    # --- Step 4: nothing topic-specific resolved ---
    if _TRENDING_HINT_RE.search(text):
        return {
            "report_type": "trending",
            "topics": None,
            "date_range": date_range,
            "needs_clarification": False,
            "clarification_message": None,
        }

    return {
        "report_type": "topic",
        "topics": None,
        "date_range": None,
        "needs_clarification": True,
        "clarification_message": (
            "I couldn't tell which topic or incident this report should cover. "
            "Could you name it, or ask about a specific topic first and then say "
            "\"this topic\"/\"that incident\" — or ask for a trending/overall report instead?"
        ),
    }


# =============================================================================
# FREE-FORM REPORTS — Curated Catalog, Matcher, Brief Extractor, Builder
# =============================================================================

CURATED_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "tpl_executive_brief": {
        "template_id": "tpl_executive_brief",
        "display_name": "Executive Brief",
        "source_file": "template_1_executive_brief.html",
        "tags": ["executive", "brief", "formal", "leadership", "overview", "short", "summary", "clean", "minimal", "official", "quick", "officer"],
        "description": "Clean, light-themed executive summary with high-level KPI cards, overview, and sentiment breakdown.",
        "curated": True,
    },
    "tpl_cyber_dossier": {
        "template_id": "tpl_cyber_dossier",
        "display_name": "Cyber Threat Dossier",
        "source_file": "template_2_cyber_dossier.html",
        "tags": ["cyber", "dark", "security", "technical", "dossier", "threat", "investigation", "hacker", "serious", "digital", "attack"],
        "description": "Dark-themed, dense technical layout for cyber, digital threat, and security-flavored intelligence dossiers.",
        "curated": True,
    },
    "tpl_law_and_order": {
        "template_id": "tpl_law_and_order",
        "display_name": "Law & Order Assessment",
        "source_file": "template_3_law_and_order_assessment.html",
        "tags": ["law", "order", "police", "incident", "assessment", "district", "field", "crime", "patrol", "operational", "riot", "protest", "law and order"],
        "description": "Structured law and order situation assessment with district breakdown, incident metrics, and operational notes.",
        "curated": True,
    },
    "tpl_sentiment_analytics": {
        "template_id": "tpl_sentiment_analytics",
        "display_name": "Sentiment & Media Analytics",
        "source_file": "template_4_sentiment_media_analytics.html",
        "tags": ["sentiment", "media", "analytics", "social", "viral", "charts", "twitter", "facebook", "trends", "engagement", "detailed", "posts", "post", "platform"],
        "description": "Rich social media and sentiment analytics dashboard featuring time-series charts, platform share, top posts, and sentiment analysis.",
        "curated": True,
    },
}

_FREEFORM_DESIGN_TRIGGERS = [
    "look like", "looks like", "focus on", "focusing on", "focused on",
    "style", "format", "tone", "short", "long", "formal", "casual",
    "theme", "design", "layout", "aesthetic", "cyber", "dossier", "executive",
    "dark theme", "light theme", "briefing", "detailed", "compact", "concise",
    "sentiment and", "posts and", "keep it", "make it", "custom report",
    "customized", "structured as", "tailored", "one-page", "one page",
    "law and order", "media analytics"
]


def _is_freeform_report_request(text: str) -> bool:
    """True if text is a free-form report request containing descriptive/design language (§2.3).
    Separate from _is_report_request so the picker flow remains untouched."""
    text_lower = (text or "").lower()
    if not text_lower:
        return False
    
    # Check if general report intent exists
    has_report_word = any(
        w in text_lower for w in [
            "report", "repot", "reprot", "briefing", "dossier", "pdf",
            "रिपोर्ट", "पीडीएफ", "समरी", "विवरण"
        ]
    )
    if not has_report_word:
        return False

    # Check for descriptive/design indicators
    has_design_modifier = any(dt in text_lower for dt in _FREEFORM_DESIGN_TRIGGERS)
    return has_design_modifier


def _ensure_curated_templates() -> None:
    """Seeds the 4 curated library templates into TEMPLATES_DIR with layout.json and meta.json."""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    test_templates_dir = MATRIX_APP_DIR / "test_templates"

    for tpl_id, meta in CURATED_TEMPLATES.items():
        tpl_dir = TEMPLATES_DIR / tpl_id
        tpl_dir.mkdir(parents=True, exist_ok=True)
        tpl_html_path = tpl_dir / "template.html"
        tpl_layout_path = tpl_dir / "layout.json"
        tpl_meta_path = tpl_dir / "meta.json"

        # Copy/ensure template.html
        if not tpl_html_path.exists():
            src_file = test_templates_dir / meta["source_file"]
            if src_file.exists():
                tpl_html_path.write_text(src_file.read_text(encoding="utf-8"), encoding="utf-8")

        # Ensure meta.json
        if not tpl_meta_path.exists():
            tpl_meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

        # Ensure layout.json
        if not tpl_layout_path.exists() and tpl_html_path.exists():
            try:
                html_content = tpl_html_path.read_text(encoding="utf-8")
                def _safe_llm(p):
                    try:
                        return _call_layout_llm(p)
                    except Exception:
                        return "[]"
                layout = template_reskin_engine.build_slot_layout(html_content, call_llm_fn=_safe_llm)
                tpl_layout_path.write_text(json.dumps(layout, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                print(f"[DynamicReportService] Error building slot layout for {tpl_id}: {e}")


def match_design_brief_to_template(design_notes: str, call_llm_fn=None) -> str:
    """Two-stage curated template matcher (§2.6):
    1. Tag-overlap keyword scoring (no LLM).
    2. LLM tiebreak if stage 1 has no clear winner.
    Default neutral template: 'tpl_executive_brief'.
    """
    _ensure_curated_templates()
    notes_lower = (design_notes or "").lower()
    
    # Stage 1: Tag-overlap scoring
    scores: Dict[str, int] = {}
    tokens = set(re.findall(r"[a-z0-9_-]+", notes_lower))
    for tpl_id, meta in CURATED_TEMPLATES.items():
        score = 0
        for tag in meta.get("tags", []):
            tag_lower = tag.lower()
            if " " in tag_lower and tag_lower in notes_lower:
                score += 3
            elif tag_lower in tokens:
                score += 2
        scores[tpl_id] = score

    sorted_scores = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_id, best_score = sorted_scores[0]
    second_id, second_score = sorted_scores[1]

    # Clear winner threshold
    if best_score >= 3 and best_score > second_score:
        return best_id
    if best_score > 0 and (best_score - second_score >= 2):
        return best_id

    # Stage 2: LLM tiebreak
    llm_callable = call_llm_fn or _call_layout_llm
    if llm_callable and notes_lower.strip():
        catalog_desc = "\n".join([
            f"- {meta['template_id']}: {meta['display_name']} — {meta['description']} (Tags: {', '.join(meta['tags'])})"
            for meta in CURATED_TEMPLATES.values()
        ])
        prompt = f"""Choose the single best template ID for a report given the user's design notes.

TEMPLATE CATALOG:
{catalog_desc}

USER DESIGN NOTES:
{design_notes}

RULES:
- Respond with ONLY the template_id (e.g. tpl_executive_brief, tpl_cyber_dossier, tpl_law_and_order, tpl_sentiment_analytics).
- No explanation or extra text.
"""
        try:
            raw_out = llm_callable(prompt).strip()
            for tpl_id in CURATED_TEMPLATES:
                if tpl_id in raw_out:
                    return tpl_id
        except Exception as exc:
            print(f"[DynamicReportService] LLM template matcher error: {exc}")

    # Neutral fallback default
    return "tpl_executive_brief"


def _extract_report_brief(
    prompt_text: str,
    scope: Optional[Dict[str, Any]] = None,
    call_llm_fn=None,
) -> Dict[str, Any]:
    """Extracts content_focus and design_notes from the free-form prompt (§2.5)."""
    text = prompt_text or ""
    llm_callable = call_llm_fn or _call_layout_llm
    
    if llm_callable:
        prompt = f"""Extract the content focus and design/style preferences from this report request.

USER PROMPT:
{text}

OUTPUT FORMAT (JSON only):
{{
  "content_focus": ["sentiment", "top posts", ...],
  "design_notes": "tone, length, theme, or style constraints"
}}
"""
        try:
            raw_json = llm_callable(prompt).strip()
            if "```json" in raw_json:
                raw_json = raw_json.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_json:
                raw_json = raw_json.split("```")[1].split("```")[0].strip()
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict) and "design_notes" in parsed:
                return {
                    "content_focus": parsed.get("content_focus") or [],
                    "design_notes": str(parsed.get("design_notes", "")).strip(),
                }
        except Exception as e:
            print(f"[DynamicReportService] _extract_report_brief LLM error: {e}")

    # Fallback deterministic brief extraction
    return {
        "content_focus": ["sentiment", "top_posts", "overview"],
        "design_notes": text,
    }


def build_freeform_report(
    scope: Dict[str, Any],
    brief: Dict[str, Any],
    call_llm_fn=None,
) -> Dict[str, Any]:
    """Free-form prompt-driven report builder (Phase 3).
    Orchestrates template matching, data fetching, slot filling, audit, and Playwright PDF compilation.
    """
    _ensure_curated_templates()
    report_id = f"rpt_{uuid.uuid4().hex[:10]}"

    # 1. Match template
    design_notes = (brief or {}).get("design_notes", "")
    template_id = match_design_brief_to_template(design_notes, call_llm_fn=call_llm_fn)
    
    # 2. Fetch grounded DB data
    report_type = (scope or {}).get("report_type", "topic")
    if report_type == "trending":
        date_range = (scope or {}).get("date_range") or {}
        date_from = date_range.get("from") or datetime.now().strftime("%Y-%m-%d")
        date_to = date_range.get("to") or date_from
        topic_data = fetch_trending_report_data(date_from, date_to, REPORTS_DIR / report_id / "assets")
    else:
        topics = (scope or {}).get("topics") or []
        if not topics:
            raise TemplateRenderError("No topic provided for topic report.")
        topic_id = topics[0].get("topic_id")
        topic_data = fetch_topic_report_data(topic_id, REPORTS_DIR / report_id / "assets")
        if topic_data.get("total_posts", 0) == 0 and not topic_data.get("top_posts"):
            raise TemplateRenderError(
                "This topic has no verified data to generate a report with "
                "(total_posts is 0 and there are no top posts)."
            )

    # 3. Load template & layout
    template_dir = TEMPLATES_DIR / template_id
    template_path = template_dir / "template.html"
    layout_path = template_dir / "layout.json"

    if not template_path.exists():
        raise TemplateRenderError(f"Matched template '{template_id}' not found.")

    template_html = template_path.read_text(encoding="utf-8")
    layout = json.loads(layout_path.read_text(encoding="utf-8")) if layout_path.exists() else None

    # 4. Fill template & audit
    if layout:
        new_html = template_reskin_engine.fill_template(
            layout, topic_data, call_llm_fn=_call_layout_llm,
            availability_llm_fn=_call_availability_phrasing_llm,
        )
        unresolved_candidates = []
    else:
        new_html = render_from_template(template_html, topic_data, custom_instructions=design_notes)
        new_html, unresolved_candidates = _redact_high_confidence_fabrications(new_html, topic_data)

    if unresolved_candidates:
        try:
            audit_prompt = build_content_audit_prompt(new_html, topic_data, unresolved_candidates)
            raw_audit = _call_content_audit_llm(audit_prompt)
            audit_results = parse_content_audit_response(raw_audit)
        except Exception as exc:
            print(f"[DynamicReportService] Content audit call failed: {exc} — failing closed")
            audit_results = []

        audited_values = {r["value"] for r in audit_results}
        confirmed_unverified = [r["value"] for r in audit_results if r["verdict"] == "unverified"]
        confirmed_unverified += [t for t in unresolved_candidates if t not in audited_values]

        if confirmed_unverified:
            new_html, n = _redact_tokens(new_html, confirmed_unverified)
            print(f"[DynamicReportService] Redacted {n} unverified token(s) in free-form report.")

    # Append evidence section after audit to preserve raw quote text and media attachments
    new_html = _append_evidence_section(new_html, topic_data.get("top_posts", []))

    # 5. Render PDF via Playwright
    report_dir = REPORTS_DIR / report_id
    report_dir.mkdir(parents=True, exist_ok=True)
    pdf_output_path = report_dir / "report.pdf"

    box_break_css = """
    <style id="matrix-pdf-box-rules">
      @media print, screen {
        .card, .kpi-card, .chart-card, .mod-card, .table-card, .ladder, .lad-row,
        .cluster-card, .report-card, .module-blurb, .note, details.dl, .bar-row,
        table, tr, tbody, thead, .post-card, .tile, .tiles, .tag-cloud,
        .insight, .header, .mod-header, .scope-row, .disclaimer,
        .chart-wrap, .ring-grid, .cluster-grid, .report-grid {
          break-inside: avoid !important;
          page-break-inside: avoid !important;
        }
        h1, h2, h3, h4, .section-lbl, .sub {
          break-after: avoid !important;
          page-break-after: avoid !important;
        }
      }
    </style>
    """
    if "</head>" in new_html:
        new_html = new_html.replace("</head>", f"{box_break_css}</head>")
    else:
        new_html = f"{box_break_css}{new_html}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.emulate_media(media="screen")
            page.route("**/*", _template_route_handler)
            page.set_content(new_html, wait_until="load", timeout=15000)
            page.wait_for_load_state("networkidle", timeout=15000)
            page.pdf(path=str(pdf_output_path), print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()

    print(f"[DynamicReportService] Free-form report compiled: {pdf_output_path} (template={template_id})")
    return {
        "report_id": report_id,
        "pdf_path": str(pdf_output_path),
        "report_type": report_type,
        "template_id": template_id,
        "download_url": f"/api/reports/download/{report_id}",
    }