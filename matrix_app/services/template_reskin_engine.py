"""
Generic template reskin engine. Any uploaded HTML goes through the same two
calls: build_slot_layout() once at upload time, fill_template() every time a
report is generated. <head> is never touched. <body> is where every slot
lives, including chart data (the inline <script> sits inside <body>).
"""

import re
import json
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup

from . import db_schema_introspect

# Closed allowlist — a mapping (LLM or mechanical) can only point a slot at one of these.
REAL_DATA_FIELDS = [
    "topic_title", "districts", "sub_category", "created_at", "total_posts",
    "sentiment_counts", "sentiment_counts.negative", "sentiment_counts.neutral", "sentiment_counts.positive",
    "platform_counts", "platform_counts.TWITTER", "platform_counts.facebook", "platform_counts.Instagram",
    "platform_counts.YouTube", "platform_counts.whatsapp", "platform_counts.News_Rss_Feed",
    "engagement_totals", "engagement_totals.total_likes", "engagement_totals.total_comments",
    "engagement_totals.total_shares", "engagement_totals.total_views",
    "timeline", "top_posts", "hourly_counts", "weekday_counts", "emotion_counts",
    "keywords", "hashtags", "mentions", "monitored_handle_mentions",
    # The 5 "clean" tables from the schema audit (see
    # MATRIX_custom_template_reskin_plan.md §5) — all joined on
    # unique_topic_id (directly or one-hop), added by
    # fetch_topic_report_data() in dynamic_report_service.py.
    "viral_alerts", "viral_alert_performance", "topic_velocity_snapshots",
    "news_paper_cutting", "sentiment_entities",
]

UNVERIFIED_MARKER = '<span class="unverified">Not available</span>'

# List-shaped fields are the only ones a table_rows slot may bind to — each item becomes one row.
_LIST_SHAPED_FIELDS = {
    "top_posts", "timeline", "hourly_counts", "weekday_counts", "monitored_handle_mentions",
    "keywords", "hashtags", "mentions",
    # viral_alert_performance is deliberately excluded — it's a single
    # UNIQUE-keyed row per topic , not a list of rows, so it's
    # only mappable to stat_number/freetext slots, same as engagement_totals.
    "viral_alerts", "topic_velocity_snapshots", "news_paper_cutting", "sentiment_entities",
}
_MAX_TABLE_ROWS = 10

# Composite/dict-shaped parent keys — present in REAL_DATA_FIELDS only so
# their `.subfield` children (sentiment_counts.negative, etc.) are valid
# mapping targets. The parent key itself is never a valid destination for
# a scalar slot (stat_number/freetext/chip_list) — resolving it hands
# fill_template() a raw dict, and stat_number's fallback used to str() that
# dict straight into the page (e.g. "{'negative': 6838, 'neutral': ...}").
# Must be excluded from `allowed` everywhere a scalar slot's allowlist is
# built, both in the heuristic/chip path and the LLM-mapping path below.
_COMPOSITE_FIELDS = {"sentiment_counts", "platform_counts", "engagement_totals"}

# Heuristics only cover common report shapes — bare numbers/percentages and class-name hints.
_NUMBER_RE = re.compile(r"^[\d,]+(\.\d+)?%?[a-zA-Z]{0,3}$")
_STAT_CLASS_HINTS = ("val", "stat", "kpi", "metric", "number", "bar-count")
_FREETEXT_CLASS_HINTS = ("blurb", "desc", "summary", "note")
_MIN_FREETEXT_CHARS = 60

_IGNORE_STAT_CLASSES = {
    "badge", "badge-lg", "mod-index", "step-num", "icon", "sample-badge",
    "nav-home-btn", "btn", "button", "dot", "tl-dot", "crumb-bar", "pn-lbl", "pn-title", "footer"
}

# logic_unconfirmed text scan — matched against a slot's stored Meaning text.
_LOGIC_UNCONFIRMED_RE = re.compile(
    r"placeholder|to be calibrated|confirm with|TBD", re.IGNORECASE
)


def _resolve_topic_field(topic_data: Dict[str, Any], field: Optional[str]) -> Any:
    """Extracts a scalar, dict, or list from topic_data supporting dotted nested paths."""
    if not field or not topic_data:
        return None
    if field in topic_data:
        return topic_data[field]
    if "." in field:
        parts = field.split(".")
        curr = topic_data
        for p in parts:
            if not isinstance(curr, dict):
                return None
            if p in curr:
                curr = curr[p]
            else:
                p_lower = p.lower()
                found = False
                for k, v in curr.items():
                    if str(k).lower() == p_lower:
                        curr = v
                        found = True
                        break
                if not found:
                    return None
        return curr
    return None


def _looks_like_stat(tag) -> bool:
    text = tag.get_text(strip=True)
    if not text or len(tag.find_all()) > 0:
        return False
    if tag.name in ("h1", "h2", "h3", "h4", "h5", "h6", "a", "button", "nav", "summary", "th"):
        return False
    tag_classes = set(c.lower() for c in tag.get("class", []))
    if tag_classes & _IGNORE_STAT_CLASSES:
        return False
    if tag.parent:
        parent_classes = set(c.lower() for c in tag.parent.get("class", []))
        if parent_classes & {"badge", "badge-lg", "mod-index", "crumb-bar", "footer", "tl-dot"}:
            return False
    classes = " ".join(tag.get("class", [])).lower()
    return bool(_NUMBER_RE.match(text)) or any(h in classes for h in _STAT_CLASS_HINTS)


def _looks_like_freetext(tag) -> bool:
    classes = " ".join(tag.get("class", [])).lower()
    text = tag.get_text(strip=True)
    if any(h in classes for h in ("module-blurb", "disclaimer", "note", "crumb-bar", "footer", "lede")):
        return False
    if tag.name in ("h1", "h2", "h3", "h4", "h5", "h6", "nav", "summary", "a", "th"):
        return False
    return len(text) >= _MIN_FREETEXT_CHARS and (
        tag.name == "p" or any(h in classes for h in _FREETEXT_CLASS_HINTS)
    )


def _looks_like_chip_list(tag) -> bool:
    classes = " ".join(tag.get("class", [])).lower()
    if "tag-cloud" in classes or "tag-list" in classes:
        return True
    chips = tag.find_all(class_=re.compile(r"tag-chip|tag|chip", re.I), recursive=False)
    return len(chips) >= 2


def _looks_like_post_cards(tag) -> bool:
    classes = " ".join(tag.get("class", [])).lower()
    if "post-cards" in classes or "posts-list" in classes:
        return True
    cards = tag.find_all(class_=re.compile(r"post-card|feed-card", re.I), recursive=False)
    return len(cards) >= 1


def _extract_chart_slots(script_text: str) -> List[Dict[str, Any]]:
    """Finds each canvas id + its data array via bracket-matching, not full JS parsing."""
    slots = []
    for m in re.finditer(r"getElementById\((['\"])(\w+)\1\)", script_text):
        canvas_id = m.group(2)
        data_m = re.search(r"data\s*:\s*\[", script_text[m.end():m.end() + 4000])
        if data_m:
            slots.append({"slot_type": "chart_series", "canvas_id": canvas_id})
    return slots


def _find_context_label(tag) -> str:
    """Finds adjacent text labels (e.g. .lbl, .bar-label) to accurately map metrics."""
    if tag.parent:
        for sib in tag.parent.find_all(class_=re.compile(r"lbl|label|bar-label|k|key|title", re.I)):
            if sib != tag:
                return sib.get_text(strip=True)
    prev = tag.find_previous_sibling()
    if prev:
        return prev.get_text(strip=True)
    return ""


def _heuristic_map(label: str, slot_type: str) -> Optional[str]:
    lbl = (label or "").lower()
    if not lbl:
        return None
    if "total post" in lbl or lbl == "posts":
        return "total_posts"
    if "like" in lbl:
        return "engagement_totals.total_likes"
    if "comment" in lbl:
        return "engagement_totals.total_comments"
    if "share" in lbl:
        return "engagement_totals.total_shares"
    if "view" in lbl:
        return "engagement_totals.total_views"
    if "negative" in lbl:
        return "sentiment_counts.negative"
    if "neutral" in lbl:
        return "sentiment_counts.neutral"
    if "positive" in lbl:
        return "sentiment_counts.positive"
    if "twitter" in lbl or lbl == "x":
        return "platform_counts.TWITTER"
    if "facebook" in lbl:
        return "platform_counts.facebook"
    if "instagram" in lbl:
        return "platform_counts.Instagram"
    if "youtube" in lbl:
        return "platform_counts.YouTube"
    if "whatsapp" in lbl:
        return "platform_counts.whatsapp"
    if "news" in lbl or "rss" in lbl:
        return "platform_counts.News_Rss_Feed"
    return None


def extract_body_slots(template_html: str) -> Tuple[str, "BeautifulSoup", List[Dict[str, Any]]]:
    """Tags candidate nodes in <body> with data-slot="sN" and returns the slot inventory."""
    soup = BeautifulSoup(template_html, "html.parser")
    body = soup.body or soup
    slots: List[Dict[str, Any]] = []
    counter = 0

    for tag in body.find_all(True):
        if tag.name == "script":
            continue
        # Skip if already inside a parent that has been designated as a container slot (table, chip_list, post_cards)
        if tag.find_parent(attrs={"data-slot": True}):
            continue
        # Skip documentation and navigation elements (Data Logic panels, blurbs, navbar, etc.)
        if tag.find_parent(class_=re.compile(r"dl-body|dl|module-blurb|disclaimer|navbar|ticker|crumb-bar|prevnext", re.I)):
            continue
        classes = " ".join(tag.get("class", [])).lower()
        if any(h in classes for h in ("dl-body", "module-blurb", "disclaimer", "navbar", "ticker", "crumb-bar", "prevnext")):
            continue

        slot_type = None
        context_lbl = ""
        if _looks_like_chip_list(tag):
            slot_type = "chip_list"
        elif _looks_like_post_cards(tag):
            slot_type = "post_cards"
        elif tag.name == "table":
            slot_type = "table_rows"
        elif _looks_like_stat(tag):
            slot_type = "stat_number"
            context_lbl = _find_context_label(tag)
        elif _looks_like_freetext(tag):
            slot_type = "freetext"
        
        if slot_type:
            counter += 1
            slot_id = f"s{counter}"
            tag["data-slot"] = slot_id
            slots.append({
                "slot_id": slot_id,
                "slot_type": slot_type,
                "sample_text": tag.get_text(strip=True)[:120],
                "context_label": context_lbl
            })

    for script in body.find_all("script"):
        for chart_slot in _extract_chart_slots(script.string or ""):
            counter += 1
            chart_slot["slot_id"] = f"s{counter}"
            slots.append(chart_slot)

    panel_info = _dl_panel_info(soup)
    for slot in slots:
        info = panel_info.get(slot.get("slot_id"))
        slot["chips"] = info["chips"] if info else []
        slot["meaning_text"] = info["meaning_text"] if info else ""

    return str(soup.head or ""), soup, slots


def _dl_panel_info(soup: "BeautifulSoup") -> Dict[str, Dict[str, Any]]:
    """slot_id -> {"chips": [...], "meaning_text": "..."} for every tagged
    node that has a following .dl-body panel."""
    mapping: Dict[str, Dict[str, Any]] = {}
    for kpi in soup.select(".kpi-card, canvas, table"):
        slot_id = kpi.get("data-slot")
        panel = kpi.find_next(class_="dl-body")
        if not slot_id or not panel:
            continue
        chips = [c.get_text(strip=True) for c in panel.select(".chip")]
        meaning_text = ""
        for line in panel.select(".dl-line"):
            label = line.find(class_="k")
            if label and label.get_text(strip=True).lower() == "meaning":
                value = line.find(class_="v")
                meaning_text = value.get_text(" ", strip=True) if value else ""
                break
        mapping[slot_id] = {"chips": chips, "meaning_text": meaning_text}
    return mapping


def _llm_map_prompt(slots: List[Dict[str, Any]]) -> str:
    return f"""Map each SLOT below to the single best-fitting field in REAL_DATA_FIELDS, or null if none fits.
Never invent a field name outside this list.

A field only fits if it represents the SAME real-world quantity the slot's
label/context describes — not merely the same data type. For example, a
slot labeled "Active Topics" is NOT a fit for "total_posts" just because
both are numbers; if no field in the list actually represents an active-
topic count, that slot must map to null. Guessing the closest available
number produces a wrong, misleading value on a real report — returning
null is always safer than a plausible-looking wrong field.

REAL_DATA_FIELDS:
{json.dumps(REAL_DATA_FIELDS)}

SLOTS:
{json.dumps(slots, ensure_ascii=False)}

Respond ONLY with a JSON array: [{{"slot_id": "...", "maps_to": "<field>" | null}}]"""


def build_slot_layout(template_html: str, call_llm_fn=None) -> Dict[str, Any]:
    """One-time, cached per uploaded template. Mechanical mapping first, LLM only for the rest."""
    head_html, soup, slots = extract_body_slots(template_html)

    unresolved = []
    for slot in slots:
        slot_type = slot["slot_type"]
        if slot_type == "chip_list":
            slot["maps_to"] = "keywords"
            continue
        if slot_type == "post_cards":
            slot["maps_to"] = "top_posts"
            continue

        allowed = _LIST_SHAPED_FIELDS if slot_type == "table_rows" else set(REAL_DATA_FIELDS) - _LIST_SHAPED_FIELDS - _COMPOSITE_FIELDS
        chip_hits = [c for c in slot.get("chips", []) if c.split(".")[-1] in allowed]
        
        # Try heuristic context mapping first
        heur = _heuristic_map(slot.get("context_label", ""), slot_type)
        if heur and heur in REAL_DATA_FIELDS:
            slot["maps_to"] = heur
        elif chip_hits:
            slot["maps_to"] = chip_hits[0].split(".")[-1]
        else:
            slot["maps_to"] = None

        if slot["maps_to"] is None and slot_type != "chart_series":
            unresolved.append(slot)

    if unresolved and call_llm_fn:
        raw = call_llm_fn(_llm_map_prompt(unresolved))
        try:
            for entry in json.loads(raw):
                for slot in slots:
                    if slot["slot_id"] != entry.get("slot_id"):
                        continue
                    field = entry.get("maps_to")
                    allowed = _LIST_SHAPED_FIELDS if slot["slot_type"] == "table_rows" else set(REAL_DATA_FIELDS) - _LIST_SHAPED_FIELDS - _COMPOSITE_FIELDS
                    slot["maps_to"] = field if field in allowed else None
        except (json.JSONDecodeError, TypeError):
            pass

    annotate_slot_status(slots)
    return {"head_html": head_html, "tagged_body_html": str(soup.body or soup), "slots": slots}


def annotate_slot_status(slots: List[Dict[str, Any]]) -> None:
    """Tags every slot dict in place with status."""
    for slot in slots:
        chips = slot.get("chips") or []
        if not chips:
            slot["status"] = "clean"
            continue

        tables_referenced = set()
        missing = False
        for chip in chips:
            if "." not in chip:
                continue
            table_name, _, column_name = chip.partition(".")
            table_name, column_name = table_name.strip(), column_name.strip()
            tables_referenced.add(table_name)
            if not db_schema_introspect.table_exists(table_name) or not db_schema_introspect.column_exists(
                table_name, column_name
            ):
                missing = True

        if missing:
            slot["status"] = "table_or_column_missing"
            continue

        if tables_referenced and any(
            db_schema_introspect.topic_join_status(t) == "none" for t in tables_referenced
        ):
            slot["status"] = "no_topic_join"
            continue

        if _LOGIC_UNCONFIRMED_RE.search(slot.get("meaning_text") or ""):
            slot["status"] = "logic_unconfirmed"
            continue

        slot["status"] = "clean"


def _patch_stat(tag, value: Any) -> None:
    tag.string = str(value)


def _fill_table_slot(table_tag, rows: Optional[List[Dict[str, Any]]]) -> None:
    """Keeps header; data rows generated from real dict values."""
    header = table_tag.find("thead") or table_tag.find("tr")
    col_count = len(header.find_all(["th", "td"])) if header else 1
    body_section = table_tag.find("tbody") or table_tag
    for tr in body_section.find_all("tr"):
        if tr.find("th") is None:
            tr.decompose()

    if not rows:
        note = table_tag.new_tag("tr")
        cell = table_tag.new_tag("td", colspan=str(col_count))
        cell.string = "Not available"
        note.append(cell)
        body_section.append(note)
        return

    for row in rows[:_MAX_TABLE_ROWS]:
        tr = table_tag.new_tag("tr")
        for value in row.values():
            td = table_tag.new_tag("td")
            td.string = str(value)
            tr.append(td)
        body_section.append(tr)


def _fill_chip_list(container_tag, items: Optional[Any]) -> None:
    """Fills a tag-cloud or list of chips with real keywords/hashtags."""
    container_tag.clear()
    tag_list = []
    if isinstance(items, str):
        try:
            parsed = json.loads(items)
            tag_list = parsed if isinstance(parsed, list) else [s.strip() for s in items.split(",") if s.strip()]
        except Exception:
            tag_list = [s.strip() for s in items.split(",") if s.strip()]
    elif isinstance(items, list):
        tag_list = items

    if not tag_list:
        span = container_tag.new_tag("span", **{"class": "unverified"})
        span.string = "Not available"
        container_tag.append(span)
        return

    for item in tag_list[:15]:
        val = str(item).strip()
        if not val:
            continue
        span = container_tag.new_tag("span", **{"class": "tag-chip"})
        span.string = val
        container_tag.append(span)


def _fill_post_cards(container_tag, posts: Optional[List[Dict[str, Any]]]) -> None:
    """Populates post card items with real post text and author metadata."""
    container_tag.clear()
    if not posts:
        div = container_tag.new_tag("div", **{"class": "post-card"})
        div.string = "No post evidence recorded for this topic."
        container_tag.append(div)
        return

    for p in posts[:5]:
        card = container_tag.new_tag("div", **{"class": "post-card"})
        meta = container_tag.new_tag("div", **{"class": "post-meta"})
        author = p.get("post_bank_author_name") or p.get("post_bank_author_username") or "Monitored Account"
        platform = p.get("post_bank_core_source") or "Social Media"
        date_str = str(p.get("created_at") or p.get("post_bank_post_date") or "")[:10]
        sentiment = (p.get("sentiment_label") or "neutral").lower()
        meta.string = f"@{author} · {platform} · {date_str} "
        chip = container_tag.new_tag("span", **{"class": f"sentiment-chip {sentiment}"})
        chip.string = sentiment.capitalize()
        meta.append(chip)
        card.append(meta)

        body = container_tag.new_tag("div", **{"class": "post-text"})
        body.string = str(p.get("input_text") or "")[:350]
        card.append(body)
        container_tag.append(card)


def _patch_chart(body_html: str, canvas_id: str, series: List[Any]) -> str:
    pattern = re.compile(
        rf"(getElementById\(['\"]{canvas_id}['\"]\).{{0,2000}}?data\s*:\s*)\[[^\]]*\]", re.S
    )
    return pattern.sub(lambda m: m.group(1) + json.dumps(series), body_html, count=1)


def _deterministic_no_data_fallback(meaning_text: str) -> str:
    first_clause = (meaning_text or "").split(".")[0].strip()
    if not first_clause:
        return UNVERIFIED_MARKER
    return f'<span class="unverified">{first_clause} — no recorded data for this topic.</span>'


def fill_template(
    layout: Dict[str, Any],
    topic_data: Dict[str, Any],
    call_llm_fn=None,
    availability_llm_fn=None,
) -> str:
    """Every-generation call. Unmapped/empty slots never render fabricated data."""
    soup = BeautifulSoup(layout["tagged_body_html"], "html.parser")

    title_tag = soup.find(attrs={"data-slot": True}) and soup.select_one("h1")
    if title_tag:
        title_tag.string = topic_data.get("topic_title", title_tag.get_text())

    total_posts = topic_data.get("total_posts", 0)

    body_html = str(soup)
    for slot in layout["slots"]:
        field = slot.get("maps_to")
        value = _resolve_topic_field(topic_data, field) if field else None

        if slot["slot_type"] == "chart_series":
            series = value if isinstance(value, list) else None
            if series is not None:
                body_html = _patch_chart(body_html, slot["canvas_id"], series)
            else:
                canvas_id = slot.get("canvas_id")
                if canvas_id:
                    soup2 = BeautifulSoup(body_html, "html.parser")
                    canvas_tag = soup2.find(id=canvas_id)
                    if canvas_tag:
                        empty_div = soup2.new_tag("div", **{
                            "class": "unverified",
                            "style": "display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-faint,#8891AC);font-size:0.88rem;text-align:center;padding:30px 10px;"
                        })
                        empty_div.string = "No time-series data recorded for this metric on this topic."
                        canvas_tag.replace_with(empty_div)
                        body_html = str(soup2)
            continue

        soup2 = BeautifulSoup(body_html, "html.parser")
        node = soup2.find(attrs={"data-slot": slot["slot_id"]})
        if node is None:
            continue

        if slot["slot_type"] == "table_rows":
            _fill_table_slot(node, value if isinstance(value, list) else None)
        elif slot["slot_type"] == "chip_list":
            _fill_chip_list(node, value)
        elif slot["slot_type"] == "post_cards":
            _fill_post_cards(node, value if isinstance(value, list) else None)
        elif value is None:
            status = slot.get("status", "clean")
            meaning_text = slot.get("meaning_text", "")
            fallback_text = None
            if status == "clean" and availability_llm_fn:
                fallback_text = availability_llm_fn(meaning_text, slot.get("chips") or [])
            node.clear()
            if fallback_text:
                node.append(BeautifulSoup(f'<span class="unverified">{fallback_text}</span>', "html.parser"))
            else:
                node.append(BeautifulSoup(_deterministic_no_data_fallback(meaning_text), "html.parser"))
        elif slot["slot_type"] == "stat_number":
            if isinstance(value, (int, float)):
                node.string = f"{value:,}"
            elif isinstance(value, (dict, list)):
                # Defense in depth: a composite/list-shaped value should
                # never reach here (see _COMPOSITE_FIELDS in
                # build_slot_layout()), but if a bad mapping slips through
                # anyway, treat it as no-data rather than str()-dumping a
                # dict/list repr onto the page.
                status = slot.get("status", "clean")
                meaning_text = slot.get("meaning_text", "")
                fallback_text = None
                if status == "clean" and availability_llm_fn:
                    fallback_text = availability_llm_fn(meaning_text, slot.get("chips") or [])
                node.clear()
                if fallback_text:
                    node.append(BeautifulSoup(f'<span class="unverified">{fallback_text}</span>', "html.parser"))
                else:
                    node.append(BeautifulSoup(_deterministic_no_data_fallback(meaning_text), "html.parser"))
            elif value is not None:
                node.string = str(value)

            # Update bar fill width if inside a .bar-row
            bar_row = node.find_parent(class_="bar-row")
            if bar_row:
                bar_fill = bar_row.find(class_="bar-fill")
                if bar_fill and total_posts and isinstance(value, (int, float)):
                    pct = min(100, max(2, round(value / total_posts * 100)))
                    existing_bg = ""
                    if "style" in bar_fill.attrs:
                        bg_m = re.search(r"background:\s*([^;]+)", bar_fill["style"])
                        if bg_m:
                            existing_bg = f";background:{bg_m.group(1)}"
                    bar_fill["style"] = f"width:{pct}%{existing_bg}"
        elif slot["slot_type"] == "freetext" and call_llm_fn:
            node.string = call_llm_fn(f"Rephrase this as one short sentence using only this real value: {value}")
        body_html = str(soup2)

    return layout["head_html"] + body_html