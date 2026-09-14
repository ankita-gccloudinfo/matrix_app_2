"""
mcp_services.py
================
External "MCP" services layer for the Matrix intelligence agent.

This module owns everything related to the system's external API
endpoints declared in external_endpoints.json — the tools the agent's
`check_and_run_endpoint_routes` node can discover and call ("MCP tools"):

  - loading / holding the endpoint registry and the authenticated
    Matrix HTTP session
  - Stage-1 candidate gathering + Stage-2 relevancy ranking (prompt
    building and response parsing)
  - path-param substitution and payload key/type validation
  - firing the actual HTTP calls (read + write)
  - shaping raw responses into a summarizable form (record aggregation,
    payload trimming, envelope unwrapping)
  - building the confirmation / multi-selection cards shown to the user

Design rule — NO LLM CALLS LIVE HERE. Every place the original logic
needed a model call (candidate gathering, relevancy ranking, final
answer generation), this module exposes a `build_..._prompt(...)` /
`parse_..._response(...)` pair instead of calling anything itself. The
caller (ollamaagent2.py, which owns `call_llm`) does the actual model
invocation and hands the raw text back in for parsing. That keeps every
LLM call in one place and keeps this module fully testable without a
model or network.
"""

import os
import re
import json
import logging
import requests
import asyncio
from urllib.parse import urlparse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# =========================
# CONFIG / ENDPOINT REGISTRY
# =========================

EXTERNAL_ENDPOINTS_FILE = os.environ.get("EXTERNAL_ENDPOINTS_FILE", "external_endpoints.json")
ENDPOINT_ROUTE_BATCH_SIZE = int(os.environ.get("ENDPOINT_ROUTE_BATCH_SIZE", "30"))
MATRIX_API_BASE_URL = os.environ.get("MATRIX_API_BASE_URL", "").rstrip("/")
MATRIX_API_AUTH_TOKEN = os.environ.get("MATRIX_API_AUTH_TOKEN", "")

# Use one authenticated requests.Session() with Matrix UPP cookies from
# environment variables for all API calls, as a short-term fix until a
# proper login/refresh flow is implemented.
MATRIX_SESSION = requests.Session()

_matrix_cookie_domain = None
if MATRIX_API_BASE_URL:
    try:
        _matrix_cookie_domain = urlparse(MATRIX_API_BASE_URL).hostname
    except Exception:
        _matrix_cookie_domain = None

for _cookie_name, _env_name in (
    ("JWT_TOKEN", "MATRIX_JWT_TOKEN"),
    ("REFRESH_TOKEN", "MATRIX_REFRESH_TOKEN"),
    ("JSESSIONID", "MATRIX_JSESSIONID"),
):
    _cookie_val = os.environ.get(_env_name, "")
    if _cookie_val:
        MATRIX_SESSION.cookies.set(_cookie_name, _cookie_val, domain=_matrix_cookie_domain)

if MATRIX_API_AUTH_TOKEN:
    # Keep the Bearer token as a fallback for endpoints that support it,
    # while still sending it alongside cookies when harmless.
    MATRIX_SESSION.headers["Authorization"] = f"Bearer {MATRIX_API_AUTH_TOKEN}"

# Endpoints that mutate state — require explicit confirmation before firing.
# Add/remove entries here to control what this node is allowed to write to.
WRITE_ENDPOINT_MARKERS = (
    "saveArea", "automateThanaMatrix", "markAsRead", "markAsUnread",
    "updatePost", "saveInternalReport", "saveTelephonicReport",
    "storeIntReport", "saveCommandCenterReport", "saveTvReport",
    "topicAssignDistrict", "saveBookmarkGroup", "saveArchivalGroup",
    "addPostToBookmarks",
)

MULTIPART_ENDPOINT_MARKERS = (
    "saveInternalReport", "storeIntReport", "saveCommandCenterReport", "saveTvReport",
)


def _payload_goes_as_query_params(description: str) -> bool:
    """True if this endpoint's own description declares its (non-path,
    non-multipart) payload as query params rather than a JSON request body.
    Looked at only for POST — GET already always uses params=, and
    multipart endpoints are handled separately via MULTIPART_ENDPOINT_MARKERS
    before this would ever be consulted."""
    if not description:
        return False
    m = re.search(r"Payload:\s*([^.]*)", description, re.IGNORECASE)
    clause = m.group(1) if m else description
    return bool(re.search(r"\bquery param", clause, re.IGNORECASE))


def _load_external_endpoints() -> dict:
    try:
        with open(EXTERNAL_ENDPOINTS_FILE, "r") as f:
            raw = json.load(f)
    except Exception as e:
        print(f"⚠️ could not load {EXTERNAL_ENDPOINTS_FILE}: {e}")
        return {}

    resolved = {}
    for key, desc in raw.items():
        if key.startswith("http://") or key.startswith("https://"):
            resolved[key] = desc
        elif MATRIX_API_BASE_URL:
            resolved[f"{MATRIX_API_BASE_URL}{key}"] = desc
        else:
            print(f"⚠️ skipping relative endpoint {key} — MATRIX_API_BASE_URL not set")
    return resolved


EXTERNAL_ENDPOINTS = _load_external_endpoints()


def reload_external_endpoints() -> dict:
    """Re-reads EXTERNAL_ENDPOINTS_FILE and refreshes the module-level
    EXTERNAL_ENDPOINTS registry in place (so callers that imported the
    dict by reference keep seeing updates). Returns the refreshed dict."""
    global EXTERNAL_ENDPOINTS
    EXTERNAL_ENDPOINTS.clear()
    EXTERNAL_ENDPOINTS.update(_load_external_endpoints())
    return EXTERNAL_ENDPOINTS


def get_endpoint_batches(batch_size: int = None) -> List[Dict[str, str]]:
    """Splits the known endpoint registry into batches of `batch_size`
    (defaults to ENDPOINT_ROUTE_BATCH_SIZE) for the Stage-1 candidate
    gathering pass."""
    size = batch_size or ENDPOINT_ROUTE_BATCH_SIZE
    items = list(EXTERNAL_ENDPOINTS.items())
    return [dict(items[i:i + size]) for i in range(0, len(items), size)]


def safe_json_or_text(resp):
    try:
        return resp.json()
    except Exception:
        return resp.text[:2000]


def _clean_json_block(raw: str) -> str:
    """Local equivalent of ollamaagent2.clean_json_string — strips a
    ```json / ``` markdown fence wrapping an LLM's JSON output. Kept as a
    tiny private copy here (rather than importing from ollamaagent2) so
    this module has zero dependency on the LLM-owning file."""
    raw = (raw or "").strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else raw


# =========================
# STAGE 1 — CANDIDATE GATHERING
# (prompt build / response parse only — caller makes the actual LLM call)
# =========================

_STOPWORDS = {"the", "a", "an", "of", "for", "to", "in", "on", "with", "and", "or",
              "is", "are", "me", "get", "give", "list", "all", "show", "find",
              "please", "under", "by", "from", "that", "this", "set"}


def keyword_overlap_candidates(query: str, batch: dict) -> list:
    """Deterministic safety net alongside the LLM pass: flags any endpoint
    whose description shares meaningful words with the query, so an
    obvious textual match can never be silently dropped by an LLM recall
    miss over a large batch. Deliberately permissive (same spirit as the
    LLM prompt) — Stage 2 does the strict filtering afterward."""
    q_words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in _STOPWORDS and len(w) > 2}
    if not q_words:
        return []
    hits = []
    for endpoint, desc in batch.items():
        d_words = {w for w in re.findall(r"[a-z0-9]+", desc.lower()) if w not in _STOPWORDS and len(w) > 2}
        if len(q_words & d_words) >= 2:  # at least 2 shared meaningful words
            hits.append(endpoint)
    return hits


def build_candidate_gather_prompt(query: str, batch: dict) -> str:
    """Stage 1 — loose pass over ONE batch of endpoints. Asks the LLM to
    flag every endpoint in this batch that could PLAUSIBLY relate to the
    query, erring on the side of inclusion. This is deliberately not the
    final decision — the Stage-2 rank prompt does the strict validation
    afterward, once candidates from ALL batches are combined."""
    return f"""You are a loose candidate-gathering pass over a list of
external API endpoints. Judge each endpoint ONLY against its own
description and the user's query below — ignore what domain the other
endpoints in this batch belong to; a generic or unrelated-looking
endpoint can still be the right match.

You will see the user's standalone query and a JSON map of external API
endpoints -> descriptions (what they return, required params, HTTP method).

Identify EVERY endpoint in this batch that could PLAUSIBLY relate to what
the user is asking — even loosely. Err on the side of including a
candidate if there's any reasonable chance it's relevant. A separate,
stricter validation step will filter this list afterward, so it is safe
to be permissive here. If NONE of the endpoints in this batch are even
loosely related, return an empty list.

Endpoints (endpoint -> description):
{json.dumps(batch, indent=2)}

User query: {query}

Respond with ONLY this JSON, no prose, no markdown fences:
{{
  "candidates": ["<endpoint string>", ...]
}}"""


def parse_candidate_gather_response(raw: str, batch: dict, query: str) -> list:
    """Parses the Stage-1 LLM response and unions it with the
    deterministic keyword-overlap floor — the union, not a replacement,
    since the keyword pass is a floor, not the whole answer."""
    try:
        parsed = json.loads(_clean_json_block(raw))
        llm_candidates = [c for c in parsed.get("candidates", []) if c in batch]
    except Exception:
        llm_candidates = []

    keyword_hits = keyword_overlap_candidates(query, batch)
    return list(dict.fromkeys(llm_candidates + keyword_hits))


# =========================
# STAGE 2 — STRICT RELEVANCY RANKING
# (prompt build / response parse only — caller makes the actual LLM call)
# =========================

def build_endpoint_rank_prompt(query: str, candidates: dict) -> str:
    """Stage 2 — strict relevancy check over the Stage-1 SHORTLIST, but
    instead of forcing exactly one winner, asks for EVERY candidate that
    genuinely matches, each tagged is_valid + relevance, so the caller can
    offer the user a choice instead of a single forced pick."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    last_week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    return f"""You are a strict endpoint relevancy validator inside a
police social-media intelligence agent. You are NOT the main router and
you must be conservative.

Current Date: {today}

This system ALSO has its own internal database covering: social media
posts, monitored user/account profiles, districts, viral/trending topics,
incidents, sentiment, engagement, platforms, and uploaded PDFs. Any query
that COULD reasonably be interpreted as asking about that internal domain
is NOT a match for an external endpoint, even if it never explicitly says
"internal" or names the external service.

Below is a SHORTLIST of candidate external API endpoints that a looser
first pass flagged as possibly relevant to the user's query. For EACH
candidate, decide independently whether it genuinely and unambiguously
answers what the user is asking, with no reasonable reading as an
internal-database question. Multiple candidates can be valid at once if
they each independently answer the query (e.g. from different angles) —
do not force a single winner.

For each valid candidate:
1. Extract every required and optional query parameter / body field the
   endpoint's OWN description declares, using values from the user's
   query, into "payload" (e.g. if the description says
   'tehsil (Long, required)' and the user asked about 'tehsil 105',
   extract {{"tehsil": 105}}). Every endpoint's payload is shaped by ITS
   OWN description only — do not carry fields from one candidate's
   description into another's payload. If a required field can't be
   found anywhere in the user's query, still include the candidate but
   leave that field out of "payload".
1a. ANY date/time field (fromDate, toDate, startDate, endDate, date,
   since, etc.) MUST be resolved to a concrete value computed from
   Current Date above — NEVER pass through a relative phrase like
   "last week", "yesterday", or "today" as a literal string. Use these
   as reference: today = {today}, yesterday = {yesterday},
   "last week" / "past 7 days" start = {last_week_start} (end = {today}).
   CHECK THE ENDPOINT'S OWN DESCRIPTION for the exact format it declares
   for that field:
     - If it says "format YYYY-MM-DD" (date only), use e.g. "{today}".
     - If it says "format YYYY-MM-DDTHH:MM" (or any format with a time
       component), append a time boundary: "T00:00" for the start-of-range
       field and "T23:59" for the end-of-range field, e.g.
       "{today}T00:00" / "{today}T23:59". Never send a bare date to a
       field whose declared format includes a time component — the API
       may reject or silently ignore it.
   If the query gives no date/time expression at all, leave that field
   out of "payload" rather than guessing a range.
2. Write "label" as one short plain-language sentence describing what
   running this lookup WOULD DO for the user (e.g. "Get the list of
   villages under tehsil 105"). Never mention the endpoint, URL, HTTP
   method, or any other technical detail in "label" — a non-technical
   user will read it as-is.

Candidate endpoints (endpoint -> description):
{json.dumps(candidates, indent=2)}

User query: {query}

Respond with ONLY this JSON, no prose, no markdown fences:
{{
  "matches": [
    {{
      "endpoint": "<endpoint string>",
      "method": "GET|POST",
      "payload": {{"param_name": <extracted_value>}},
      "is_valid": true or false,
      "relevance": "high|medium|low",
      "reasoning": "<one sentence, internal — why this endpoint matches>",
      "label": "<one sentence, user-facing — what running it would do>"
    }}
  ],
  "ambiguity_considered": "<one sentence on whether an internal-DB reading was possible overall, and why>"
}}"""


def parse_endpoint_rank_response(raw: str, candidates: dict) -> dict:
    try:
        parsed = json.loads(_clean_json_block(raw))
        matches = [
            m for m in parsed.get("matches", [])
            if m.get("endpoint") in candidates and m.get("is_valid")
        ]
        # highest relevance first
        _rank = {"high": 0, "medium": 1, "low": 2}
        matches.sort(key=lambda m: _rank.get((m.get("relevance") or "low").lower(), 2))
        parsed["matches"] = matches
        return parsed
    except Exception as e:
        return {"matches": [], "ambiguity_considered": f"parse error: {e}"}


def split_write_read_matches(matches: list) -> Tuple[list, list]:
    """Splits a Stage-2 match list into (write_matches, read_matches),
    where a write match is a POST hitting a WRITE_ENDPOINT_MARKERS
    endpoint — everything else is treated as a read."""
    write_matches = [
        m for m in matches
        if m.get("method", "").upper() == "POST"
        and any(marker.lower() in m["endpoint"].lower() for marker in WRITE_ENDPOINT_MARKERS)
    ]
    read_matches = [m for m in matches if m not in write_matches]
    return write_matches, read_matches


# =========================
# PAYLOAD / PATH-PARAM HANDLING
# =========================

def substitute_path_params(endpoint: str, payload: dict) -> Tuple[str, dict]:
    """Replaces {name} placeholders in the endpoint path using matching keys
    from payload (case-insensitive), removing consumed keys from the
    remaining payload. Returns (resolved_endpoint, remaining_payload)."""
    remaining = dict(payload)
    resolved = endpoint
    for match in re.findall(r"\{(\w+)\}", endpoint):
        for pkey in list(remaining.keys()):
            if pkey.lower() == match.lower():
                resolved = resolved.replace(f"{{{match}}}", str(remaining.pop(pkey)))
                break
    return resolved, remaining


_TYPE_PATTERN = re.compile(r"(\w+)\s*\(\s*(Long|Integer|Int|Short|Double|Float|Boolean)\b", re.IGNORECASE)
_PARAM_NAME_PATTERN = re.compile(r"(\w+)\s*\(\s*(?:Long|Integer|Int|Short|Double|Float|Boolean|String|Date|DateTime|Enum)\b", re.IGNORECASE)

_NUMERIC_TYPES = {"long", "integer", "int", "short", "double", "float"}
_BOOLEAN_TYPES = {"boolean"}


def fix_unrecognized_payload_keys(description: str, payload: dict) -> Tuple[dict, List[str]]:
    """Catches the 'startDate' vs 'startDateTime' class of bug: a payload key
    that doesn't match ANY parameter name the endpoint's own description
    declares. This is a NAME mismatch, distinct from validate_payload_types
    below (which only checks the TYPE of already-correctly-named numeric/
    boolean params) — a String-typed field like startDateTime was never
    covered by that check at all.

    When an unrecognized key is an unambiguous prefix of exactly one
    declared name (or vice versa) — e.g. payload has 'startDate' and the
    description declares 'startDateTime' — it's auto-renamed to the
    declared name before the call fires, since this is a common, mechanical
    LLM slip (dropping a suffix like 'Time') worth silently correcting
    rather than failing the whole call on. Ambiguous or unmatched keys are
    left as-is and reported so the caller can log/flag them; they are NOT
    dropped, since dropping a still-plausible param could silently change
    what the query returns.

    Returns (corrected_payload, warnings)."""
    declared_names = _PARAM_NAME_PATTERN.findall(description or "")
    if not declared_names:
        return payload, []  # description doesn't declare named params — nothing to check

    declared_lower = {n.lower(): n for n in declared_names}
    corrected = dict(payload)
    warnings = []

    for key in list(payload.keys()):
        if key.lower() in declared_lower:
            continue  # exact match (case-insensitive) — already correct

        key_lower = key.lower()
        prefix_matches = [orig for low, orig in declared_lower.items()
                           if low.startswith(key_lower) or key_lower.startswith(low)]
        if len(prefix_matches) == 1:
            correct_name = prefix_matches[0]
            corrected[correct_name] = corrected.pop(key)
            warnings.append(f"renamed unrecognized param '{key}' -> declared '{correct_name}'")
        else:
            warnings.append(f"'{key}' does not match any parameter this endpoint declares "
                             f"(declared: {sorted(declared_lower.values())})")

    return corrected, warnings


def validate_payload_types(description: str, payload: dict) -> List[str]:
    """Parses declared param types out of an endpoint's description string
    (e.g. 'tehsil (Long, required)') and checks the LLM-built payload
    against them BEFORE the request is fired. Returns a list of
    human-readable mismatch messages; empty list means it's safe to call."""
    declared = {name.lower(): dtype.lower() for name, dtype in _TYPE_PATTERN.findall(description or "")}
    if not declared:
        return []  # description doesn't declare typed params — nothing to check

    errors = []
    for key, value in payload.items():
        dtype = declared.get(key.lower())
        if not dtype:
            continue  # param not typed in the description — skip

        if dtype in _NUMERIC_TYPES:
            if not (isinstance(value, (int, float)) and not isinstance(value, bool)) and not (
                isinstance(value, str) and value.strip().lstrip("-").isdigit()
            ):
                errors.append(f"'{key}' must be a {dtype} (numeric ID), got {value!r}")
        elif dtype in _BOOLEAN_TYPES:
            if not isinstance(value, bool) and str(value).lower() not in ("true", "false"):
                errors.append(f"'{key}' must be a boolean, got {value!r}")

    return errors


# =========================
# CONFIRMATION / SELECTION CARDS
# =========================

def build_write_confirmation_card(decision: dict, write_id: str) -> Tuple[str, dict, str]:
    """Builds the write-confirmation payload + human-readable answer text
    for a single write match. Returns (resolved_endpoint, confirm_payload,
    answer_text)."""
    endpoint = decision["endpoint"]
    method = decision.get("method", "POST").upper()
    payload = decision.get("payload") or {}
    endpoint, payload = substitute_path_params(endpoint, payload)
    confirm_payload = {
        "type": "endpoint_write_confirmation",
        "write_id": write_id,
        "endpoint": endpoint,
        "method": method,
        "payload": payload,
    }
    field_summary = "\n".join(f"- **{k}**: {v}" for k, v in payload.items()) or "(no fields)"
    answer = (
        f"⚠️ This will **write data** to the Matrix system:\n\n"
        f"**Action:** `{endpoint}`\n\n{field_summary}\n\n"
        f"Reply to confirm, or say no to cancel.\n\n"
        f"```json\n{json.dumps(confirm_payload, ensure_ascii=False)}\n```"
    )
    return endpoint, confirm_payload, answer


def build_multi_selection_card(read_matches: list, query: str, selection_id: str) -> Tuple[dict, str]:
    """Builds the checkbox multi-select card offered when 2+ genuine read
    matches were found. Returns (selection_card, answer_text)."""
    candidates_payload = []
    for m in read_matches:
        ep, pl = substitute_path_params(m["endpoint"], m.get("payload") or {})
        candidates_payload.append({
            "endpoint": ep,
            "method": m.get("method", "GET").upper(),
            "payload": pl,
            "relevance": m.get("relevance", "medium"),
            "reasoning": m.get("reasoning", ""),
            "label": m.get("label", ""),
        })

    selection_card = {
        "type": "endpoint_multi_selection",
        "selection_id": selection_id,
        "query": query,
        "candidates": candidates_payload,
    }
    answer = (
        f"I found {len(candidates_payload)} endpoint(s) that could answer this. "
        f"Pick which ones to run:\n\n"
        f"```json\n{json.dumps(selection_card, ensure_ascii=False)}\n```"
    )
    return selection_card, answer


def resolve_single_read_match(match: dict) -> dict:
    """Resolves path params for the exactly-one-read-match fast path and
    returns the {"endpoint","method","payload"} item ready for
    call_read_endpoints."""
    ep, pl = substitute_path_params(match["endpoint"], match.get("payload") or {})
    return {"endpoint": ep, "method": match.get("method", "GET").upper(), "payload": pl}


# =========================
# WRITE EXECUTION (pure HTTP, no LLM)
# =========================

def validate_write_endpoint(endpoint: Optional[str]) -> Optional[str]:
    """Re-validates an echoed write endpoint against the CURRENT
    EXTERNAL_ENDPOINTS / WRITE_ENDPOINT_MARKERS before it's allowed to
    fire — never trusts an endpoint/payload blindly just because it
    round-tripped through the client. Returns an error message string if
    invalid, or None if it's safe to execute."""
    if not endpoint or endpoint not in EXTERNAL_ENDPOINTS:
        return f"rejected — endpoint '{endpoint}' is not a currently known endpoint"
    if not any(marker.lower() in endpoint.lower() for marker in WRITE_ENDPOINT_MARKERS):
        return f"rejected — '{endpoint}' is not a recognized write endpoint"
    return None


def execute_write_endpoint(endpoint: str, method: str, payload: dict) -> dict:
    """Fires the actual write HTTP call (GET/POST/multipart as declared by
    MULTIPART_ENDPOINT_MARKERS) and returns {"status_code","body"} or
    {"error": ...}. Caller is responsible for validating the endpoint
    first via validate_write_endpoint."""
    is_multipart = any(marker.lower() in endpoint.lower() for marker in MULTIPART_ENDPOINT_MARKERS)
    description = EXTERNAL_ENDPOINTS.get(endpoint, "")
    try:
        if method == "GET":
            resp = MATRIX_SESSION.get(endpoint, params=payload, timeout=15)
        elif is_multipart:
            files = {k: (None, str(v)) for k, v in payload.items()}
            resp = MATRIX_SESSION.post(endpoint, files=files, timeout=30)
        elif _payload_goes_as_query_params(description):
            # e.g. updatePost, addPostToBookmarks — declared as query params
            # in their own description, not a JSON body (see the note by
            # _payload_goes_as_query_params above).
            resp = MATRIX_SESSION.post(endpoint, params=payload, timeout=15)
        else:
            resp = MATRIX_SESSION.post(endpoint, json=payload, timeout=15)
        return {"status_code": resp.status_code, "body": safe_json_or_text(resp)}
    except Exception as e:
        return {"error": str(e)}


def build_write_result_prompt(endpoint: str, result: dict) -> str:
    return (
        f"Turn this API write result into a short plain-language confirmation for the user.\n"
        f"Endpoint: {endpoint}\nResult: {json.dumps(result)[:4000]}"
    )


# =========================
# READ EXECUTION (pure HTTP + parallel gather, no LLM)
# =========================

def _call_one_read(item: dict) -> dict:
    endpoint = item.get("endpoint")
    method = (item.get("method") or "GET").upper()
    payload = item.get("payload") or {}

    if not endpoint or endpoint not in EXTERNAL_ENDPOINTS:
        return {"endpoint": endpoint, "payload": payload, "error": "not a currently known endpoint"}
    if any(marker.lower() in endpoint.lower() for marker in WRITE_ENDPOINT_MARKERS):
        return {"endpoint": endpoint, "payload": payload, "error": "write endpoints are not runnable via multi-select"}

    # Auto-correct payload keys that don't match this endpoint's OWN
    # declared parameter names (e.g. 'startDate' sent where the
    # endpoint declares 'startDateTime') before firing — this is what
    # produced a raw backend 400 on getAllTopics ("Failed to convert
    # 'startDate'...") even though the VALUE was correctly formatted.
    description = EXTERNAL_ENDPOINTS.get(endpoint, "")
    payload, param_warnings = fix_unrecognized_payload_keys(description, payload)
    if param_warnings:
        logger.info(f"[mcp_services] payload key check for {endpoint}: {param_warnings}")

    type_errors = validate_payload_types(description, payload)
    if type_errors:
        logger.warning(f"[mcp_services] payload type mismatch for {endpoint}: {type_errors}")
        return {"endpoint": endpoint, "payload": payload,
                "error": f"payload type mismatch: {'; '.join(type_errors)}"}

    try:
        if method == "GET":
            resp = MATRIX_SESSION.get(endpoint, params=payload, timeout=15)
        elif _payload_goes_as_query_params(description):
            resp = MATRIX_SESSION.post(endpoint, params=payload, timeout=15)
        else:
            resp = MATRIX_SESSION.post(endpoint, json=payload, timeout=15)
        body = safe_json_or_text(resp)
        logger.info(f"[mcp_services] {method} {endpoint} params={payload} "
                    f"-> status={resp.status_code} body={json.dumps(body)[:500] if not isinstance(body, str) else body[:500]}")
        return {"endpoint": endpoint, "payload": payload, "status_code": resp.status_code, "body": body}
    except Exception as e:
        logger.error(f"[mcp_services] Error occurred while calling {endpoint}: {e}")
        return {"endpoint": endpoint, "payload": payload, "error": str(e)}


async def call_read_endpoints(selected: list) -> list:
    """Re-validates every item against the CURRENT EXTERNAL_ENDPOINTS,
    NEVER executes anything matching WRITE_ENDPOINT_MARKERS regardless of
    what the caller sends, and runs all validated calls in parallel.
    requests is blocking — each call runs on a worker thread so
    asyncio.gather actually overlaps them instead of serializing."""
    return await asyncio.gather(*[asyncio.to_thread(_call_one_read, item) for item in selected])


def extract_payload(body):
    """This Java API wraps real content in an envelope:
    {"username", "message", "statusCode", "size", "data"}. Only `data` is
    actual content — message/username/statusCode are process metadata and
    must never be treated as findings by the summarizing LLM. Returns None
    when the source genuinely found nothing (empty dict/list/null data),
    so the caller can tell "no results" apart from "no data field at all"
    (e.g. jsonplaceholder's plain array body, which has no envelope and is
    passed through unchanged)."""
    if isinstance(body, dict) and "data" in body:
        data = body["data"]
        if data in ({}, [], None):
            return None
        return data
    return body


def classify_read_results(results: list) -> Tuple[list, list, list, list, int]:
    """Splits raw call_read_endpoints() results into
    (succeeded, failed, payloads, non_empty_payloads, empty_source_count)."""
    succeeded = [r for r in results if "error" not in r and r.get("status_code") == 200]
    failed = [r for r in results if r not in succeeded]

    payloads = [extract_payload(r.get("body")) for r in succeeded]
    non_empty_payloads = [p for p in payloads if p is not None]
    empty_source_count = len(payloads) - len(non_empty_payloads)
    return succeeded, failed, payloads, non_empty_payloads, empty_source_count


# =========================
# RESULT SHAPING / SUMMARY-PROMPT BUILDING
# =========================

_TITLE_FIELD_HINTS = ("title", "name", "headline", "subject")
# NOTE: "label" was previously in this list but was removed — in this
# domain, "*_label" fields (e.g. sentiment_label: positive/neutral/negative)
# are categorical/enum fields, i.e. exactly the kind of field we WANT
# detect_summary_fields to pick as a category, not exclude as a display
# title. Keeping "label" here caused sentiment_label to be misclassified
# as a title-hinted field and silently dropped from categorization even
# after the whole-token-matching fix below (see field_matches_hint).


def field_matches_hint(field_name: str, hints: tuple) -> bool:
    """True if `field_name` contains one of `hints` as a distinct
    underscore/camelCase-separated token — NOT merely as a raw substring.

    A plain `hint in field_name.lower()` check makes 'sentiment_label'
    match the 'label' hint purely by coincidence of spelling, even though
    it's a categorical field (values: positive/neutral/negative), not a
    title/display-label field. Token-boundary matching (split on '_' and
    non-alphanumeric chars) still correctly matches genuine cases like
    'topic_title' or 'post_bank_post_title' -> 'title'."""
    tokens = re.findall(r"[a-z0-9]+", field_name.lower())
    return any(h in tokens for h in hints)


def find_nested_record_list(d: dict):
    """Structural, schema-agnostic scan for the real per-record collection
    hiding inside a bare dict payload — e.g. sentimentPost's
    {"groupedPosts": {"positive": [...], "neutral": [...], "negative": [...]}},
    where the actual posts sit inside a DICT of sentiment-bucket LISTS, not
    directly under a list key.

    Looks for:
      - a top-level list that is itself all dicts (one level down), or
      - a dict whose sub-values are lists of dicts (two levels down, e.g.
        groupedPosts.neutral / groupedPosts.positive / ...) — these get
        flattened together, or
      - a top-level list whose dict elements each wrap a genuinely bigger
        list-of-dicts field inside them (three levels down, e.g.
        ticketCountDashboard's data=[{"summary": {...}, "tabularData": [75
        per-district dicts]}] — the outer "data" list has only 1 element,
        so without this check it would be mistaken for "1 record found,"
        silently discarding all 75 real rows and forcing the summarizer
        onto raw/truncated JSON instead of a grounded aggregate; live
        testing on 2026-09-05 showed exactly this — a fabricated answer
        with invented categories that don't exist anywhere in the real
        response, because the real per-district records never reached
        detect_summary_fields/aggregate_records_for_summary at all).

    Whichever candidate yields the MOST dict records wins, so a payload
    that's genuinely just single-entity metadata (e.g. TopicByUniqueId's
    {"topic": {...}}, all scalar/string fields, no list-of-dicts anywhere)
    correctly finds nothing and returns None.

    Shared by aggregate_records_for_summary and prepare_payload_for_summary
    so both get an accurate record count out of bare-dict endpoint
    responses."""
    if not isinstance(d, dict):
        return None
    best_items, best_count = None, 0
    for v in d.values():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            if len(v) > best_count:
                best_items, best_count = v, len(v)
            # Also check one level deeper: does each dict element of this
            # list itself wrap a bigger list-of-dicts field? If so, that's
            # very likely the real record collection and this outer list
            # is just a thin metadata wrapper around it.
            nested_flat = []
            for item in v:
                for sub in item.values():
                    if isinstance(sub, list) and sub and all(isinstance(x, dict) for x in sub):
                        nested_flat.extend(sub)
            if len(nested_flat) > best_count:
                best_items, best_count = nested_flat, len(nested_flat)
        elif isinstance(v, dict):
            flat = []
            for sub in v.values():
                if isinstance(sub, list) and sub and all(isinstance(x, dict) for x in sub):
                    flat.extend(sub)
            if len(flat) > best_count:
                best_items, best_count = flat, len(flat)
    return best_items


def detect_summary_fields(items: list, max_category_fields: int = 3, sample_size: int = 200):
    """Schema-agnostic field detection — inspects actual record dicts (from
    WHATEVER endpoint they came from) and figures out which fields are worth
    aggregating, instead of assuming a fixed field name like 'topic_title'
    or 'broad_category' that only exists on one endpoint's response shape.

    - "category" fields: any key whose value is
        (a) a list, or a JSON-encoded string of a list (e.g. '["CRIME"]'), OR
        (b) a plain scalar string (e.g. sentiment_label='neutral').
      In both cases, a field only qualifies when the number of DISTINCT
      values seen is small relative to how often the field appears — i.e.
      values repeat across records, which is what makes a count meaningful.
      Fields whose name hints at being an identifier/title (see
      _TITLE_FIELD_HINTS) are excluded from category consideration even if
      they happen to repeat, since those are meant to label a record, not
      classify it.
    - "title" field: prefers a key whose name contains a common label hint
      (title/name/headline/subject); falls back to whichever string field
      has the highest distinct-value ratio (a proxy for "this is a
      human-readable identifier", since IDs/enums repeat but titles don't).

    Returns (category_fields, title_field). category_fields is [] when
    nothing aggregatable was found, signaling the caller to fall back to
    the raw-JSON summarization path instead.
    """
    field_stats: dict = {}
    for it in items[:sample_size]:
        if not isinstance(it, dict):
            continue
        for k, v in it.items():
            parsed_list = None
            if isinstance(v, list):
                parsed_list = v
            elif isinstance(v, str) and v.strip().startswith("["):
                try:
                    p = json.loads(v)
                    if isinstance(p, list):
                        parsed_list = p
                except Exception:
                    pass

            stat = field_stats.setdefault(
                k, {"kind": None, "list_values": {}, "str_values": [], "str_value_counts": {}, "total": 0}
            )
            if parsed_list is not None:
                stat["kind"] = "list"
                stat["total"] += 1
                for c in parsed_list:
                    if isinstance(c, str) and c:
                        stat["list_values"][c] = stat["list_values"].get(c, 0) + 1
            elif isinstance(v, str) and v:
                if stat["kind"] is None:
                    stat["kind"] = "str"
                stat["total"] += 1
                stat["str_values"].append(v)
                stat["str_value_counts"][v] = stat["str_value_counts"].get(v, 0) + 1

    ranked_category_fields = []
    for k, stat in field_stats.items():
        if stat["kind"] not in ("list", "str") or stat["total"] < 3:
            continue
        if stat["kind"] == "str" and field_matches_hint(k, _TITLE_FIELD_HINTS):
            # Identifier/label-like field name (title/name/headline/...) —
            # even if it happens to repeat, it's meant to LABEL a record
            # (picked up below as title_field), not classify it as a category.
            continue
        values = stat["list_values"] if stat["kind"] == "list" else stat["str_value_counts"]
        distinct = len(values)
        if distinct <= 1:
            continue  # nothing to break down if every record has the same single value
        ratio = distinct / stat["total"]
        if ratio <= 0.5:  # values repeat enough across records to be worth counting
            ranked_category_fields.append((k, ratio))
    ranked_category_fields.sort(key=lambda x: x[1])
    category_fields = [k for k, _ in ranked_category_fields[:max_category_fields]]

    title_field = None
    hinted = [k for k, stat in field_stats.items()
              if stat["kind"] == "str" and field_matches_hint(k, _TITLE_FIELD_HINTS)]
    if hinted:
        title_field = hinted[0]
    else:
        best_ratio = 0.0
        for k, stat in field_stats.items():
            if stat["kind"] == "str" and stat["total"] >= 3:
                distinct = len(set(stat["str_values"]))
                ratio = distinct / stat["total"]
                if ratio > best_ratio:
                    best_ratio, title_field = ratio, k

    return category_fields, title_field


def aggregate_records_for_summary(payloads: list, max_samples: int = 8):
    """Computes real per-field value counts and a small set of verbatim
    example titles IN CODE, for ANY list-of-record endpoint response
    (not one hardcoded schema) — see detect_summary_fields for how the
    relevant fields are chosen per response. Handing the LLM this small,
    already-correct table instead of a large raw JSON blob avoids relying
    on it to faithfully extract categories/titles itself.

    Handles both a flat list of records and the Spring Data pageable
    wrapper ({"content": [...], "totalElements": N, ...}), same as
    prepare_payload_for_summary.

    Returns None when no aggregatable category field was found (e.g. a
    payload of scalar stats, or a record shape with no repeating
    array-valued or scalar field), so the caller falls back to the generic
    raw-JSON summarization path for those endpoint shapes.
    """

    def _iter_items():
        top_level_items = []
        dict_only_payloads = []
        for p in payloads:
            if isinstance(p, dict) and isinstance(p.get("content"), list):
                top_level_items.extend(p["content"])
            elif isinstance(p, list):
                top_level_items.extend(p)
            elif isinstance(p, dict):
                dict_only_payloads.append(p)

        if top_level_items:
            # A genuine top-level list-of-records source was selected (e.g.
            # topicPostDetails) — don't ALSO pull items out of any bare-dict
            # payload selected alongside it (TopicByUniqueId, sentimentPost),
            # even if one of them structurally contains its own nested copy
            # of the same records (sentimentPost's groupedPosts is often the
            # same 12 posts topicPostDetails already returned). Pooling both
            # would double-count the same underlying posts (e.g. 12 + 12 =
            # 24) instead of reporting the true total.
            for item in top_level_items:
                yield item
            return

        # No top-level list source was selected — this is the case a bare
        # single-endpoint sentimentPost (or similar) call needs: its real
        # category/sentiment data per post is nested, not at the top level,
        # so without this fallback detect_summary_fields would see nothing
        # aggregatable and this call would (wrongly) fall through to the
        # raw-JSON path and risk inventing example content again.
        for p in dict_only_payloads:
            nested = find_nested_record_list(p)
            if nested:
                for item in nested:
                    yield item
            elif len(dict_only_payloads) == 1 and len(payloads) == 1:
                # Only treat the whole dict as a single record when it's the
                # ONLY payload for this query AND no nested collection was
                # found in it — a genuine single-entity response like
                # TopicByUniqueId's {"topic": {...}} called on its own.
                yield p

    items = [it for it in _iter_items() if isinstance(it, dict)]
    if not items:
        return None

    # Prefer authoritative pre-computed count maps returned by the API.
    # These remain useful even when every raw record has the same label
    # (e.g. all 9 posts are neutral), which detect_summary_fields correctly
    # treats as non-diverse for generic category aggregation.
    precomputed_counts = {}
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for field in ("sentimentCounts", "primaryEmotionCounts"):
            counts = payload.get(field)
            if not isinstance(counts, dict) or not counts:
                continue
            normalized = {}
            valid = True
            for value, count in counts.items():
                if isinstance(count, bool) or not isinstance(count, (int, float)):
                    valid = False
                    break
                normalized[str(value)] = count
            if valid and normalized:
                precomputed_counts[field] = normalized

    category_fields, title_field = detect_summary_fields(items)
    if not category_fields and not precomputed_counts:
        return None

    def _parse_field_values(raw):
        """Returns the category value(s) contained in a single field's raw
        value on one record — handles a genuine list, a JSON-array-string
        (e.g. '["PROTEST"]'), and a plain scalar string (e.g.
        sentiment_label='neutral') by treating the whole scalar as one
        value."""
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str):
            s = raw.strip()
            if s.startswith("["):
                try:
                    p = json.loads(s)
                    if isinstance(p, list):
                        return p
                except Exception:
                    pass
            if s:
                return [s]
        return []

    field_counts = dict(precomputed_counts)
    field_counts.update({f: {} for f in category_fields if f not in field_counts})
    samples_by_value: dict = {}

    for it in items:
        title = it.get(title_field) if title_field else None
        for f in category_fields:
            for c in _parse_field_values(it.get(f)):
                field_counts[f][c] = field_counts[f].get(c, 0) + 1
                if title and c not in samples_by_value:
                    samples_by_value[c] = title

    sample_titles = list(samples_by_value.values())[:max_samples]

    precomputed_total = 0
    for counts in precomputed_counts.values():
        precomputed_total = max(precomputed_total, sum(counts.values()))

    return {
        "total_items": max(len(items), precomputed_total),
        "field_counts": field_counts,  # {field_name: {value: count}}
        "title_field": title_field,
        "sample_titles": sample_titles,
    }


def prepare_payload_for_summary(payloads: list, char_budget: int = 12000) -> tuple:
    """Trims each payload down to a JSON-safe, char_budget-sized subset for
    the summarizing LLM prompt — never blindly slicing the serialized JSON
    string, which cuts large results off mid-object and hands the LLM a
    broken fragment that reads as if nothing had been found. Keeps only
    whole records/items within the budget and reports the TRUE total item
    count across all payloads so the prompt can explicitly tell the LLM
    "there are N results, a subset is shown" instead of letting it infer
    emptiness from a truncated blob.

    Some endpoints (e.g. Spring Data pageable APIs like getAllTopics) wrap
    their real list one level deeper: {"content": [...], "pageable": {...},
    "totalElements": N, "totalPages": ..., ...}. We detect that shape (a
    dict with a "content" list) and use "totalElements" for the true total
    and "content" for the actual items to trim.

    Returns (trimmed_payloads, total_item_count, was_truncated)."""
    total_item_count = 0
    trimmed = []
    truncated = False
    remaining_budget = char_budget
    for p in payloads:
        if isinstance(p, dict) and isinstance(p.get("content"), list):
            page_items = p["content"]
            total_item_count += p.get("totalElements", len(page_items))
            kept = []
            for item in page_items:
                item_str = json.dumps(item)
                if len(item_str) > remaining_budget:
                    truncated = True
                    break
                kept.append(item)
                remaining_budget -= len(item_str)
            if len(kept) < len(page_items):
                truncated = True
            trimmed.append(kept)
        elif isinstance(p, list):
            total_item_count += len(p)
            kept = []
            for item in p:
                item_str = json.dumps(item)
                if len(item_str) > remaining_budget:
                    truncated = True
                    break
                kept.append(item)
                remaining_budget -= len(item_str)
            trimmed.append(kept)
        else:
            # A bare dict here (not a list, not a Spring "content" page) may
            # be a genuine single-entity/summary envelope — e.g.
            # TopicByUniqueId's {"topic": {...}} — OR it may have a REAL
            # list of records hiding a level or two down — e.g.
            # sentimentPost's {"groupedPosts": {"neutral": [...12 posts...],
            # "positive": [], "negative": []}}. Check for a nested record
            # list FIRST and count its REAL length, regardless of how many
            # other payloads are in this batch. Only fall back to "+1 when
            # this is the sole payload" when no nested collection is found
            # at all — i.e. a genuine single-entity envelope.
            nested = find_nested_record_list(p)
            if nested:
                total_item_count += len(nested)
            elif len(payloads) == 1:
                total_item_count += 1
            item_str = json.dumps(p)
            if len(item_str) > remaining_budget:
                truncated = True
                trimmed.append(None)
            else:
                trimmed.append(p)
                remaining_budget -= len(item_str)
    return trimmed, total_item_count, truncated


def quick_total_count(non_empty_payloads: list) -> int:
    """Cheap, pure-computation check for whether ANY selected endpoint
    actually returned matching data — used to decide whether to fall back
    to the normal router_node pipeline instead of summarizing an empty
    result. No LLM call, so it's safe to run before deciding whether a
    summarization call is even needed."""
    _, total, _ = prepare_payload_for_summary(non_empty_payloads)
    return total


# Field names aggregate_records_for_summary() uses for API-provided
# pre-computed breakdowns (see `precomputed_counts` there). Kept as a
# constant here so build_record_aggregate_prompt can single them out for
# the query-relevance rule below without re-deriving the distinction.
_SENTIMENT_EMOTION_FIELDS = ("sentimentCounts", "primaryEmotionCounts")


def build_record_aggregate_prompt(query: str, record_aggregate: dict, failed: list, results: list) -> str:
    """Prompt for the code-computed aggregate summarization path — used
    when aggregate_records_for_summary() found an aggregatable category
    field. Real counts + real sample titles are computed in code; the LLM
    only has to phrase them, since narrative-summarization from a large
    raw JSON blob proved unreliable at faithfully extracting
    categories/titles.

    Sentiment/emotion counts are handled differently from other fields:
    aggregate_records_for_summary() always includes them when the API
    provided them (needed so an all-one-value sentiment field, e.g. every
    post "neutral", still gets reported instead of silently dropped — see
    detect_summary_fields' distinct<=1 rule). But "always computed" should
    not mean "always the headline of the answer" — a generic "show me the
    posts for this topic" question shouldn't come back as a sentiment
    breakdown. So field selection stays in code (unconditional, cheap,
    reliable), while RELEVANCE — whether sentiment/emotion should lead the
    answer — is left to the LLM via the FIELD RELEVANCE rule below, gated
    only on whether the question explicitly asks about it.
    """
    field_counts_desc = "\n".join(
        f"- {field} counts: {json.dumps(counts, ensure_ascii=False)}"
        + ("  [sentiment/emotion field — see FIELD RELEVANCE rule]" if field in _SENTIMENT_EMOTION_FIELDS else "")
        for field, counts in record_aggregate["field_counts"].items()
    )
    has_sentiment_fields = any(f in _SENTIMENT_EMOTION_FIELDS for f in record_aggregate["field_counts"])
    sentiment_relevance_rule = f"""
FIELD RELEVANCE — sentiment/emotion counts: one or more fields above are
marked as pre-computed sentiment/emotion breakdowns. Whether to lead with
them depends on the user's actual question, not just whether the data
exists:
- If the question explicitly asks about sentiment, emotion, mood, tone,
  feeling, or similar, including those counts is COMPULSORY.
- Otherwise, decide for yourself whether mentioning them helps answer
  what was actually asked. A general question (e.g. "show me the posts",
  "topic details", "what's in this topic") should be answered with the
  fields that actually address it — you may mention sentiment/emotion
  briefly if it adds value, or leave it out, at your discretion.
All other (non-sentiment/emotion) fields below should still be mentioned
as usual — this relevance judgment call applies only to sentiment/emotion.
""" if has_sentiment_fields else ""
    return f"""Answer the user's question using ONLY the aggregate data below,
which was computed directly from the real records in code (not generated
by you) — every number and value in it is guaranteed accurate. Do not
describe what you did, do not mention API calls, endpoints, URLs, status
codes, or technical process details of any kind — the user only wants
the answer.

STRICT RULE: The field values, counts, and example titles below are the
COMPLETE and ONLY real values found in the data. NEVER invent, add, or
substitute any category, topic, or subject that is not listed here — not
even as a plausible-sounding example. If you mention example items, use
ONLY the exact titles listed under "Real example titles" below, copied
verbatim (same language, same wording) — do not translate, paraphrase,
or invent new ones.
{sentiment_relevance_rule}
User's question: {query}

Total matching records: {record_aggregate['total_items']}
{field_counts_desc}
Real example titles (verbatim, do not alter): {json.dumps(record_aggregate['sample_titles'], ensure_ascii=False)}

Summarize what was found in plain language for a non-technical reader,
prioritizing whatever actually answers the user's question (see FIELD
RELEVANCE above for sentiment/emotion specifically — every other field
should still be mentioned as usual); include a few of the real example
titles listed above exactly as given. Never claim nothing was found —
{record_aggregate['total_items']} total record(s) exist.
{f"Note: {len(failed)} of {len(results)} data source(s) could not be reached — mention this in one brief, non-technical sentence at the end ONLY if it means the answer is incomplete. Never name or describe which source failed." if failed else ""}"""


def build_raw_json_summary_prompt(
    query: str,
    trimmed_payloads: list,
    total_item_count: int,
    was_truncated: bool,
    empty_source_count: int,
    payloads: list,
    failed: list,
    results: list,
) -> str:
    """Prompt for the generic raw-JSON summarization path — used when no
    aggregatable category field was found by aggregate_records_for_summary."""
    return f"""Answer the user's question using ONLY the data below. Do not describe
what you did, do not mention API calls, endpoints, URLs, status codes,
messages, or technical process details of any kind — the user only wants
the answer.

GROUNDING RULE: Every fact in your answer must trace back to an actual
field value in the JSON below (e.g. topic_title, broad_category,
sub_category, primary_districts, zone, created_at). NEVER invent example
categories, topics, or subjects that are not literally present in the
data (e.g. do not say "Technology" or "Healthcare" unless that exact
value appears in broad_category/sub_category below). If you are unsure
what a field means, describe it in plain language rather than guessing
or substituting a generic placeholder category.

When the data is a list of records (e.g. topics/incidents), do not just
describe the data's shape in the abstract — summarize the actual
content: mention real category names as they appear (e.g. CRIME,
TRAFFIC, GRIEVANCE, DISASTER), how many records fall in each if visible,
and 3-6 concrete example topic titles or descriptions taken directly
from the data, in plain language a non-technical reader can follow.

User's question: {query}

Data retrieved ({total_item_count} total matching record(s) found{"; only a subset is shown below due to size — this does NOT mean nothing was found" if was_truncated else ""}):
{json.dumps(trimmed_payloads)}

{f"Note: {total_item_count} total record(s) exist but only a partial subset is shown above because the full result was too large to include — do not say nothing was found; summarize the pattern/highlights ACTUALLY VISIBLE in the subset (real categories and topics, not invented ones) and mention that there are {total_item_count} results in total." if was_truncated else ""}
{f"Note: {empty_source_count} of {len(payloads)} successfully-reached source(s) returned no matching data — do not mention this fact unless it changes whether the answer is complete." if empty_source_count else ""}
{f"Note: {len(failed)} of {len(results)} data source(s) could not be reached — mention this in one brief, non-technical sentence at the end ONLY if it means the answer is incomplete. Never name or describe which source failed." if failed else ""}

Only say nothing matching was found if the total record count above is 0.
If the total record count is greater than 0, always summarize what was
found — even from a partial subset — grounded in the real field values
above, and never claim nothing was found."""