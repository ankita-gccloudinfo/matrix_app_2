"""
Live-DB schema introspection for the template reskin engine's mechanical
slot-status checks (see annotate_slot_status() in template_reskin_engine.py
and MATRIX_custom_template_reskin_plan.md §4-§5).

Two things live here:
  1. A cached, TTL'd snapshot of information_schema.columns for the
     connected database — table/column existence checks must never hit the
     DB per-slot, per-request (build_slot_layout runs once per upload, but
     with dozens of chips per template, per-chip queries would still be
     wasteful and slow).
  2. A generic, convention-based BFS join-path check for
     topic.unique_topic_id. There are no declared FK constraints in this
     schema (see mysql_db.py / DB_SCHEMA_YAML notes elsewhere in the repo),
     so "is this table joinable to a topic" can't be answered from
     information_schema.key_column_usage — it's inferred from column-naming
     convention instead: a column literally named "<other_table>_id" is
     treated as an informal FK to other_table.id. Capped at 2 hops, which
     covers every case found in the schema audit (see plan §5) — e.g.
     sentiment_entities.analyzed_data_id -> analyzed_data.id ->
     analyzed_data.unique_topic_id is a 1-hop (2-edge) path.
"""

import os
import time
from typing import Dict, List, Optional, Set

from database.mysql_db import run_query

TOPIC_TABLE = "topic"
TOPIC_JOIN_COLUMN = "unique_topic_id"

# How many intermediate tables the BFS is allowed to pass through before
# giving up. 2 covers every path found in the schema audit; raising this
# risks the BFS "discovering" coincidental *_id name collisions that aren't
# real relationships, which is worse than a false no_topic_join.
_MAX_HOPS = 2

_CACHE_TTL_SECONDS = int(os.getenv("SCHEMA_INTROSPECT_TTL_SECONDS", "900"))

_cache: Dict[str, Set[str]] = {}
_cache_at: float = 0.0


def _load_schema() -> Dict[str, Set[str]]:
    """table_name -> set of column_name, scoped to the connected database only."""
    rows = run_query(
        "SELECT table_name AS table_name, column_name AS column_name "
        "FROM information_schema.columns WHERE table_schema = DATABASE()"
    )
    schema: Dict[str, Set[str]] = {}
    for row in rows:
        # mysql.connector returns information_schema column names in
        # whatever case the server reports them in (commonly TABLE_NAME /
        # COLUMN_NAME, uppercase, regardless of how the query was written)
        # — the explicit "AS table_name" above fixes this for a normal
        # MySQL server, but Aurora/MariaDB/version differences have been
        # known to still return the source case, so this is normalized
        # defensively rather than trusted to always come back lowercase.
        row = {k.lower(): v for k, v in row.items()}
        schema.setdefault(row["table_name"], set()).add(row["column_name"])
    return schema


def get_schema_snapshot(force_refresh: bool = False) -> Dict[str, Set[str]]:
    """The only function here that hits the DB — everything else below reads
    the cache this returns. Cached module-wide (not per-request) with a TTL
    so the live schema is still picked up if tables/columns change without a
    server restart. A failed refresh serves the last good snapshot rather
    than failing the whole upload — unless there's no prior snapshot at all,
    in which case the exception propagates (nothing safe to fall back to)."""
    global _cache, _cache_at
    stale = force_refresh or not _cache or (time.monotonic() - _cache_at) > _CACHE_TTL_SECONDS
    if stale:
        try:
            fresh = _load_schema()
            _cache = fresh
            _cache_at = time.monotonic()
        except Exception as exc:
            if not _cache:
                raise
            print(f"[db_schema_introspect] Schema refresh failed, serving stale cache: {exc}")
    return _cache


def table_exists(table_name: str) -> bool:
    return table_name in get_schema_snapshot()


def column_exists(table_name: str, column_name: str) -> bool:
    return column_name in get_schema_snapshot().get(table_name, set())


def topic_join_path(table_name: str) -> Optional[List[str]]:
    """BFS from table_name to a column named topic_join_column, hopping over
    "<other_table>_id"-named columns (informal FK convention — no declared
    FK constraints exist). Returns the path as a list of "table.column" hop
    descriptors (e.g. ["sentiment_entities.analyzed_data_id",
    "analyzed_data.id", "analyzed_data.unique_topic_id"]), or None if no
    path is found within _MAX_HOPS intermediate tables."""
    schema = get_schema_snapshot()
    if table_name not in schema:
        return None

    visited = {table_name}
    frontier = [(table_name, [])]  # (current_table, hops_taken_to_reach_it)

    for hop in range(_MAX_HOPS + 1):
        next_frontier = []
        for current_table, path_so_far in frontier:
            columns = schema.get(current_table, set())
            if TOPIC_JOIN_COLUMN in columns:
                return path_so_far + [f"{current_table}.{TOPIC_JOIN_COLUMN}"]
            if hop >= _MAX_HOPS:
                continue
            for column in columns:
                if column == "id" or not column.endswith("_id"):
                    continue
                candidate_table = column[: -len("_id")]
                if candidate_table in visited or candidate_table not in schema:
                    continue
                if "id" not in schema[candidate_table]:
                    continue  # can't land on it without a PK-shaped column to join to
                visited.add(candidate_table)
                next_frontier.append((
                    candidate_table,
                    path_so_far + [f"{current_table}.{column}", f"{candidate_table}.id"],
                ))
        frontier = next_frontier
        if not frontier:
            break

    return None


def topic_join_status(table_name: str) -> str:
    """Coarse classification for callers that only need clean/no_topic_join,
    not the actual hop chain: "direct" | "<n>_hop" | "none"."""
    path = topic_join_path(table_name)
    if path is None:
        return "none"
    hops = (len(path) - 1) // 2
    return "direct" if hops == 0 else f"{hops}_hop"