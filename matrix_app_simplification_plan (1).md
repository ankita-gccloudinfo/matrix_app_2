# Matrix App — Simplification Plan

## Progress

- [x] **Step 1 — Report generation removed.** Done and delivered in
      `matrix_app_step1_report_removal.zip`. See "Step 1 — completed" notes
      at the end of this document for exactly what changed.
- [ ] **Step 2 — MCP / external-endpoint routes.** Not started.
- [ ] **Step 3 — Router / PDF chat collapsed to DB-only.** Not started.

**Goal:** turn this into a DB-only agent. Every query is assumed to be answerable
from the UP Police social-media MySQL DB (with Qdrant/Neo4j as fallback search).
No PDF chat, no external-endpoint/MCP actions, no report generation.

---

## Final KEEP list (untouched)

- `query_rewriter_node`
- `query_manager_node`
- `check_query_manager_node`
- `keyword_of_post_maker_node` + `keyword_of_post_maker_and_checker_node`
  (this is the EN/Hindi spelling + hashtag + related-entity grounding step —
  it's what makes SQL generation work against `topic_title` (Hindi-only) and
  `input_text` (mixed Hindi/English/Hinglish) columns)
- `go_duck_search_node` + `go_duck_search_verify_node` (unresolved-short-form
  fallback used by the keyword nodes above — keep, it's a dependency of the
  keep-list, not a separate thing)
- `table_selector_node` → `generate_sql_node` → `sql_judge_node` →
  `is_safe_sql_node` → `execute_sql_node`
- `fallback_decider_node` → `content_index_search_node` (Qdrant) →
  `neo4j_search_node` → `fallbackchecker_node`
- `llm_validator_node` → `judge_and_reason_node` → `answer_node` →
  `answer_checker_node`

---

## Final REMOVE list

### 1. Router — collapse to DB-only (this message's decision)

Router stops being an LLM decision. It becomes a straight pass-through to the
DB pipeline. No `pdf_chat` branch exists anywhere anymore.

**In `ollamaagent2.py`:**
- Delete `router_node` entirely (the whole LLM-prompt/backstop-signal-word
  function, ~lines 2887–3025) — or if you'd rather not touch the graph-edge
  shape, replace its body with a one-liner: `return {"route": "database", ...}`
  and drop the LLM call. Cleaner to delete the node and edge outright though.
- Delete `pdf_search_node`, `pdf_answer_node`, `search_pdf()` (~lines 3302–3360).
- Graph wiring: replace
  `_builder.add_conditional_edges("router", _route_decision, {...})`
  with a direct edge `check_query_manager` ← comes straight from
  `query_manager` (once endpoint-check is also removed, see §2) — i.e. delete
  the `router` node from `add_node`, delete `pdf_search`/`pdf_answer` from
  `add_node`, delete the `add_edge("pdf_search", "pdf_answer")` /
  `add_edge("pdf_answer", END)` lines, and delete `_route_decision`.
- Delete State fields: `route`, `pdf_uploaded`, `pdf_filenames`.
- Delete the `is_slash_report` special-case inside `router_node` — moot, the
  whole node is gone.

**In `server.py`:**
- Stop building `pdf_uploaded` / `pdf_filenames` from `chat_request.pdf_scope`
  (~line 167–176) — drop those two lines from the state dict passed into the
  graph.
- Remove `pdf_scope: Optional[List[str]] = None` from `ChatRequest`.
- **Caveat:** the actual PDF-upload HTTP endpoint is mounted by
  `register_common_routes()` from an external `common/routes.py` package that
  is **not included in this zip** (it's a shared library imported from
  elsewhere on the deployment machine). You can't delete that endpoint from
  files in this project. What you *can* do — and what actually matters — is
  stop ever passing `pdf_uploaded=True` into the graph, so even if someone
  uploads a PDF through that external route, the agent will never treat any
  query as PDF-related. If you also want the upload endpoint gone, that's a
  change in the other repo/package, outside this zip's scope.

**Files that become dead once this is done:** `services/pdf_rag.py`,
`services/pdf_embed_worker.py` (only used to build/query the PDF vector
index that `search_pdf()` used) — safe to delete once `pdf_search_node` is gone,
*unless* `register_common_routes` (external package) also imports
`ingest_pdf`/`extract_pages` from `pdf_rag.py` for its own upload route — check
that before deleting the file, since `server.py` line 40 imports those two
functions specifically to inject into the external route.

---

### 2. MCP / external-endpoint routes — full removal

**In `ollamaagent2.py`:**
- Delete `check_and_run_endpoint_routes_node`, `_gather_one_batch`,
  `_execute_and_summarize_reads`, `endpoint_write_executor_node`,
  `endpoint_multi_run_executor_node` (~lines 3027–3300).
- Delete `_endpoint_route_decision` (~line 6006).
- Delete `import mcp_services` (line 910).
- Graph wiring: delete the `add_node` calls for
  `check_and_run_endpoint_routes`, `endpoint_write_executor`,
  `endpoint_multi_run_executor`; delete their `add_conditional_edges`/
  `add_edge` calls; change `add_edge("query_manager", "check_and_run_endpoint_routes")`
  to go straight from `query_manager` to `check_query_manager` (per §1, since
  router is also gone, this is now the sole downstream edge from
  `query_manager`).
- Delete State fields: `endpoint_route_name`, `pending_endpoint_write`,
  `endpoint_write_confirmation`, `endpoint_multi_selection`.
- Update `_graph_entry_decision` (~line 6068): remove the
  `endpoint_write_confirmation` / `endpoint_multi_selection` branches, leaving
  only the `report_selection` check (which itself goes away in §3) — this
  function can likely be deleted entirely once §3 is also done, making
  `query_rewriter` the unconditional entry point.

**Files to delete:** `mcp_services.py`, `external_endpoints.json`,
`endpoint.txt` (the last one looks like a working/debug scratch file — confirm
nothing else reads it before deleting).

**In `server.py`:** remove `endpoint_write_confirmation` and
`endpoint_multi_selection`/`endpoint_multi_selection_query` from `ChatRequest`,
and drop them from the state dict passed to the graph (~line 184 area).

---

### 3. Report generation — full removal ✅ DONE (see completion notes at bottom)

This one touches more places because several nodes check `is_slash_report` /
`_is_report_request` / `_is_freeform_report_request` as a side-condition, not
as a dedicated branch.

**In `ollamaagent2.py`:**
- Delete `report_builder_node` (~lines 4065–4196).
- Delete `_is_report_request`, `_lookup_topic_id_by_title` (if only used by
  report building — verify), `_is_freeform_report_request` (imported from
  `services/dynamic_report_service`, so nothing to delete here beyond the
  import).
- Delete the `from services.dynamic_report_service import (...)` block
  (~line 875).
- Strip the `is_slash_report` checks from: `query_manager_node` (~1738),
  `check_query_manager_node` (~2044), `check_and_run_endpoint_routes_node`
  (gone anyway per §2), `llm_validator_node` (~3633 — this also removes the
  *freeform* report-building block, the "dynamic report picker card" logic
  described around line 1088; this is the one place report logic isn't a
  clean bolt-on, read through this function before cutting), `execute_sql_node`
  (~5463/5509/5512, just simplify `query_intent` logic to drop the
  slash-report special case), `fallbackchecker`'s decision helper (~5951).
- Delete State fields: `report_selection`, `is_slash_report`,
  `needs_clarification` handling can stay (it's used generally, not only by
  reports) — just remove the report-specific paths that set it.
- Graph wiring: delete `add_node("report_builder", ...)`,
  `add_edge("report_builder", END)`, and the `report_builder` branch in
  `_graph_entry_decision`.

**Files/dirs to delete:** `services/dynamic_report_service.py`,
`services/template_reskin_engine.py`, `services/adhoc_generation_service.py`
(check this one isn't reused elsewhere before deleting), `reports/templates/`.
`reports/` output PDFs themselves are just generated data, not code — delete
if you don't need the historical files.

**In `server.py`:** remove the report endpoints —
`/report-builder`, `/api/components`, `/api/reports/generate`,
`/api/report-templates/upload`, `/api/report-templates`,
`/api/reports/generate-from-template`, `/api/reports/generate-freeform`,
`/api/reports/preview-freeform-adhoc`, `/api/reports/confirm-freeform-adhoc`,
`/api/reports/download/{report_id}` (~lines 810–1127), and remove
`report_selection` from `ChatRequest`.

---

## Order of operations (do it in this order to avoid breaking imports mid-way)

1. **Report generation** first (§3) — it's the most tangled, best to untangle
   while the router/endpoint nodes are still there to use as reference points
   for how "optional side-branches" were wired.
2. **MCP/endpoint routes** (§2) — clean, self-contained.
3. **Router / PDF chat** (§1) last — this is the one where you also simplify
   the graph's shape (query_manager → check_query_manager direct edge), so do
   it once the other two conditional branches off `query_manager` are already
   gone.
4. Re-run `graph = _builder.compile()` mentally (or literally, via a quick
   script) after each step — LangGraph will throw immediately if an edge
   points to a deleted node, which is your safety net.

## Verification checklist after all three are done

- [ ] `ollamaagent2.py` graph has exactly these nodes: `query_rewriter`,
      `query_manager`, `check_query_manager`, `keyword_of_post_maker`,
      `keyword_of_post_maker_and_checker`, `go_duck_search`,
      `go_duck_search_verify`, `table_selector`, `generate_sql`, `sql_judge`,
      `is_safe_sql`, `execute_sql`, `fallback_decider`, `content_index_search`,
      `neo4j_search`, `fallbackchecker`, `llm_validator`, `judge_and_reason`,
      `answer`, `answer_checker`.
- [ ] No remaining references to `mcp_services`, `pdf_search`, `pdf_answer`,
      `report_builder`, `router_node` anywhere in `ollamaagent2.py` or `server.py`
      (`grep -rn` for each name should return nothing outside comments).
- [ ] A test query with no DB-relevant content (e.g. general chat) now goes
      through the DB pipeline and returns a graceful "no data found" style
      answer instead of erroring — confirm `answer_node`'s fallback copy
      reads sensibly for that case, since this path is now reachable more
      often than before.
- [ ] A Hindi-language query and an English query for the same topic both
      resolve to SQL that hits `topic_title`/`input_text` with the correct
      Hindi and English `LIKE` variants — confirms `keyword_of_post_maker_and_checker`
      still works untouched.
- [ ] `server.py` starts cleanly with `services/pdf_rag.py` either kept (if the
      external `common/routes.py` still needs `ingest_pdf`/`extract_pages`) or
      removed (if you've also cut the external upload registration).

---

## Step 1 — completed (report generation)

Delivered in `matrix_app_step1_report_removal.zip`.

**`ollamaagent2.py`:**
- Removed the `services.dynamic_report_service` import block.
- Removed `report_id`, `report_pdf_url`, `report_selection`, `is_slash_report`
  from the `State` TypedDict.
- Removed the `/report` slash-command branch from `query_rewriter_node`.
- Removed the `is_slash_report` early-returns from `query_manager_node` and
  `check_query_manager_node`.
- Removed the entire "Path 4: Free-Form Prompt-Driven Report Builder" block
  and the report-picker-card block from `llm_validator_node` (this was the
  cross-cutting piece flagged in the original plan — confirmed and cut).
- Deleted `report_builder_node` in full, and removed it from the graph
  (`add_node`, the `report_selection` branch in `_graph_entry_decision`, and
  its `add_edge(..., END)`).
- Deleted `_is_report_request` and `_lookup_topic_id_by_title` (both fully
  unused once the above was removed).
- Cleaned up 3 call sites that referenced the deleted report helpers:
  `check_and_run_endpoint_routes_node` (report bypass check — harmless to
  leave since this whole node is cut in step 2 anyway, but cleaned for
  consistency), `_classify_sql_query_intent`, and `_execute_decision`.
- **Found and fixed during cleanup, not in the original plan:** `execute_sql_node`
  had an unreachable duplicate `return` statement right after an early
  `return` (pre-existing dead code, unrelated to report logic but it also
  referenced `is_slash_report` so it got cleaned up here) and a stray
  `if is_slash_report: ... else: ...` branch around query-intent
  classification — both simplified to a single unconditional path.
- Deleted the now-orphaned `_resolve_report_date_range` helper (no callers
  left after the picker-card block was removed).

**`server.py`:**
- Removed `/report-builder`, `/api/components`, `/api/reports/generate`,
  `/api/report-templates/upload`, `/api/report-templates`,
  `/api/reports/generate-from-template`, `/api/reports/generate-freeform`,
  `/api/reports/preview-freeform-adhoc`, `/api/reports/confirm-freeform-adhoc`,
  `/api/reports/download/{report_id}`, and the `dynamic_report_service` /
  `adhoc_generation_service` imports that fed them.
- Removed `report_selection` from `ChatRequest` and from the graph state
  dict built in the `/api/chat` handler.

**Files deleted:** `services/dynamic_report_service.py`,
`services/template_reskin_engine.py`, `services/adhoc_generation_service.py`,
`services/db_schema_introspect.py` (only ever referenced by the three files
above), `reports/templates/` (all template + `_pending` subfolders).

**Verification done:** both files still pass `ast.parse` (syntax-valid), and
a static sweep of every `add_node`/`add_edge`/`add_conditional_edges`/
`set_conditional_entry_point` call confirms no dangling references to the
removed `report_builder` node anywhere in the graph wiring. **Not done:** an
actual `import ollamaagent2` / `graph.compile()` smoke test — this sandbox
has no network access to install `langgraph`/`langchain-openai`/etc., so this
still needs a real run in your environment before deploying.
