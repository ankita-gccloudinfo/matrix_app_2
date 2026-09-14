"""

Thin wrapper around the `adhoc_report_sidecar` service (a self-hosted
abi/screenshot-to-code backend, see adhoc_report_sidecar/README.md) —
turns a free-form design brief into a raw HTML document with placeholder
data, over that service's `/generate-code` WebSocket endpoint.

Deliberately isolated from the rest of the report pipeline: this module
does NOT touch MySQL, does NOT call template_reskin_engine, and is not
wired into any FastAPI route yet. It should be callable and testable on
its own — see the "Manual test" section at the bottom of this file.

Protocol note: the request/response shape below was confirmed against
this project's own cloned copy of `backend/routes/generate_code.py`
(no `Params` BaseModel — raw `websocket.receive_json()` validated into
`ExtractedParams` via `ParameterExtractionStage`). Text-only ("create",
no screenshot) generation is confirmed supported on this same
`/generate-code` route. Still worth re-checking after any upstream pull,
since this isn't a versioned public API:

    grep -n "class ExtractedParams" -A 40 adhoc_report_sidecar/screenshot-to-code/backend/routes/generate_code.py
"""

import asyncio
import json
from typing import Optional

import websockets

# Internal-only sidecar from adhoc_report_sidecar/docker-compose.yml —
# bound to 127.0.0.1, reachable only from this same host, never public.
ADHOC_SIDECAR_WS_URL = "ws://127.0.0.1:7001/generate-code"

# Generous timeout: this is a full-document LLM generation over the same
# vLLM backend dynamic_report_service.py already calls (see
# _call_template_llm's own 300s timeout for the equivalent reskin call).
_GENERATION_TIMEOUT_SECONDS = 300


class AdhocGenerationError(Exception):
    """Raised when the sidecar can't be reached, times out, or returns
    something that isn't usable HTML. Mirrors how TemplateRenderError is
    used elsewhere in dynamic_report_service.py — callers must not hand a
    bad response to the slot-layout pipeline unchecked."""


_GENERATION_SYSTEM_PROMPT = """You are designing a single-page HTML intelligence report layout for a
police/public-safety social-media monitoring platform.

Generate ONE complete, self-contained HTML document (inline <style>, no
external framework build step) matching the design notes below. Since no
real data is available yet, fill every data-driven element with realistic
PLACEHOLDER values in these categories only — do not invent categories
that aren't in this list:
- total post / mention counts (plausible numbers, e.g. "1,284")
- sentiment breakdown (negative/neutral/positive, as percentages)
- platform breakdown (Twitter/X, Instagram, Facebook, YouTube, WhatsApp)
- engagement totals (likes, comments, shares, views)
- 3-5 keyword or hashtag chips
- 2-3 sample "post card" entries (author, platform, short sample text,
  sentiment tag) — clearly fictional placeholder content, not claims
  about any real person or event
- a simple chart (bar or line) reflecting one of the above categories

Requirements:
- Valid, complete HTML from <!doctype html> to </html>.
- No JavaScript frameworks (React/Vue) and no build tooling — plain
  HTML/CSS(/small inline <script> for a chart is fine).
- Keep placeholder numbers plausible but clearly generic — this output
  will later have every one of these values replaced by real data from a
  separate pipeline step; do not make them so specific/dramatic that a
  reviewer mistakes them for real.
- Design for a fixed print page, ~800px content width, portrait orientation.
  Never use vh/vw units, 100vh/100vw containers, or any other
  viewport-relative sizing — this document is rendered to a PDF page, not a
  browser window, and viewport units collapse unpredictably in that context.
- Assume the real topic behind this layout may end up with very little data
  — as few as a single real post, with most other fields unavailable. Do not
  build a layout where one region can end up mostly empty while another is
  full (e.g. a wide sidebar next to a short main column, or a multi-column
  split where one column has much more content than the other). Prefer a
  single main column of modular, independently-stacking sections. If a
  sidebar or split layout is genuinely part of the brief, cap its width, do
  not give it a fixed min-height, and let it shrink gracefully when its
  content is short."""


def _build_design_prompt(design_notes: str, content_focus: list) -> str:
    focus_line = (
        f"\nCONTENT FOCUS (prioritize these sections): {', '.join(content_focus)}"
        if content_focus else ""
    )
    return f"{_GENERATION_SYSTEM_PROMPT}\n\nDESIGN NOTES FROM REQUESTER:\n{design_notes}{focus_line}"


def _build_request_params(prompt_text: str) -> dict:
    """Builds the JSON payload sent over the WebSocket — matches
    `ExtractedParams`/`ParameterExtractionStage.extract_and_validate()`
    confirmed against this project's own clone (see module docstring)."""
    return {
        "inputMode": "text",  # text-only create, no screenshot/image
        "generationType": "create",
        "generatedCodeConfig": "html_tailwind",
        "prompt": {
            "text": prompt_text,
            "images": [],
            "videos": [],
        },
        "isImageGenerationEnabled": False,  # no DALL-E/Replicate placeholder images needed
        "isAssetExtractionEnabled": False,  # nothing to crop/extract with no image input
        "history": [],  # fresh "create", not an "update" turn
    }


def _parse_stream_message(raw_message: str) -> Optional[dict]:
    """Parses one WebSocket text frame. Returns None for anything that
    isn't valid JSON (defensive — some deployments send plain-text status
    lines rather than JSON)."""
    try:
        return json.loads(raw_message)
    except (json.JSONDecodeError, TypeError):
        return None


async def _generate_layout_html_async(design_notes: str, content_focus: list) -> str:
    prompt_text = _build_design_prompt(design_notes, content_focus)
    params = _build_request_params(prompt_text)

    collected_html_by_variant: dict = {}
    errored_variants: set = set()
    expected_variant_count: Optional[int] = None

    try:
        async with websockets.connect(
            ADHOC_SIDECAR_WS_URL,
            open_timeout=10,
        ) as ws:
            await ws.send(json.dumps(params))

            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=_GENERATION_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    raise AdhocGenerationError(
                        f"Sidecar generation timed out after {_GENERATION_TIMEOUT_SECONDS}s "
                        "(no message received in that window)."
                    )

                msg = _parse_stream_message(raw)
                if msg is None:
                    continue

                msg_type = msg.get("type")

                if msg_type == "error":
                    # Global failure — sent before the socket closes.
                    raise AdhocGenerationError(f"Sidecar returned a global error: {msg.get('value')!r}")

                if msg_type == "variantCount":
                    try:
                        expected_variant_count = int(msg.get("value"))
                    except (TypeError, ValueError):
                        expected_variant_count = None
                    continue

                if msg_type == "variantError":
                    variant = msg.get("variantIndex", 0)
                    errored_variants.add(variant)
                    collected_html_by_variant.pop(variant, None)
                    if expected_variant_count and len(errored_variants) >= expected_variant_count:
                        raise AdhocGenerationError(
                            f"All {expected_variant_count} variant(s) failed; last error: {msg.get('value')!r}"
                        )
                    continue

                if msg_type == "chunk":
                    variant = msg.get("variantIndex", 0)
                    if variant in errored_variants:
                        continue
                    collected_html_by_variant[variant] = (
                        collected_html_by_variant.get(variant, "") + msg.get("value", "")
                    )
                    continue

                if msg_type == "setCode":
                    # Full accumulated code for this variant, sent once —
                    # replaces (not appends to) anything collected via chunks.
                    variant = msg.get("variantIndex", 0)
                    if variant not in errored_variants:
                        collected_html_by_variant[variant] = msg.get("value", "")
                    continue

                if msg_type == "variantComplete":
                    # Pure completion signal — no code payload of its own;
                    # the html should already be sitting in collected_html_by_variant
                    # from prior "chunk"/"setCode" messages for this variant.
                    variant = msg.get("variantIndex", 0)
                    if variant in collected_html_by_variant and variant not in errored_variants:
                        return collected_html_by_variant[variant]
                    continue

                # "status"/"variantModels"/"thinking"/"assistant"/"toolStart"/
                # "toolResult" are ignored here — no progress callback wired
                # up yet, and none of them carry final code.

    except AdhocGenerationError:
        raise
    except (websockets.exceptions.WebSocketException, OSError) as exc:
        raise AdhocGenerationError(
            f"Could not reach adhoc_report_sidecar at {ADHOC_SIDECAR_WS_URL}: {exc}. "
            "Confirm it's running: `docker compose ps` inside adhoc_report_sidecar/."
        ) from exc

    # Fell out of the loop (socket closed) without an explicit
    # "variantComplete" for a healthy variant — fall back to any collected,
    # non-errored variant rather than losing it.
    for variant, html in collected_html_by_variant.items():
        if variant not in errored_variants and html:
            return html
    raise AdhocGenerationError("Sidecar connection closed with no usable generated content received.")


def generate_layout_html(design_notes: str, content_focus: Optional[list] = None) -> str:
    """Synchronous entry point — matches the calling convention of every
    other function in dynamic_report_service.py (_call_layout_llm,
    _call_template_llm, etc. are all sync `requests` calls; build_report /
    build_freeform_report wrap their sync work in asyncio.to_thread at the
    server.py layer, not here).

    Raises AdhocGenerationError on any failure. Callers must not hand a
    bad/partial response to template_reskin_engine.build_slot_layout()
    unchecked — same posture as render_from_template's callers.
    """
    return asyncio.run(_generate_layout_html_async(design_notes, content_focus or []))


# ── Manual test (Phase 1 exit criteria) ─────────────────────────────────
# Run directly to confirm the sidecar round-trips a real design brief
# into valid HTML, with zero MySQL/Playwright/route involvement:
#
#   cd matrix_app
#   python3 -m services.adhoc_generation_service
#
if __name__ == "__main__":
    test_notes = "A concise executive-brief style report, indigo/purple theme, sentiment and top posts up front."
    try:
        html = generate_layout_html(test_notes, content_focus=["sentiment", "top_posts", "overview"])
        print(f"Received {len(html)} chars.")
        print("Looks like a full HTML doc:", html.strip().lower().startswith(("<!doctype html", "<html")))
        print(html[:500])
    except AdhocGenerationError as exc:
        print(f"AdhocGenerationError: {exc}")