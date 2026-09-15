LLM_BACKEND = "vllm" # Change to "ollama" to use the Ollama backend

VLLM_BASE_URL = "http://100.98.23.74:2211/v1"
VLLM_MODEL_NAME = ""
VLLM_API_KEY = "EMPTY"  # vLLM ignores this unless it was started with --api-key

OLLAMA_URL = "http://100.100.130.85:11434/api/generate"
OLLAMA_MODEL_NAME = "qwen3-coder:30b"

# ── Dedicated SQL-generation backend ────────────────────────────────────────
# A separate, smaller vLLM instance serving a LoRA fine-tune of
# Qwen2.5-Coder-7B-Instruct (4-bit, via Unsloth) trained specifically on
# MySQL query generation for this schema ("project-qwen26-mysql-lora").
# Used ONLY by generate_sql() below — every other node keeps using the general-purpose backend above (VLLM_BASE_URL / OLLAMA_URL) via call_llm(),since this fine-tune targets SQL synthesis, not general reasoning/NLU.
#
# Set SQL_GEN_USE_FINETUNED_MODEL = False to disable and fall back to the original VLLM_BASE_URL path for generate_sql() without touching any code— useful for A/B testing correctness/latency against test_pipeline_scenarios.py before rolling this out for real traffic.
SQL_GEN_USE_FINETUNED_MODEL = False  # Use the general LLM backend for SQL generation

SQL_VLLM_BASE_URL = "http://100.97.41.98:8000/v1"
SQL_VLLM_MODEL_NAME = "unsloth_Qwen2.5-Coder-7B-Instruct-bnb-4bit__project-qwen26-mysql-lora_1789210014"
SQL_VLLM_API_KEY = "sk-unsloth-310413cb63671ea4a5e4b49a18e5b738"
SQL_VLLM_TIMEOUT_SECONDS = 60

MYSQL_HOST = "100.98.23.74"
MYSQL_PORT = "3306"
MYSQL_USER = "readUser"
MYSQL_PASSWORD = "readUser@123"
MYSQL_DB = "up_police_matrix"

QDRANT_HOST_DEFAULT = "100.100.130.85"
QDRANT_PORT_DEFAULT = 6333
QDRANT_COLLECTION = "content_index"
JINA_API_URL = "https://api.jina.ai/v1/embeddings"
JINA_MODEL = "jina-embeddings-v3"

NEO4J_URI      = "bolt://100.100.130.85:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "YourStrongPassword"


DB_SCHEMA_YAML = """
# ═══════════════════════════════════════════════════════════════════════════
# MATRIX DATABASE SCHEMA — verified against live DDL (Up_police_Matrix_db_structure.sql)
# Written for a 30B-class LLM: every risky pattern has a copy-pasteable
# CORRECT / WRONG pair. Do not reason from column names alone — several
# columns are NOT what their name implies (see the *_master_list rules at
# the bottom).
#
# THIS IS A LIVE, CONSTANTLY-GROWING DATABASE. Never assume a table is
# "small enough to scan" or "too big to touch" based on anything you were
# told once — table sizes change continuously and are not part of this
# schema. Instead, apply these UNIVERSAL rules to every query regardless
# of which table it targets:
#   1. If the user's question gives you a filterable value (district, date,
#      platform, category, topic id, status), always add it as a WHERE
#      condition on an indexed column BEFORE any free-text LIKE search.
#   2. If a column has a FULLTEXT index (see per-table `indexes` below),
#      use MATCH(...) AGAINST(...) for word/phrase search on it instead of
#      LIKE '%term%' — this is correct regardless of table size and is
#      simply the right tool for that index type.
#   3. Always add LIMIT on non-aggregate SELECTs unless the user asked for
#      a specific different number.
#   4. Never pick a table because its name sounds similar to another one —
#      check `never_query_these_tables` below first.
#
# DEFAULT LIMIT: 100 rows unless the user names a different number.
# ═══════════════════════════════════════════════════════════════════════════

database_schema:

  how_to_pick_the_right_table: >
    Route by WHAT the question is actually asking for, not by which table
    name sounds closest to a word in the question:
    - Incident/topic-level overview, category stats, district summary,
      trending list → topic
    - Individual post text, author, sentiment, platform, keyword/mention
      search across posts → analyzed_data
    - Raw post fields not present on analyzed_data, engagement numbers not
      already denormalized, reply-thread anchoring → post_bank
    - Who liked/retweeted/replied to a SPECIFIC post → post_user_interactions, reply
    - Account/profile details, follower counts, verification → post_users
    - Follower/following graph between two accounts → profile_network
    - Ticket/workflow status, dashboard counts → ticket_raised_table (never topic/analyzed_data for ticket status)
    - Zone/Range/Commissionerate rollups of ticket data → thana_matrix (join required, ticket_raised_table has no such columns itself)
    - Pending vs submitted internal reports → district_internal_report (existence-based, not a status column)
    - Category/keyword/hashtag taxonomy and definitions → broad_category, sub_category, keywords, hashtags
    - Monitored account tagging/mention questions → monitor_profiles, then analyzed_data
    - Per-entity stance within a post (not just overall post sentiment) → sentiment_entities
    - Alert history for a topic → viral_alerts

  never_query_these_tables: >
    `primary` — a near-duplicate of analyzed_data's old column layout, not
    used by any live feature. "primary" is also a reserved SQL keyword.
    If table selection is ever tempted to pick this because the name looks
    similar to analyzed_data, that is always wrong — ignore it entirely.

  tables_not_currently_wired_into_any_feature: >
    These tables have complete schemas and real indexes but are not read by
    any documented query path today: user_connections, user_monitoring,
    viral_alert_performance, topic_velocity_snapshots, topic_baseline_metrics,
    discarded_topic. This does not mean they are permanently empty — this is
    a live system and any of them could be populated at any time. It means:
    do not assume a result from them reflects the full picture, and if a
    query against one returns nothing, don't treat that as proof the
    underlying real-world fact is false — it may simply mean this table
    hasn't been backfilled for that record yet. For topic-reference lookups
    specifically: before concluding a unique_topic_id doesn't exist, check
    discarded_topic.discarded_unique_topic_id for a merge redirect to
    discarded_topic.current_unique_topic_id.

  tables:

    # ═══════════════════════════════════════════════════════════════════
    # CORE CONTENT
    # ═══════════════════════════════════════════════════════════════════

    - name: topic
      alias: t
      purpose: >
        One row per incident/storyline (many posts share one topic). Use
        for: incident overviews, category stats, district summaries,
        trending/viral topic lists, ticket/report linkage. Never use for
        individual post text, author, or sentiment of one specific post
        — that is analyzed_data.
      columns:
        id: BIGINT PK
        unique_topic_id: VARCHAR(255) — join key to analyzed_data, ticket_raised_table.topic_unique_id, viral_alerts, news_paper_cutting. NOT declared UNIQUE at the DB level — do not assume exactly one row per id in edge cases.
        topic_title: >
          VARCHAR(255) — Hindi/Devanagari text. Always LIKE '%term%' with the
          Hindi form. Never exact =.
        total_no_of_post: BIGINT — post count, use for virality ranking
        primary_districts: >
          LONGTEXT — JSON array e.g. ["Lucknow","Varanasi"]. First element
          is the primary district.
          CORRECT: JSON_UNQUOTE(JSON_EXTRACT(t.primary_districts,'$[0]')) = 'Lucknow'
          WRONG:   t.primary_districts LIKE '%Lucknow%'  (matches secondary districts too)
        broad_category: >
          LONGTEXT — JSON ARRAY, e.g. ["CRIME","PROTEST"]. NOT a scalar string.
          CORRECT to count: JSON_TABLE(t.broad_category,'$[*]' COLUMNS(cat VARCHAR(100) PATH '$'))
          WRONG: GROUP BY t.broad_category directly — groups by the whole JSON string, not by category.
        sub_category: >
          LONGTEXT — JSON ARRAY, same rule as broad_category above. This is
          NOT the same storage shape as analyzed_data.sub_category (varchar,
          shorter) — treat each table's version independently, same JSON
          array semantics, different column width.
        read_count / unread_count: BIGINT — per-district read tracking
        read_count_hq / unread_count_hq: BIGINT — separate HQ-specific counters, distinct from read_count/unread_count
        ticket_raised_id: VARCHAR(255) — if non-NULL, a ticket exists for this topic. Join: ticket_raised_table.id = CAST(t.ticket_raised_id AS UNSIGNED) — verify type before joining, ticket_raised_id is stored as text.
        ticket_raised_status: VARCHAR(255) — denormalized copy of the ticket's status, avoids a join for simple status checks
        request_internal_report: >
          VARCHAR(255) — '1' means HQ/DGP has requested an internal report
          for this topic. Required condition before checking district_internal_report
          for pending/submitted status.
        pinned: VARCHAR(255) — non-NULL/'true'-like value means this topic is pinned; check actual stored values before filtering, do not assume boolean semantics
        platform_stats: >
          JSON (native JSON type, not text) — pre-aggregated per-platform
          post counts for this topic. If the user asks "platform breakdown
          for this topic," read this column directly instead of joining and
          aggregating analyzed_data — it is already computed and is the
          correct source of truth for per-topic breakdowns.
        sentiment_stats: JSON (native) — pre-aggregated sentiment counts for this topic. Prefer this over re-aggregating analyzed_data when the question is scoped to one topic.
        emotional_stats: JSON (native) — pre-aggregated emotion breakdown for this topic. Same rule as above.
        dgp_remark / headquarter_remark / range_remark / zone_remark: LONGTEXT — free-text remarks entered by each command level; only surface when the user explicitly asks for remarks/comments on a topic
        topic_status: VARCHAR(255) — workflow status of the topic itself (distinct from ticket_raised_status)
        created_at: DATETIME INDEXED
        updated_at: DATETIME INDEXED
      indexes: [unique_topic_id, created_at, updated_at, ticket_raised_id]

    - name: analyzed_data
      alias: a
      purpose: >
        One row per individual social media post, AI-enriched. Use for: post
        text, author, sentiment, district of a post, mention/tag search,
        keyword search across posts. Do NOT use for engagement counts beyond
        what's denormalized here — post_bank_likes/retweets/etc. below ARE
        available on this table already, so you usually do not need to join
        post_bank at all unless you need raw post_bank-only fields.
      columns:
        id: INT PK
        dump_table_id: INT UNIQUE — FK to post_bank.id (1:1, this table is an enrichment layer over one post_bank row)
        unique_topic_id: VARCHAR(255) INDEXED — join key to topic.unique_topic_id
        topic_id: >
          VARCHAR(100) — a SEPARATE column from unique_topic_id, also
          indexed. Do not confuse the two. Prefer unique_topic_id for
          joining to topic; only use topic_id if a query or prior turn
          specifically resolved that value.
        topic_title: TEXT — Hindi/Devanagari, same LIKE rules as topic.topic_title
        input_text: >
          TEXT — raw/original post text, MIXED language (Hindi/English/Hinglish
          in the same row). Search both language forms OR'd together.
        processed_text / enhanced_text: TEXT — cleaned/AI-processed variants of input_text; use input_text by default unless the user specifically wants the processed version
        sentiment_label: VARCHAR(20) INDEXED — Positive / Neutral / Negative
        sentiment_confidence: FLOAT
        emotional_primary_emotion: VARCHAR(255) — one of the supported emotions; do not invent additional emotion categories beyond what's actually stored
        emotional_secondary_emotion: VARCHAR(255)
        emotional_intensity: FLOAT
        broad_category: >
          VARCHAR(255) — shorter storage than topic.broad_category. May still
          hold a JSON-array-formatted string; check the actual value shape
          before assuming scalar vs array — do not assume identical semantics
          to topic.broad_category just because the name matches.
        sub_category: >
          VARCHAR(255) — JSON array string e.g. '["HATE SPEECH","TRAFFIC"]'.
          Never GROUP BY directly:
          CORRECT: JSON_TABLE(a.sub_category,'$[*]' COLUMNS(cat VARCHAR(100) PATH '$'))
          or one LIKE per category: a.sub_category LIKE '%MURDER%'
        primary_district: >
          VARCHAR(2550) — but functionally a JSON ARRAY (a live functional
          index confirms this shape). Same rule as topic.primary_districts:
          CORRECT: JSON_UNQUOTE(JSON_EXTRACT(a.primary_district,'$[0]')) = 'Lucknow'
          WRONG:   a.primary_district LIKE '%Lucknow%'
          A functional index exists for the CORRECT form combined with
          post_bank_core_source + post_bank_post_timestamp — use all three
          together when the question supports it.
        primary_thana: VARCHAR(2550) — may be NULL, use only when specifically asked
        primary_location: VARCHAR(2550) — sub-district; use only if district filter doesn't resolve
        mention_ids_extracted: >
          TEXT INDEXED — for profile-tagging queries. Use with the
          monitor_profiles join pattern below. Never search input_text for
          tag/mention questions.
        post_bank_post_url: TEXT
        post_bank_core_source: >
          VARCHAR(255) INDEXED — specific platform (TWITTER, facebook,
          whatsapp, instagram, YouTube, News_Rss_Feed, Google_News). Use this
          for platform filtering, never source_type.
        source_type: VARCHAR(50) — broad category (social_media/news/whatsapp). Never filter specific platforms with this.
        post_bank_author_name: VARCHAR(255) INDEXED
        post_bank_author_username: VARCHAR(255) INDEXED
        post_bank_likes / post_bank_retweets / post_bank_comments / post_bank_bookmarks: INT — engagement already denormalized here, no post_bank join needed for these
        post_bank_views: BIGINT
        post_bank_post_date: DATE INDEXED — participates in the most composite indexes, prefer it for date filtering
        post_bank_post_time: TIME INDEXED
        post_bank_post_timestamp: DATETIME INDEXED
        created_at / updated_at: DATETIME
        read_status: VARCHAR(20) DEFAULT 'UNREAD' — per-district read tracking
        read_status_hq: VARCHAR(20) DEFAULT 'UNREAD' — separate HQ-level read tracking, do not conflate with read_status
        caste_names / religion_names: VARCHAR(255) — sensitive extracted entities; surface only if the user's question is specifically about caste/religion angle of an incident
        person_names / organisation_names / location_names / district_names / thana_names: TEXT — extracted named entities, JSON-array-like text; useful for "who/what/where is mentioned" questions without joining sentiment_entities
        keywords_cloud: TEXT — JSON array of extracted keywords for this post
      indexes: >
        unique_topic_id, (core_source, post_date, id), (author_username, post_date),
        (sentiment_label, post_date), (unique_topic_id, core_source, reply_status),
        post_bank_post_timestamp, (topic_id, core_source),
        functional index on JSON_EXTRACT(primary_district,'$[0]') combined with
        (core_source, post_timestamp) — see primary_district above
      join_key: analyzed_data.dump_table_id = post_bank.id  (NOT analyzed_data.id — these are different values entirely)

    - name: post_bank
      alias: pb
      purpose: >
        Raw canonical post record. Use for: engagement numbers if NOT
        already covered by analyzed_data's post_bank_* denormalized columns,
        reply threading, is_reply checks. For almost all "show me posts
        about X" questions, analyzed_data already has everything needed —
        do not join post_bank unless the question needs a column that ONLY
        exists here.
      text_search_rule: >
        post_title and post_snippet HAVE FULLTEXT INDEXES. For any word/
        phrase search on these two specific columns, use
        MATCH(post_title) AGAINST('term' IN NATURAL LANGUAGE MODE) — this
        is the correct tool for a FULLTEXT-indexed column and should be used
        regardless of how many rows currently exist.
        CORRECT: WHERE MATCH(post_title) AGAINST('bribery' IN NATURAL LANGUAGE MODE)
        WRONG:   WHERE post_title LIKE '%bribery%'
        Caveat: default FULLTEXT parsing is word-based and reliable for
        English; for Hindi/Devanagari text search, prefer analyzed_data.input_text
        instead — post_bank's FULLTEXT index is not guaranteed to tokenize
        Devanagari script usefully with the default parser.
      columns:
        id: INT PK — referenced by reply.post_bank_id, post_user_interactions.post_bank_id, engagement_metric.post_bank_id
        post_title: TEXT — FULLTEXT INDEXED, see text_search_rule above
        post_snippet: TEXT — FULLTEXT INDEXED, see text_search_rule above
        post_url: TEXT INDEXED
        core_source: VARCHAR(255) INDEXED
        post_date: DATE INDEXED — prefer for date-range filters
        post_timestamp: DATETIME INDEXED
        author_name: VARCHAR(255) INDEXED
        author_username: VARCHAR(255)
        likes / retweets / comments: INT
        views: BIGINT
        bookmarks: INT
        is_reply: TINYINT(1) — boolean, 0 or 1
        in_reply_to_username: VARCHAR(255)
        analysis_status: VARCHAR(50) DEFAULT 'NOT_ANALYZED' — whether this raw post has been through the analyzed_data enrichment pipeline yet
        ingestion_at: DATETIME INDEXED
      indexes: [core_source, post_timestamp, post_date, author_name, post_url, post_id, ingestion_at, FULLTEXT(post_snippet), FULLTEXT(post_title)]

    # ═══════════════════════════════════════════════════════════════════
    # ACTOR TABLES
    # ═══════════════════════════════════════════════════════════════════

    - name: post_users
      alias: pu
      purpose: Social media account profiles. Use for account details, follower counts, verification, bio.
      columns:
        id: INT PK
        platform: VARCHAR(20) — twitter, facebook, instagram, youtube
        platform_user_id: VARCHAR(100) — combined with platform is the TRUE unique key
        username: VARCHAR(255) — NOT unique alone; the same handle text can exist across different platforms. Always filter by (platform, username) together when precision matters, never username alone if the platform isn't already fixed by context.
        display_name: VARCHAR(255)
        followers_count / following_count: BIGINT
        posts_count: INT
        total_engagement: BIGINT
        is_verified / is_business / is_private: TINYINT(1)
        is_blue_verified: TINYINT(1) — Twitter-specific, separate from is_verified
        account_status: VARCHAR(50)
        bio_description: TEXT
        location: VARCHAR(255)
        country_code / state: VARCHAR(100) — geo-normalized fields, more reliable than free-text location for filtering
        normalization_status: VARCHAR(20) DEFAULT 'pending' — whether location/other normalization has completed for this row; a 'pending' row may have unreliable country_code/state
      indexes: [UNIQUE(platform, platform_user_id), username, is_verified, is_business, account_status]

    - name: profile_network
      alias: pn
      purpose: >
        Raw follower/following edges between any two post_users accounts.
        Use for: who follows X, who does X follow, connection between two
        specific accounts. Prefer this table over user_connections (see
        tables_not_currently_wired_into_any_feature) for general
        follower-graph questions.
      columns:
        user_id: INT FK → post_users.id — the account being followed
        follower_id: INT FK → post_users.id — the account that follows
        relationship_type: VARCHAR(20) — FOLLOWER or FOLLOWING
        platform: VARCHAR(20)
        status: VARCHAR(20)
      indexes: [UNIQUE(user_id,follower_id,platform), (user_id,relationship_type), (follower_id,relationship_type)]

    # ═══════════════════════════════════════════════════════════════════
    # ENGAGEMENT TABLES (join to post_bank.id)
    # ═══════════════════════════════════════════════════════════════════

    - name: post_user_interactions
      alias: pui
      purpose: >
        Individual LIKE/RETWEET/QUOTE/REPLY/BOOKMARK actions on a post.
        This is per-interaction detail, not every post will have rows here
        — treat a missing row as "no interaction-level detail captured,"
        not as "nobody interacted."
      columns:
        post_bank_id: INT FK → post_bank.id
        post_user_id: INT FK → post_users.id
        interaction_type: VARCHAR(20) — 'retweet' | 'like' (lowercase, per column comment)
        analyzed_data_id: BIGINT — direct shortcut ref to analyzed_data.id, avoids the post_bank_id round-trip when you already have analyzed_data context

    - name: reply
      alias: rp
      purpose: Individual replies/comments on posts. Use for reply content, reply author details, reply engagement, conversation threads.
      columns:
        post_bank_id: INT FK → post_bank.id — original post
        post_user_id: INT FK → post_users.id — ORIGINAL POST author being replied to, NOT the replier
        analyzed_data_id: INT — shortcut ref to analyzed_data.id for the original post
        reply_text: TEXT — mixed language, same dual-language LIKE rule
        reply_author_username / reply_author_display_name: VARCHAR(255) — the actual replier's identity
        reply_author_followers_count: INT
        reply_author_is_verified: TINYINT(1)
        reply_created_at: DATETIME
        reply_like_count / reply_retweet_count / reply_quote_count / reply_bookmark_count: INT
        conversation_id: VARCHAR(255)
      note: Filter on post_bank_id (or another indexed column) before running any reply_text LIKE search.

    - name: engagement_metric
      alias: em
      purpose: Pre-aggregated post engagement totals, including platform-specific breakdowns (Facebook reactions, Instagram saves, etc). Use when only overall numbers are needed, faster than aggregating interactions.
      columns:
        post_bank_id: INT FK → post_bank.id
        platform_type: VARCHAR(20)
        likes / comments / shares: INT
        views / reach: BIGINT
        engagement_rate: FLOAT
        fb_reactions_love / fb_reactions_haha / fb_reactions_wow / fb_reactions_sad / fb_reactions_angry / fb_reactions_total: INT — Facebook-specific, only populated for Facebook posts
        ig_saved / ig_engagement / ig_profile_views: INT — Instagram-specific

    # ═══════════════════════════════════════════════════════════════════
    # TAXONOMY / LOOKUP
    # ═══════════════════════════════════════════════════════════════════

    - name: broad_category
      columns:
        id: BIGINT PK
        broad_category: VARCHAR(255) UNIQUE
        priority: BIGINT — display order only, not severity

    - name: sub_category
      columns:
        id: BIGINT PK
        sub_category: VARCHAR(255)
        priority: VARCHAR(255) — HIGH/MEDIUM/LOW, compare case-insensitively
        classify_priority: INT — a SEPARATE ranking column from classify_sub_priority below; do not confuse the two
        classify_sub_priority: INT — ONLY this one resolves the winning sub-category when several are tagged (lowest wins)
        hint: TEXT — free-text disambiguation hint for this category
        broad_category_id: BIGINT FK → broad_category.id

    - name: keywords
      columns:
        id: BIGINT PK
        english_keyword / hindi_keyword / hinglish_keyword: TEXT NOT NULL
        broad_category_name / sub_category_name: VARCHAR(255) — denormalized names, avoids a join if only the name text is needed
        broad_category_id: BIGINT FK → broad_category.id
        sub_category_id: BIGINT FK → sub_category.id

    - name: hashtags
      columns:
        id: BIGINT PK
        hashtag_keyword / hashtag_hindi_keyword: VARCHAR(255)
        hastag_keyword_category: VARCHAR(255) — misspelled as stored, must use this exact name
        priority: VARCHAR(255)
        vertical: VARCHAR(255)

    - name: category_handle_master
      columns:
        id: BIGINT PK
        category_name / handle_name / name / profile_url: TEXT

    - name: monitor_profiles
      alias: mp
      purpose: Registry of monitored accounts. First step for any tag/mention query.
      columns:
        id: BIGINT PK
        category: >
          VARCHAR(255) — ALWAYS English (e.g. 'DGP UP', 'STF'). Translate
          Hindi input to English before filtering. Closed-set field, no
          free-text search.
        platform: VARCHAR(255)
        user_name: VARCHAR(255) UNIQUE — the handle for mention matching, strip leading '@'
        process_status: VARCHAR(45) — 'SKIP' marks official/verified handles that should never be treated as suspicious/monitored-for-violation accounts; used to build an exclusion list
        ref_name: TEXT — reference field, surface only if the user's question is specifically about it
        profile_link: VARCHAR — Official profile URL/link of the monitored account
      critical_join_pattern: >
        JOIN monitor_profiles mp
          ON LOWER(a.mention_ids_extracted)
          LIKE CONCAT('%', LOWER(TRIM(LEADING '@' FROM mp.user_name)), '%')
        Never join mp.id to analyzed_data — no such FK exists.

    - name: thana_matrix
      alias: tm
      purpose: District → Range → Commissionerate → Zone → Thana lookup.
      columns: {id: BIGINT PK, district: VARCHAR(255), dist_range: VARCHAR(255), commissionarate: VARCHAR(255), zone: VARCHAR(255), thana: VARCHAR(255)}

    - name: recycle_search
      purpose: Curated keyword tag → search-term expansion, used by keyword_of_post_maker.
      columns: {id: BIGINT PK, query_tag: VARCHAR(500) INDEXED, searched_term: TEXT, total_posts_fetched: INT, last_post_datetime: DATETIME}

    - name: discarded_topic
      purpose: >
        Tracks topic merges: when a topic gets folded into another, this
        table records the redirect. Not currently checked by any fallback
        path automatically — check it manually when a topic reference
        resolves to nothing.
      columns:
        current_unique_topic_id: VARCHAR(255) — the surviving topic to redirect to
        discarded_unique_topic_id: VARCHAR(255) — the old/merged-away topic id
        dis_topic_title: VARCHAR(255) — title the discarded topic had
      recommended_use: >
        If a resolved_topic_reference or a user-supplied unique_topic_id
        returns 0 rows from topic/analyzed_data, check:
        SELECT current_unique_topic_id FROM discarded_topic
        WHERE discarded_unique_topic_id = '<the_id>'
        before concluding the topic doesn't exist — it may have been merged.

    # ═══════════════════════════════════════════════════════════════════
    # WORKFLOW / TICKETS
    # ═══════════════════════════════════════════════════════════════════

    - name: district_internal_report
      alias: dir
      purpose: >
        One row per submitted internal report. Presence of a row for a
        unique_topic_id = report submitted. Absence = pending (only for
        topics where topic.request_internal_report = '1').
      columns:
        unique_topic_id: VARCHAR(255) — join key to topic
        district / thana: VARCHAR(255)
        crime_type: VARCHAR(255)
        virality: VARCHAR(255)
        fir: VARCHAR(10) — likely 'YES'/'NO', verify actual stored values before filtering
        fir_date / fir_no: VARCHAR(255)
        arrest_status: VARCHAR(255)
        victim_name / victim_age / victim_religion / victim_cast: >
          sensitive personal fields — surface only when the user's question
          is specifically an official case-detail lookup, never in aggregate
          dashboards or general summaries
        accused_names / accused_arrested / accused_known: VARCHAR(255)
        cause_of_death: LONGTEXT
        dgp_remark / headquater_remark / range_remark / zone_remark: LONGTEXT
      pending_report_pattern: >
        topic.request_internal_report = '1'
        AND NOT EXISTS (SELECT 1 FROM district_internal_report dir
                         WHERE dir.unique_topic_id = topic.unique_topic_id)

    - name: ticket_raised_table
      alias: trt
      purpose: >
        Workflow tickets. Use for ALL ticket dashboard metrics. Never derive
        ticket status from topic or analyzed_data — this table is
        authoritative. It has many more columns than are relevant to
        reporting queries — the ones below are the ones that matter, the
        rest are UI/attachment/history bookkeeping fields.
      status_mapping:
        DISCARDED: discard_ticket = 1  (bit(1) column — see critical_gotcha below)
        ASSIGNED: step_status = 'TICKET_ASSIGNED' AND discard_ticket != 1
        IN_PROGRESS: step_status = 'IN_PROGRESS' AND discard_ticket != 1
        RESOLVED: step_status = 'VERIFIED' AND discard_ticket != 1
        CLOSED: step_status = 'CLOSED_FOR_VERIFICATION' AND discard_ticket != 1
      critical_gotcha_discard_ticket: >
        discard_ticket is BIT(1), not varchar or int.
        CORRECT: WHERE discard_ticket = 1   or   WHERE discard_ticket = b'1'
        WRONG:   WHERE discard_ticket = '1'  (string comparison against a bit column is unreliable)
      critical_gotcha_date_of_assignee: >
        date_of_assignee is VARCHAR(255) in 'DD/MM/YYYY HH:mm:ss' text format.
        A functional index EXISTS but only matches this EXACT expression:
        idx_func_date ON (STR_TO_DATE(SUBSTR(date_of_assignee,1,10),'%d/%m/%Y'))
        CORRECT (uses the index): WHERE STR_TO_DATE(SUBSTR(date_of_assignee,1,10),'%d/%m/%Y') = '2026-09-01'
        WRONG (ignores the index):
          WHERE STR_TO_DATE(date_of_assignee,'%d/%m/%Y %H:%i:%s') >= '2026-09-01'
        A native column date_of_assignee_ts (DATETIME(6)) also exists and is
        cleaner for anything beyond exact-date matching — prefer it over
        string-parsing when the comparison isn't a simple date equality.
      critical_gotcha_numeric_columns_are_text: >
        likes, retweets, views, quotes, plays, profile_follower,
        profile_following, read_post_count, total_number_of_post,
        unread_post_count are ALL varchar(255), not numeric.
        CORRECT to sort/aggregate: ORDER BY CAST(views AS UNSIGNED) DESC
        WRONG: ORDER BY views DESC   (sorts "9" after "10" and "2" — lexicographic, not numeric)
      critical_gotcha_column_name: >
        This table's topic join column is named topic_unique_id — reversed
        word order from topic.unique_topic_id. Do not assume the same name
        pattern as other tables.
      columns:
        sub_category: LONGTEXT — JSON array, same counting rule as topic.sub_category (JSON_TABLE, never GROUP BY directly)
        broad_category: LONGTEXT — JSON array
        complaint_assigned_to_district: >
          LONGTEXT, may be comma-separated. Always take the first element:
          TRIM(SUBSTRING_INDEX(complaint_assigned_to_district, ',', 1))
          This is the canonical district column — never use the plain
          `district` column for ticket dashboard district analysis.
        verified_status / date_of_verified_ticket: verification workflow fields, distinct from step_status='VERIFIED'
        ticket_re_open_status: BIT(1) — a reopen workflow exists; use = 1, same bit gotcha as discard_ticket
      ticket_priority_derivation: >
        Not a stored column. Derive from the winning tagged sub_category:
        (SELECT sc.priority FROM JSON_TABLE(trt.sub_category,'$[*]'
          COLUMNS(cat VARCHAR(100) PATH '$')) jt
         JOIN sub_category sc ON sc.sub_category = jt.cat
         ORDER BY sc.classify_sub_priority ASC LIMIT 1) AS ticket_priority

    # ═══════════════════════════════════════════════════════════════════
    # VIRAL INTELLIGENCE (join on unique_topic_id)
    # ═══════════════════════════════════════════════════════════════════

    - name: viral_alerts
      alias: va
      purpose: Alert history — many rows per topic over time, as alerts fire.
      columns:
        unique_topic_id: VARCHAR(255) INDEXED
        alert_level: VARCHAR(20) — LOW/MEDIUM/HIGH/CRITICAL
        viral_score: FLOAT
        posts_5min / posts_10min / posts_1hour: INT
        telegram_sent: INT — 0/1, NOT boolean type but used as one
        created_at: DATETIME INDEXED

    - name: viral_alert_performance
      purpose: >
        One summary row per topic — first alert, peak alert, whether it was
        truly viral. See tables_not_currently_wired_into_any_feature above.
      columns:
        unique_topic_id: VARCHAR(255) UNIQUE
        first_alert_level / peak_alert_level: VARCHAR(20)
        first_alert_time / peak_alert_time: DATETIME
        time_to_peak_minutes: INT
        was_truly_viral: TINYINT(1)

    - name: topic_velocity_snapshots
      purpose: >
        Time-series snapshots of a topic's posting velocity. See
        tables_not_currently_wired_into_any_feature above.
      columns:
        unique_topic_id: VARCHAR(255)
        snapshot_time: DATETIME
        posts_5min / posts_10min / posts_15min / posts_30min / posts_1hour: INT
        viral_score: FLOAT

    - name: topic_baseline_metrics
      purpose: >
        Expected/typical posting-volume baseline per topic per day. See
        tables_not_currently_wired_into_any_feature above.
      columns:
        unique_topic_id: VARCHAR(255)
        baseline_date: DATE
        avg_posts_per_hour / peak_posts_per_hour: FLOAT
        total_posts_7days: INT

    - name: news_paper_cutting
      alias: npc
      columns: {unique_topic_id: VARCHAR(255), news_paper_name: VARCHAR(255), district: VARCHAR(255), eidition_name: VARCHAR(255), eidition_city: VARCHAR(255), published_date: DATETIME(6), published_by: VARCHAR(255)}

    - name: sentiment_entities
      alias: se
      purpose: >
        Named entities per post with individual stance — finer-grained than
        analyzed_data.sentiment_label. No unique_topic_id column — must
        one-hop through analyzed_data.
      columns:
        analyzed_data_id: INT FK → analyzed_data.id
        entity_name: VARCHAR(500)
        entity_type: VARCHAR(50) — PERSON/ORGANIZATION/LOCATION
        stance: VARCHAR(20)
        confidence: FLOAT
      join_pattern: >
        se.analyzed_data_id = a.id, then filter/join on a.unique_topic_id.
        Never filter sentiment_entities by unique_topic_id directly — no such column exists.

  # ─────────────────────────────────────────────────────────────────────
  # RELATIONSHIPS & GLOBAL RULES
  # ─────────────────────────────────────────────────────────────────────

  relationships:

    content_join_key: >
      topic.unique_topic_id = analyzed_data.unique_topic_id
      analyzed_data.dump_table_id = post_bank.id  (NEVER analyzed_data.id = post_bank.id)

    engagement_hub: >
      post_bank.id is central. reply.post_bank_id, post_user_interactions.post_bank_id,
      engagement_metric.post_bank_id all reference it. Never join engagement
      tables directly to analyzed_data — go through post_bank.id, or use the
      analyzed_data_id shortcut columns already present on reply and
      post_user_interactions when you already have an analyzed_data row.

    actor_hub: >
      post_users.id referenced by post_user_interactions.post_user_id,
      reply.post_user_id (original author, NOT the replier — replier fields
      are reply.reply_author_*), profile_network.user_id/follower_id.

    monitor_profile_tagging: >
      SELECT a.* FROM analyzed_data a
      JOIN monitor_profiles mp ON LOWER(a.mention_ids_extracted)
        LIKE CONCAT('%', LOWER(TRIM(LEADING '@' FROM mp.user_name)), '%')
      WHERE mp.category = 'DGP UP'
      Never join on mp.id, never search input_text for tag questions.

    junk_topic_exclusion: >
      Always exclude: topic_title <> 'असाइन नहीं की गई पोस्ट'
      AND topic_title <> 'NOT RELEVANT POST'
      Apply on both topic.topic_title and analyzed_data.topic_title.

    json_array_columns_master_list: >
      These columns are JSON ARRAYS regardless of their declared VARCHAR/TEXT
      type — never treat as scalar, never GROUP BY directly, always
      JSON_TABLE or per-value LIKE:
      topic.primary_districts, topic.broad_category, topic.sub_category,
      analyzed_data.primary_district, analyzed_data.sub_category,
      ticket_raised_table.sub_category, ticket_raised_table.broad_category

    bit_columns_master_list: >
      These are BIT(1), compare with = 1 or = b'1', NEVER = '1':
      ticket_raised_table.discard_ticket, ticket_raised_table.ticket_re_open_status

    text_that_is_actually_numeric_master_list: >
      Cast before sorting/aggregating — these are varchar despite holding numbers:
      ticket_raised_table.likes/retweets/views/quotes/plays/profile_follower/
      profile_following/read_post_count/total_number_of_post/unread_post_count

    topic_district_rule: >
      JSON_UNQUOTE(JSON_EXTRACT(t.primary_districts,'$[0]')) = 'Lucknow'  -- correct
      t.primary_districts LIKE '%Lucknow%'  -- wrong, matches secondary districts

    no_district_filter_tables: >
      monitor_profiles, post_users, profile_network, keywords, hashtags,
      broad_category, sub_category, category_handle_master, recycle_search

    alias_convention: >
      t=topic, a=analyzed_data, pb=post_bank, pu=post_users, pn=profile_network,
      pui=post_user_interactions, rp=reply, em=engagement_metric,
      bc=broad_category, sc=sub_category, kw=keywords, ht=hashtags,
      chm=category_handle_master, mp=monitor_profiles, dir=district_internal_report,
      trt=ticket_raised_table, tm=thana_matrix, va=viral_alerts,
      npc=news_paper_cutting, se=sentiment_entities
"""


import os
import re
import json
import uuid
import difflib
import asyncio
import logging
import requests
import mysql.connector
from datetime import datetime, timedelta
from typing import TypedDict, List, Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END
from qdrant_client import QdrantClient, models as qdrant_models
from neo4j import GraphDatabase as _Neo4jDriver
import embedder
from services.location import UP_DISTRICTS as _UP_DISTRICTS

# Flat list of district name strings, for the voice-entity grounding pool
# below (_fetch_voice_grounding_candidates) — UP_DISTRICTS itself is a list
# of {"name", "lat", "lng"} dicts used elsewhere for map coordinates.
UP_DISTRICT_NAMES = [d["name"] for d in _UP_DISTRICTS]
# Report generation removed — services/dynamic_report_service.py,
# services/template_reskin_engine.py, services/adhoc_generation_service.py,
# and services/db_schema_introspect.py are no longer used by this file.

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Matches a message that is ONLY a greeting (optionally with trailing punctuation) —
# used by query_rewriter_node to short-circuit small talk before it ever reaches the
# SQL pipeline. Deliberately anchored ^...$ so "hi, show me topics in Lucknow" does
# NOT match and still goes through the normal DB flow.
GREETING_PATTERN = re.compile(
    r"^(hi+|he+llo+|he+y+|heya|yo+|hola|namaste|namaskar|namaskaar|greetings|"
    r"good\s*(morning|afternoon|evening|night)|"
    r"salaam|assalamualaikum|नमस्ते|नमस्कार|हाय|हैलो)[\s!.,?~]*$",
    re.IGNORECASE,
)

# =========================
# LANGUAGE MATCHING (fixes: user-facing messages switching to a different
# language than the one the user typed in — was happening because several
# nodes below used a hardcoded string in one fixed language, or asked an LLM
# to write a message without ever telling it which language to use. Only
# answer_node had a language instruction before this change.)
# =========================
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

def _query_language(text: str) -> str:
    """Cheap, deterministic language cue for a short user message — used only
    to pick between a fixed English/Hindi phrase (no LLM call needed) for the
    small handful of instant, non-LLM reply paths below (greeting, "no" reply,
    last-resort confirmation fallback). Devanagari script present -> 'hi',
    else 'en'. Hinglish typed in Latin script is treated as 'en', same
    convention answer_node already uses ("if the user asked in Hindi, reply
    in Hindi, otherwise English") — this just makes that same call in the
    places that previously had no language check at all.
    Real LLM-authored messages (grounded clarifications, the
    fallback-exhausted message) instead get an explicit
    "match the user's language" instruction in their own prompt — see
    _LANGUAGE_MATCH_INSTRUCTION below — so they aren't limited to this
    two-way split."""
    return "hi" if _DEVANAGARI_RE.search(text or "") else "en"

# Dropped into any LLM prompt that produces user-facing text, so every such
# message — not just answer_node's — matches what the user actually typed
# (English, Hindi, or Hinglish) instead of defaulting to whatever language
# the prompt happens to be written in.
_LANGUAGE_MATCH_INSTRUCTION = (
    "IMPORTANT: Write your reply in the SAME language the user used in their "
    "message below (English, Hindi, or Hinglish) — match it exactly, do not "
    "translate to a different language."
)

GREETING_REPLIES = {
    "en": (
        "Hello! I'm the UP Police Matrix assistant. Ask me about topics, posts, "
        "sentiment, districts, tickets, or reports, and I'll pull the answer from "
        "the monitoring database."
    ),
    "hi": (
        "नमस्ते! मैं UP Police Matrix सहायक हूँ। मुझसे टॉपिक्स, पोस्ट्स, सेंटिमेंट, "
        "जिलों, टिकटों या रिपोर्ट्स के बारे में पूछें, और मैं मॉनिटरिंग डेटाबेस से जवाब लाऊंगा।"
    ),
}

# Safety-net template for the fallback_exhausted clarification below, used only
# if the LLM call to write it fails/times out (call_llm returns ""). Keeps the
# old always-Hindi text as one of two fixed options instead of the only option.
CLARIFICATION_FALLBACK = {
    "en": (
        "I found some loosely related data for your question, but I need more "
        "precise information:\n\n**Related data found:**\n{preview}\n\n"
        "Could you tell me exactly which specific person, incident, or detail "
        "you're asking about?"
    ),
    "hi": (
        "मैंने आपके प्रश्न के लिए कुछ मिलते-जुलते डेटा ढूंढे हैं, लेकिन मुझे सटीक जानकारी चाहिए:\n\n"
        "**मिली-जुली जानकारी:**\n{preview}\n\n"
        "क्या आप बता सकते हैं कि आप किस विशेष व्यक्ति, घटना या जानकारी के बारे में पूछ रहे हैं?"
    ),
}

NEGATIVE_CLARIFICATION = {
    "en": 'No problem — could you say exactly what "{term}" refers to?',
    "hi": 'कोई बात नहीं — क्या आप बता सकते हैं कि "{term}" का सटीक अर्थ क्या है?',
}

CANDIDATE_CONFIRM_FALLBACK = {
    "en": 'Are you asking about "{candidate}"? (yes/no)',
    "hi": 'क्या आप "{candidate}" के बारे में पूछ रहे हैं? (हाँ/नहीं)',
}

today = datetime.now().strftime("%Y-%m-%d")
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
now_iso = datetime.now().isoformat()

# Override config from environment if available
QDRANT_HOST = os.environ.get("QDRANT_HOST", QDRANT_HOST_DEFAULT)
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", str(QDRANT_PORT_DEFAULT)))
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")

# Dedicated SQL-generation backend (fine-tuned Qwen2.5-Coder-7B MySQL LoRA) —
# see declarations near the top of the file for what each of these does.
SQL_GEN_USE_FINETUNED_MODEL = os.environ.get(
    "SQL_GEN_USE_FINETUNED_MODEL", str(SQL_GEN_USE_FINETUNED_MODEL)
).lower() == "true"
SQL_VLLM_BASE_URL = os.environ.get("SQL_VLLM_BASE_URL", SQL_VLLM_BASE_URL)
SQL_VLLM_MODEL_NAME = os.environ.get("SQL_VLLM_MODEL_NAME", SQL_VLLM_MODEL_NAME)
SQL_VLLM_API_KEY = os.environ.get("SQL_VLLM_API_KEY", SQL_VLLM_API_KEY)
SQL_VLLM_TIMEOUT_SECONDS = int(os.environ.get("SQL_VLLM_TIMEOUT_SECONDS", str(SQL_VLLM_TIMEOUT_SECONDS)))


# LangChain LLM client — points at the same vLLM OpenAI-compatible endpoint
llm = ChatOpenAI(
    model=VLLM_MODEL_NAME,
    base_url=VLLM_BASE_URL,
    api_key=VLLM_API_KEY,
    temperature=0,
)

# Qdrant client for content_index_search fallback
qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=120, check_compatibility=False)

# Neo4j driver — used in neo4j_search_node after Qdrant finds topic_ids
_neo4j_driver = None
try:
    _neo4j_driver = _Neo4jDriver.driver(
        NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
    )
    print("✅ Neo4j driver connected:", NEO4J_URI)
except Exception as _neo4j_err:
    print(f"⚠️ Neo4j driver not available ({_neo4j_err}) — neo4j_search_node will be skipped.")


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


LLM_CALL_TIMEOUT_SECONDS = int(os.environ.get("LLM_CALL_TIMEOUT_SECONDS", "120"))

async def call_llm(prompt: str) -> str:
    """Invoke the configured LLM backend and return clean text, stripping any <think> blocks.
    Wrapped in a hard timeout so a stalled backend (e.g. vLLM hanging on a
    request) fails fast and falls back cleanly instead of blocking the
    request indefinitely — generate_ollama already has its own timeout=120
    on the requests.post call, but the vLLM path via llm.ainvoke() had none,
    so this covers both backends uniformly."""
    try:
        if LLM_BACKEND.lower() == "ollama":
            text = await asyncio.wait_for(
                asyncio.to_thread(generate_ollama, prompt), timeout=LLM_CALL_TIMEOUT_SECONDS
            )
        else:
            response = await asyncio.wait_for(
                llm.ainvoke([HumanMessage(content=prompt)]), timeout=LLM_CALL_TIMEOUT_SECONDS
            )
            text = response.content

        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        return text.strip()
    except asyncio.TimeoutError:
        print(f"LLM Error ({LLM_BACKEND}): timed out after {LLM_CALL_TIMEOUT_SECONDS}s")
        return ""
    except Exception as e:
        print(f"LLM Error ({LLM_BACKEND}):", e)
        return ""


def clean_json_string(raw: str) -> str:
    """Strip a ```json / ``` markdown fence wrapping an LLM's JSON output."""
    raw = raw.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else raw


def format_history(messages: list) -> str:
    """Render the last few conversation turns as plain text for prompt context."""
    if not messages:
        return ""
    lines = []
    for m in messages[-10:]:
        role = "User" if m.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {m.get('content', '')}")
    return "\n".join(lines)


_TRACE_LOG = []

def clear_trace():
    _TRACE_LOG.clear()

def get_trace():
    return list(_TRACE_LOG)

def add_trace(node_name: str, user_query: str = None, prompt: str = None,
             output: str = None, retry_count=None, error: str = None):
    """Lightweight local trace log — prints and keeps in-memory for server."""
    out_msg = output if output is not None else (f"ERROR: {error}" if error else "")
    print(f"[trace] {node_name}: {out_msg}")
    _TRACE_LOG.append({
        "node": node_name,
        "query": user_query,
        "prompt": prompt,
        "output": out_msg,
        "error": error,
        "retry_count": retry_count,
        "timestamp": datetime.now().isoformat()
    })


# =========================
# GRAPH STATE
# =========================

class State(TypedDict):
    query: str                          # raw on entry; query_manager overwrites with standalone query
    original_query: str                 # raw user query (preserved for retries)
    query_manager_feedback: str         # feedback from check_query_manager if the standalone query is bad
    query_manager_retry_count: int      # retry counter for check_query_manager loop (max 3)
    is_query_correct: bool              # true if query_manager produced a correct standalone query
    messages: List[Dict[str, str]]      # in-memory conversation history for this run
    corrected_query: str
    rewrite_context: str
    expert_name: str
    selected_tables: List[str]          # tables picked by table_selector
    table_reason: str                   # why those tables were selected
    sql: str
    sql_matches: bool                   # output of sql_judge
    sql_match_reason: str
    retry_count: int                    # retry loop counter (max 2)
    content_index_hint: str             # info from Qdrant for table_selector retry
    content_index_retry_count: int
    rows: List[Any]
    is_dashboard_query: bool            # flag for llm_validator branch
    query_intent: str                   # "count" or "summary" from intent classifier
    validated_sql_context: str           # output of llm_validator batch processing
    reasoning: str                      # output of judge_and_reason
    answer: str
    needs_clarification: bool           # true if the query is ambiguous and we should stop and ask the user
    explain_request: bool               # true if user asks "why/how did you get this"
    last_sql_context: str               # exact SQL/topics from the previous turn
    session_log: list                   # in-memory log of executed SQL
    last_topic_ids: list                # [{"topic_id": ..., "title": ...}] from the previous turn's SQL results
    last_executed_sql: str              # exact SQL text run last turn — reused verbatim (WHERE/ORDER BY unchanged) for pagination continuations instead of asking the LLM to regenerate it
    last_sql_offset: int                # cumulative rows already shown for last_executed_sql's result set — becomes the OFFSET for the next "show more"/"next N" continuation (0 = nothing shown yet / fresh query)
    is_pagination_request: bool         # true when the LATEST message is a deterministic "show more"/"next N" continuation of the previous SQL result set (set by query_rewriter_node)
    pagination_requested_count: int     # explicit batch size the user asked for ("next 10" -> 10); 0 = reuse the previous batch's LIMIT size
    applied_pagination_offset: int      # the OFFSET actually used for this turn's SQL (set by generate_sql_node, consumed by execute_sql_node to compute the next turn's last_sql_offset)
    pagination_exhausted: bool          # true when this was a pagination continuation that returned 0 rows (no more results left) — lets answer_node phrase that correctly instead of saying the search itself failed
    resolved_topic_reference: str       # confirmed unique_topic_id if user says "this post/topic"
    post_metadata: dict                 # mapping of post_id to {url, source} for the final answer
    has_table_topic: bool               # output of check_query_manager — routes to keyword steps or straight to table_selector
    keywords: List[str]                 # output of keyword_of_post_maker
    keyword_feedback: str               # feedback from keyword_checker
    keyword_retry_count: int            # counter for keyword loop
    keywords_checked: List[str]         # output of keyword_of_post_maker_and_checker
    keyword_notes: str
    duck_search_term: str               # unresolved short form/acronym detected by keyword_of_post_maker
    duck_search_done: bool              # flag to avoid re-running go_duck_search more than once per turn
    duck_search_verify_term: str        # unresolved short form/acronym detected by keyword_of_post_maker_and_checker
    duck_search_verify_done: bool       # flag to avoid re-running go_duck_search_verify more than once per turn
    duck_resolved_terms: List[str]      # short forms already looked up this turn (resolved or not)
    keyword_combination_string: str     # EN/Hindi spelling + hashtag + related-entity OR-group from keyword_of_post_maker, fed into generate_sql
    hashtag_intent_detected: bool       # true when the query uses natural-language "hash/hashtag/mentions/tags" wording instead of a literal '#'
    hashtag_intent_term: str            # specific tag named alongside that wording (e.g. "uppolice"); empty = general "top hashtags" request
    answer_feedback: str                # feedback from answer_checker to add missing details
    answer_retry_count: int             # counter for answer_checker loop
    neo4j_graph_context: str            # structured graph answer from neo4j_search_node
    neo4j_search_done: bool             # flag to avoid re-running neo4j_search in same turn
    fallback_retry_count: int           # counter for Qdrant/Neo4j fallback loops (max 3)
    fallback_feedback: str              # feedback from fallbackchecker when a graph answer is wrong
    fallback_route: str                 # "keyword_search" or "graph_query" picked by fallback_decider
    fallback_exhausted: bool            # True when all 3 fallback retries failed → routes to query_rewriter
    pending_keyword_confirmation: dict  # {"term","resolved_entity","resolved_query","source"} — set when check_query_manager's live classification (or query_rewriter's own grounded clarification) is waiting on a yes/no; checked at the top of query_rewriter_node on the NEXT turn
    is_relationship_query: bool         # output of check_query_manager — true when the query asks whether 2+ named entities/incidents/places are related/connected/linked (a real-world relationship question, NOT the Neo4j account-graph kind)
    relationship_entities: List[str]    # the 2+ entity/incident names check_query_manager extracted for the relationship query
    external_relationship_context: str  # raw DuckDuckGo snippets gathered by web_relationship_search_node
    relationship_search_done: bool      # guard so web_relationship_search_node only runs once per turn
    input_source: str                   # "voice" (STT auto-submit) or "text" (typed) — set by server.py from ChatRequest.input_source; gates query_rewriter_node's voice entity grounding (Phase 5)


# =========================
# LOG TRACKING (In-Memory)
# =========================

def _search_related_log_points(query_text: str, session_log: list, limit: int = 5) -> str:
    """Deterministic (in-memory) search over THIS chat's own retrieval history."""
    if not session_log:
        return ""
        
    matches = []
    # Since this is a lightweight in-memory session log, we just return the most recent ones
    for log in reversed(session_log):
        matches.append(log)
        if len(matches) >= limit:
            break
            
    if not matches:
        return ""
        
    lines = []
    for m in matches:
        lines.append(f"- [SQL] User asked: '{m.get('query', '')}' -> Executed SQL and found {m.get('row_count', 0)} rows.")
        
    return "\n".join(lines)


# =========================
# QUERY_REWRITER'S OWN GROUNDED CLARIFICATION — separate instance, NOT shared
# with keyword_of_post_maker_node's live_search branch. query_rewriter hasn't
# run query_manager/check_query_manager yet at this point, so it
# can't route into keyword_of_post_maker_node without running the rest of the
# pipeline first — this is its own independent copy of the "7 questions ->
# DuckDuckGo" pattern, scoped to the raw query, used only to ground the
# clarification message itself before the needs_clarification short-circuit.
# Skipped entirely for explain_request — there's nothing to search for there.
# =========================

async def _query_rewriter_grounded_clarification(topic: str) -> dict:
    """Forms 7 fixed investigative questions about `topic`, answers each with a
    real DuckDuckGo search, and asks the LLM whether the grounded answers point
    at ONE specific candidate entity worth confirming with the user.

    DuckDuckGo has no idea this is "Matrix" — a police social-media monitoring
    platform — so a vague query like "what is trending going on" grounds to a
    generic external tool (Google Trends, Twitter Trends, ...) that has nothing
    to do with this system's own data. When that happens, `internal_alternative`
    is set and `grounded_message` offers Matrix's OWN trending-topics reading
    (based on post volume in the monitored data) as an explicit second choice,
    instead of silently assuming the external interpretation is what the user
    meant. Returns {"candidate_entity", "grounded_message", "internal_alternative"}
    — candidate_entity/grounded_message are empty if no confident candidate was found."""
    question_angles = [
        "Who is involved in this",
        "Why is this involved / happening",
        "When did this start",
        "Where — location",
        "What is this about",
        "Which entities are involved",
        "How is this important",
    ]
    questions = [f"{angle} — {topic}?" for angle in question_angles]

    async def _answer_one(q: str) -> str:
        results = await asyncio.to_thread(duckduckgo_search_sync, q, 3)
        if not results:
            return f"Q: {q}\nA: (no results)"
        snippet = " | ".join(r["snippet"] for r in results if r["snippet"])[:400]
        return f"Q: {q}\nA: {snippet or '(no snippet)'}"

    answered = await asyncio.gather(*[_answer_one(q) for q in questions])
    findings_text = "\n".join(answered)

    prompt = f"""The user's message below was flagged as too ambiguous to process directly,
inside "Matrix" — a police social-media monitoring platform that tracks posts, incidents,
and topics from its own monitored database. Below are DuckDuckGo-grounded answers to 7
investigative questions about the message:

{_LANGUAGE_MATCH_INSTRUCTION} (applies to grounded_message below.)

USER MESSAGE: {topic}

{findings_text}

Based ONLY on these grounded search results, is there ONE specific, concrete named
entity/topic the user is most likely asking about? Only answer with high confidence.

IMPORTANT: if the grounded answers point to a generic EXTERNAL web tool/concept that has
no connection to police work or social-media monitoring of India/UP incidents (e.g. "Google
Trends", "Twitter/X Trends", a generic dictionary definition, a general news aggregator) —
that is a real, valid candidate_entity, but it is very likely NOT what the user meant, since
this system has no access to external trend data. In that case set internal_alternative=true
and phrase grounded_message as an explicit CHOICE between the external candidate and Matrix's
OWN trending topics (based on post volume in Matrix's monitored data) — tell the user they can
reply with the candidate's name for the external meaning, or reply "matrix" for trending
topics within Matrix itself.

If the candidate is clearly domain-relevant (a person, organization, political party, incident,
movement, acronym tied to India/UP/policing/social media) set internal_alternative=false and
phrase grounded_message as a normal yes/no confirmation.

Output ONLY a JSON object:
{{
  "candidate_entity": "specific name or empty string",
  "confidence": "high" or "low",
  "internal_alternative": true or false,
  "grounded_message": "the phrased clarification question, per the rules above"
}}
"""
    raw = await call_llm(prompt)
    try:
        parsed = json.loads(clean_json_string(raw))
        if str(parsed.get("confidence", "low")).strip().lower() == "high" and parsed.get("candidate_entity"):
            return {
                "candidate_entity": str(parsed["candidate_entity"]).strip(),
                "grounded_message": str(parsed.get("grounded_message") or "").strip(),
                "internal_alternative": bool(parsed.get("internal_alternative")),
            }
    except Exception:
        pass
    return {"candidate_entity": "", "grounded_message": "", "internal_alternative": False}


# =========================
# QUERY REWRITER — grammar fix + conversation-history relation
# =========================
# =========================
# VOICE ENTITY GROUNDING (Phase 5)
# =========================
# STT (browser SpeechRecognition / self-hosted Nemotron ASR — see script.js)
# can mishear names, handles, and hashtags. Rather than trust a voice
# transcript's proper nouns as fact, cross-check them against real DB values
# before they reach table_selector/generate_sql. Gated on
# state["input_source"] == "voice" (see query_rewriter_node below) so typed
# queries keep their current latency/cost profile unchanged.

_VOICE_GROUNDING_CACHE: Dict[str, Any] = {"fetched_at": None, "candidates": None}
_VOICE_GROUNDING_TTL = timedelta(minutes=15)


def _fetch_voice_grounding_candidates() -> Dict[str, List[str]]:
    """Cheap, cached (15 min TTL) fetch of the real values a voice-transcribed
    entity should be checked against: monitored profile handles, hashtag
    keywords (both languages), and UP districts. Same DB-first, no-LLM-
    guessing spirit as _term_exists_in_internal_data above. Fails to an
    empty candidate set (never raises) so a DB hiccup just skips grounding
    for this turn instead of breaking the chat."""
    now = datetime.utcnow()
    cached = _VOICE_GROUNDING_CACHE
    if cached["candidates"] is not None and cached["fetched_at"] is not None:
        if now - cached["fetched_at"] < _VOICE_GROUNDING_TTL:
            return cached["candidates"]

    candidates = {"profiles": [], "hashtags": [], "districts": list(UP_DISTRICT_NAMES)}
    conn = None
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST, port=int(MYSQL_PORT), user=MYSQL_USER,
            password=MYSQL_PASSWORD, database=MYSQL_DB, connection_timeout=8,
        )
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT user_name FROM monitor_profiles WHERE user_name IS NOT NULL LIMIT 2000")
        candidates["profiles"] = [r[0] for r in cursor.fetchall() if r[0]]
        cursor.execute(
            "SELECT DISTINCT hashtag_keyword FROM hashtags WHERE hashtag_keyword IS NOT NULL "
            "UNION SELECT DISTINCT hashtag_hindi_keyword FROM hashtags WHERE hashtag_hindi_keyword IS NOT NULL "
            "LIMIT 2000"
        )
        candidates["hashtags"] = [r[0] for r in cursor.fetchall() if r[0]]
        cursor.close()
    except Exception as e:
        print(f"⚠️ _fetch_voice_grounding_candidates DB check failed: {e}")
    finally:
        if conn is not None:
            conn.close()

    _VOICE_GROUNDING_CACHE["candidates"] = candidates
    _VOICE_GROUNDING_CACHE["fetched_at"] = now
    return candidates


def _ground_voice_entities(entities: List[str]) -> Dict[str, Any]:
    """Fuzzy-match each extracted entity against real DB values.
    Returns {"substitutions": {original: matched}, "ambiguous": [(original, best_match)], "unmatched": [...]}.
    - ratio >= 0.92  -> confident, silently substitute
    - 0.65-0.92      -> ambiguous, ask "did you mean X?" instead of guessing
    - < 0.65         -> no plausible match in our known lists, leave as-is
                        (NOT necessarily wrong — could be a real term this
                        candidate set just doesn't cover, e.g. an incident
                        name not stored as a profile/hashtag/district)
    """
    candidates = _fetch_voice_grounding_candidates()
    pool = candidates["profiles"] + candidates["hashtags"] + candidates["districts"]
    result = {"substitutions": {}, "ambiguous": [], "unmatched": []}
    if not pool:
        return result

    for entity in entities:
        entity = (entity or "").strip()
        if not entity:
            continue
        matches = difflib.get_close_matches(entity, pool, n=1, cutoff=0.65)
        if not matches:
            result["unmatched"].append(entity)
            continue
        best = matches[0]
        ratio = difflib.SequenceMatcher(None, entity.lower(), best.lower()).ratio()
        if entity.lower() == best.lower():
            continue  # exact already, nothing to ground
        if ratio >= 0.92:
            result["substitutions"][entity] = best
        else:
            result["ambiguous"].append((entity, best))
    return result


# Natural-language ways users refer to a hashtag/mention without typing the
# literal '#' — the dataset's hashtag lookup (hashtags.hashtag_keyword /
# hashtag_hindi_keyword) and the deterministic '#' guard further down
# (_hashtag_terms_are_empty) only recognize a literal '#', so a query like
# "what is the hash today" or "hash mentions of uppolice" would otherwise
# never reach that logic and instead loop in this node's own ambiguous-
# request clarification (see Job 0 instruction injected below).
_HASHTAG_INTENT_WORDS_RE = re.compile(
    r"\bhash(?:tag)?(?:s|ed|ging)?\b|\bmentions?\b|\btags?\b",
    re.IGNORECASE,
)

# Connector/filler words that can sit between a hashtag-intent word and a
# real tag name, or trail one without naming anything — e.g. "hash mentions
# today", "hashtag for X", "what is the hashtag" (no specific tag named).
_HASHTAG_QUERY_STOPWORDS = {
    "today", "yesterday", "content", "mention", "mentions", "tag", "tags",
    "hashtag", "hashtags", "hash", "hashed", "used", "post", "posts", "the",
    "database", "matrix", "trends", "trend", "trending", "social", "media",
    "of", "on", "for", "about", "in", "is", "are", "was", "were", "what",
    "show", "me", "please", "give", "list", "and", "or", "that", "this",
    "week", "weeks", "month", "months", "year", "years", "hour", "hours",
    "day", "days", "recent", "latest", "most", "top", "all", "current",
}


def _detect_hashtag_intent(query: str) -> bool:
    """True when `query` uses a natural-language hashtag/mention word
    ('hash', 'hashtag', 'hashed', 'mentions', 'tags'...) but contains no
    literal '#' — i.e. the user means hashtags, but the '#'-keyed machinery
    elsewhere in the pipeline won't recognize it as such without
    normalization."""
    if "#" in query:
        return False  # already a literal '#' — existing logic handles it
    return bool(_HASHTAG_INTENT_WORDS_RE.search(query))


def _extract_named_hashtag_term(query: str) -> str:
    """When hashtag intent is detected AND a specific tag/handle is named
    close to the hashtag-intent word (e.g. "hash mentions of uppolice",
    "hashtag for bjplucknow"), pull out that term. Returns "" when the
    query only asks about hashtags in general ("what is the hash today",
    "hashed mentions used in posts today") with no specific term — that's a
    trending/most-used-hashtags request, not a search for one hashtag.
    Only looks a few words past each hashtag-intent word (not the whole
    message) so unrelated trailing words don't get mistaken for a tag."""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", query)
    lowered = [t.lower() for t in tokens]
    for i, lw in enumerate(lowered):
        if not _HASHTAG_INTENT_WORDS_RE.fullmatch(lw):
            continue
        for lw2 in lowered[i + 1: i + 5]:
            if _HASHTAG_INTENT_WORDS_RE.fullmatch(lw2) or lw2 in _HASHTAG_QUERY_STOPWORDS:
                continue
            if len(lw2) < 3:
                continue
            return lw2
    return ""


def _hashtag_intent_job_instruction(hashtag_intent_term: str) -> str:
    """Prompt block injected into query_rewriter's LLM call so it stops
    treating hashtag/mention wording as an ambiguous request needing
    clarification, and instead normalizes it into the literal '#' form the
    rest of the pipeline already understands."""
    if hashtag_intent_term:
        return f"""
## Job 0 — Hashtag/mention wording (deterministic — do NOT ask for clarification)

The user's message uses a natural-language hashtag word ("hash", "hashtag",
"mentions", "tags") instead of typing '#'. In this dataset that ALWAYS means
the '#' hashtag/mention feature. Do NOT set needs_clarification=true because
of this wording. Rewrite corrected_query so the named term is expressed as a
literal hashtag — e.g. turn "hash mentions of {hashtag_intent_term}" into
something that includes "#{hashtag_intent_term}" literally.

---
"""
    return """
## Job 0 — Hashtag/mention wording (deterministic — do NOT ask for clarification)

The user's message uses a natural-language hashtag word ("hash", "hashtag",
"mentions", "tags") instead of typing '#', with NO specific hashtag named.
This means the user wants the most-used hashtags/mentions for the given time
period — e.g. "what is the hash today" means "what are the most-used
hashtags/mentions in today's posts". Do NOT set needs_clarification=true
because of this wording. Set corrected_query to a clear standalone request
for the top/most-used hashtags for that time period.

---
"""


# ── Pagination follow-up detection (deterministic) ──────────────────────────
# "show more" / "next 10" / "show next" etc. must reliably continue the
# previous SQL result set (same WHERE/ORDER BY, advanced OFFSET) rather than
# being left to an LLM classification that can silently drift. Kept
# deterministic and regex-based, the same pattern used for the hashtag-intent
# guard above, so this can never be talked out of firing by prompt phrasing.
_PAGINATION_RE = re.compile(
    r"^\s*(show\s+|give\s+|send\s+)?(me\s+)?(the\s+)?"
    r"(next|more)(\s+(\d+))?(\s+(results?|rows?|posts?|topics?|items?|ones?))?\s*$",
    re.IGNORECASE,
)
# Phrases that contain "next"/"more" but are NOT a pagination continuation —
# excluded so this guard doesn't misfire on unrelated short messages.
_PAGINATION_EXCLUDE_RE = re.compile(
    r"\b(next\s+(week|month|year|day|time|step)|more\s+(details?|info|information|about))\b",
    re.IGNORECASE,
)


def _detect_pagination_request(text: str):
    """Returns the explicitly requested batch size (0 if unspecified) if
    `text` is a short 'show more'/'next N' continuation request, else None."""
    t = (text or "").strip()
    if not t or len(t.split()) > 6:
        return None
    if _PAGINATION_EXCLUDE_RE.search(t):
        return None
    m = _PAGINATION_RE.match(t)
    if not m:
        return None
    count_str = m.group(6)
    return int(count_str) if count_str else 0


async def query_rewriter_node(state: State) -> dict:
    """START -> here first, every turn.

    One LLM call that (1) fixes grammar/typos in the latest message and
    (2) figures out what it relates to in the conversation history so far.
    Never answers the question — that is query_manager_node's job.

    SPECIAL CASE: If fallback_exhausted=True it means Qdrant+Neo4j
    tried 3 times and found similar-but-not-exact data. In this case we
    immediately ask the user for clarification instead of re-processing.
    """
    query = state.get("original_query") or state["query"]

    # ── Hashtag/mention wording detection (deterministic, no LLM) ──────────
    # Runs before anything else so both the prompt injected below AND the
    # post-parse override further down can act on it.
    hashtag_intent_detected = _detect_hashtag_intent(query)
    hashtag_intent_term = _extract_named_hashtag_term(query) if hashtag_intent_detected else ""

    # ── Pagination follow-up shortcut (deterministic, no LLM) ───────────────
    # "show more" / "next 10" only ever means "continue the previous SQL
    # result set" — never ambiguous, so it bypasses the LLM job entirely
    # (same reasoning as the hashtag-intent guard) rather than risking the
    # model treating it as a new/unrelated short query. Only fires when
    # there's an actual previous SQL result to continue (last_executed_sql
    # threaded in from server.py's session store); otherwise falls through
    # to the normal elliptical-follow-up handling below, which will
    # correctly ask for clarification since there's nothing to page through.
    if (
        not state.get("fallback_exhausted")
        and not state.get("pending_keyword_confirmation")
    ):
        pagination_count = _detect_pagination_request(query)
        if pagination_count is not None and state.get("last_executed_sql"):
            add_trace("query_rewriter", user_query=query,
                       output=f"[pagination] '{query}' resolved as a continuation "
                              f"of the previous SQL result set "
                              f"(requested_count={pagination_count or '(same as before)'})")
            return {
                "corrected_query": "Show the next batch of results from the previous query.",
                "rewrite_context": "Pagination continuation of the previous SQL result set.",
                "needs_clarification": False,
                "explain_request": False,
                "resolved_topic_reference": "",
                "hashtag_intent_detected": False,
                "hashtag_intent_term": "",
                "is_pagination_request": True,
                "pagination_requested_count": pagination_count,
            }

    # ── Greeting shortcut ──────────────────────────────────────────────────
    # Plain small talk ("hi", "hello", "namaste", ...) never needs a DB lookup.
    # Answer directly here and route straight to END, same mechanism as the
    # fallback_exhausted shortcut below, so it never reaches table_selector/
    # generate_sql/execute_sql at all. Skipped while a real multi-turn flow
    # (fallback_exhausted / pending_keyword_confirmation) is in progress, so a
    # stray "hi" mid-flow doesn't derail it.
    if (
        not state.get("fallback_exhausted")
        and not state.get("pending_keyword_confirmation")
        and GREETING_PATTERN.match(query.strip())
    ):
        greeting_reply = GREETING_REPLIES[_query_language(query)]

        add_trace("query_rewriter", user_query=query, output="Greeting detected — answered directly, no DB lookup")
        return {
            "needs_clarification": True,
            "explain_request": False,
            "answer": greeting_reply,
            "corrected_query": query,
            "rewrite_context": "",
        }
    # ── Fallback exhaustion shortcut ──────────────────────────────────────
    if state.get("fallback_exhausted"):
        graph_context = state.get("content_index_hint", "")
        # Build a short preview of what we actually found
        preview_lines = [line for line in graph_context.splitlines() if line.strip()][:5]
        preview = "\n".join(preview_lines)
        clarification_prompt = f"""You are the UP Police Matrix assistant. A search for the
user's question found only loosely related data, not an exact match.

{_LANGUAGE_MATCH_INSTRUCTION}

USER'S QUESTION:
{query}

Write a short, polite message that:
1. Tells the user only loosely related data was found, not an exact match.
2. Shows the related data below under a short bolded heading, EXACTLY as given, unchanged.
3. Asks them to clarify exactly which specific person, incident, or detail they mean.

RELATED DATA FOUND:
{preview}

Return ONLY the message to show the user. No JSON. No explanation of your reasoning."""
        clarification_msg = (await call_llm(clarification_prompt)).strip()
        if not clarification_msg:
            # LLM call failed/timed out — fall back to a fixed template picked
            # by the same language cue, instead of always defaulting to Hindi.
            clarification_msg = CLARIFICATION_FALLBACK[_query_language(query)].format(preview=preview)
        add_trace("query_rewriter", output="Fallback exhausted — asking user for clarification")
        return {
            "needs_clarification": True,
            "explain_request": False,
            "answer": clarification_msg,
            "corrected_query": query,
            "rewrite_context": "",
            "fallback_exhausted": False,   # reset for next turn
            "fallback_retry_count": 0,
            "fallback_feedback": "",
            "fallback_route": "",
        }
    # ─────────────────────────────────────────────────────────────────────
    # NOTE: server.py's chat_endpoint builds a brand-new State dict from
    # scratch on every /api/chat call — it never re-supplies a State field
    # from the previous turn's result (this is also why the
    # pending_keyword_confirmation shortcut immediately below only actually
    # works through ollamaagent2.py's standalone CLI REPL, not the deployed
    # web app).

    # ── Pending confirmation shortcut ───────────────────────────────────────
    # A previous turn asked "Are you asking about <X>?" (either from this node's
    # own grounded-clarification instance below, or from the topic-classification
    # shortcut further down) and is waiting on a yes/no reply.
    pending = state.get("pending_keyword_confirmation")
    if pending:
        reply = query.strip().lower()
        affirmative = reply in ("yes", "y", "yeah", "yep", "haan", "ha", "sahi", "correct", "confirm", "confirmed")
        negative = reply in ("no", "n", "nope", "nahi", "galat", "incorrect")
        wants_internal = pending.get("internal_alternative") and reply in ("matrix", "internal", "here", "our data", "platform")

        if wants_internal:
            # User rejected the external (e.g. "Google Trends") reading and wants
            # Matrix's OWN trending topics instead — based on post volume in the
            # monitored data, not the DuckDuckGo-grounded external candidate.
            add_trace("query_rewriter", user_query=query,
                     output=f"user chose Matrix's internal trending topics over external candidate '{pending['resolved_entity']}'")
            return {
                "corrected_query": "Show today's trending topics in Matrix, ordered by total number of posts (post volume) across all districts.",
                "rewrite_context": "User asked for trending topics within Matrix itself, not an external/general web trend.",
                "needs_clarification": False,
                "explain_request": False,
                "pending_keyword_confirmation": None,
            }
        elif affirmative:
            resolved_query = pending.get("resolved_query") or pending["resolved_entity"]
            add_trace("query_rewriter", user_query=query,
                     output=f"confirmed '{pending['term']}' -> '{pending['resolved_entity']}'")
            return {
                "corrected_query": resolved_query,
                "rewrite_context": f"User confirmed '{pending['term']}' means '{pending['resolved_entity']}'.",
                "needs_clarification": False,
                "explain_request": False,
                "pending_keyword_confirmation": None,
            }
        elif negative:
            add_trace("query_rewriter", user_query=query,
                     output=f"user rejected guess for '{pending['term']}'")
            return {
                "needs_clarification": True,
                "explain_request": False,
                "answer": NEGATIVE_CLARIFICATION[_query_language(query)].format(term=pending["term"]),
                "corrected_query": pending["term"],
                "rewrite_context": "",
                "pending_keyword_confirmation": None,
            }
        # Anything else (not a yes/no reply) — drop the stale pending confirmation
        # and fall through to process this message as a brand-new query.
    # ─────────────────────────────────────────────────────────────────────
    messages = state.get("messages", [])
    session_log = state.get("session_log", [])
    last_sql_context = state.get("last_sql_context", "")
    feedback = state.get("query_manager_feedback", "")

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    history_block = format_history(messages) or "(none — this is the first message of the conversation)"

    last_sql_block = last_sql_context or "(none — no prior successful SQL turn this session)"

    related_history = _search_related_log_points(query, session_log)
    history_context = f"PAST LOG POINTS:\n{related_history}" if related_history else ""

    last_topic_ids = state.get("last_topic_ids", [])
    if last_topic_ids:
        topic_lines = []
        for t in last_topic_ids[:20]:
            topic_lines.append(
                f"  - unique_topic_id: {t['topic_id']} | title: {t['title'][:150]}"
            )
        last_topics_block = "TOPICS FROM PREVIOUS SQL RESULT:\n" + "\n".join(topic_lines)
    else:
        last_topics_block = "(no topics from previous SQL turn)"

    feedback_block = f"\nFEEDBACK FROM PREVIOUS ATTEMPT:\nThe previous generated query was rejected because: {feedback}\nPlease fix the errors based on this feedback." if feedback else ""

    prompt = f"""Current Date: {today}
Yesterday: {yesterday}

==========================================================
PREVIOUS SUCCESSFUL SQL CONTEXT (if any):
{last_sql_block}

{history_context}
{feedback_block}


CONVERSATION HISTORY:
{history_block}

LATEST USER MESSAGE:
{query}

{last_topics_block}
==========================================================

You have four jobs on the user's LATEST message.

You do NOT answer the user.
You do NOT generate SQL.
You only rewrite and resolve context.
{_hashtag_intent_job_instruction(hashtag_intent_term) if hashtag_intent_detected else ""}
## Job 1 — Grammar correction

Fix spelling, grammar, and typing mistakes in the LATEST message ONLY.

Rules:
- Preserve the user's language (English/Hindi/Hinglish).
- Preserve meaning exactly.
- Do not translate.
- Do not expand or answer.
- If there are no mistakes, return the message unchanged.

---

## Job 2 — Context relation

Determine whether the latest message depends on previous conversation context.

Identify:

- Previous related query/turn.
- Referenced topic.
- Referenced post.
- Referenced monitored profile/account.
- Filters inherited from previous turn:
  - district
  - date range
  - category
  - platform
  - topic
  - profile

Only carry forward information explicitly available from history or previous SQL context.

Never invent:
- topic_id
- username
- district
- category
- filters

---

## Follow-up Resolution Rules

Short follow-ups can depend on previous SQL results.

Examples:

Previous:
"viral topic of Lucknow today"

Latest:
"show all"

If previous SQL returned exactly one topic:
Resolve as:
"show all posts of that topic"

Carry forward:
- exact unique_topic_id
- district
- date filter
- topic context

If previous SQL returned multiple topics:
Ask clarification because "show all" is ambiguous.

---

Previous:
"Which posts tag DGP?"

Latest:
"show sentiment"

Resolve:
- same tagged posts
- only requested output changes to sentiment

---

Previous:
"Show posts of fire incident"

Latest:
"show author"

Resolve:
- same posts
- output changes to author information

---

## Elliptical Short Follow-ups

If the latest message is 1-4 words and incomplete:

Examples:
- "show all"
- "show more"
- "details"
- "sentiment"
- "author"
- "url"

Check previous context first.

If previous context clearly identifies one entity:
resolve it.

If previous context does not identify one clear entity:
set needs_clarification=true.

---

## Job 3 — Explain Request Detection

If the latest message asks how or why the previous answer was generated:

Examples:
- "how did you find this?"
- "why this result?"
- "explain your reasoning"

Set:
explain_request = true

Otherwise:
explain_request = false

---
## Job 4 — Contextual Result Reference Resolution

Resolve whether the LATEST message depends on the previous SQL result, previous query,
or returned topics/posts.

Use:
- TOPICS FROM PREVIOUS SQL RESULT
- PREVIOUS SUCCESSFUL SQL CONTEXT
- CONVERSATION HISTORY

### Resolve explicit references

If the latest message refers to a previous result using phrases like:

- "this post"
- "this topic"
- "that incident"
- "ye post"
- "ye topic"
- "iske baare mein"
- "show posts of this"
- "open this"
- "details of this"
- "more about this"

or quotes/paraphrases a returned topic title:

Set:
"resolved_topic_id" = exact matching unique_topic_id

### Resolve implicit follow-ups

If the latest message is a short command that has no object but clearly continues
the previous query, treat it as referring to the previous result context.

Examples:

Previous:
"viral topic of Lucknow today"

User:
"show all"

Meaning:
"show all posts of the viral topic identified in previous result"

Set:
- related = true
- notes should mention the inherited context
- resolved_topic_id:
    - If exactly one topic was returned, use that topic unique_topic_id.
    - If multiple topics were returned, keep empty string "" because the user has not selected one.

Other implicit follow-ups:

Previous:
"show murder incidents in Lucknow"

User:
"show posts"

Meaning:
"show posts for the previously requested murder incidents"

Previous:
"top trending topic"

User:
"details"

Meaning:
"show details of the previously identified trending topic"

### Do not resolve

Do NOT resolve when:
- The latest message starts a new independent query.
- The previous result has multiple possible topics and the user did not specify which one.
- The phrase is unrelated to previous context.

If no valid resolution:
"resolved_topic_id": ""

---

## Job 5 — Domain Vocabulary Normalization

Users describe requests across 10 monitoring domains (law & order/unrest,
women's safety, caste-related monitoring, crime & OSINT, misinformation,
police perception, predictive alerting, geo/language breakdowns,
cross-platform network analysis, reporting) in loose everyday language. This
is normal, expected phrasing for this system — do NOT set
needs_clarification=true just because the wording is informal, uses a
severity synonym instead of a formal category name, or names a "zone"
instead of a district. Normalize corrected_query so generate_sql can act on
it directly:

- State-wide scope: The entire database is already the Uttar Pradesh Police database (all 75 districts). If the user query includes "UP", "Uttar Pradesh", "all over UP", or "entire state", normalize `corrected_query` to state-wide subject inquiry (e.g., "protest in uttar pradesh" -> "protests and dharna across Uttar Pradesh") so downstream nodes know to fetch all records across the 75 districts of UP without applying any district filter or searching the literal words "in uttar pradesh" in titles.
- Crime-severity synonyms ("sensational crime", "heinous crime", "shocking
  crime", "high-profile crime", "brutal/gruesome murder") all describe a
  crime-category filter, not an ambiguous request — keep them in
  corrected_query as-is so generate_sql can match them against
  broad_category/sub_category; do not ask the user to pick one synonym over
  another.
- "Zone" is a real, distinct concept (district → range → commissionerate →
  zone → thana) from "district" — preserve whichever the user actually said
  rather than silently substituting one for the other.
- "Highest" vs "lowest" number of cases are opposite requests — preserve
  exactly which one the user asked for; if they ask for both, keep both in
  corrected_query.
- Requests for "who is posting bad/negative content against [CM/minister/
  official]" with platform/link/content detail are a specific, well-formed
  request (VIP mention monitoring) — not something requiring clarification
  just because no single person was named.
- Requests to score or flag accounts as "bot"/"fake"/"coordinated" on a
  numeric scale are answerable only by noting this dataset has no such
  score — do not set needs_clarification=true for these either; pass the
  request through as-is so the final answer can state that limitation
  honestly rather than being blocked earlier in the pipeline.

---

## Clarification Rules

Set needs_clarification=true only when:

- The request is impossible to understand.
- A short follow-up cannot be resolved from context.
- Multiple possible previous entities exist.

Do NOT ask clarification when:
- A previous SQL result contains exactly one clear topic/entity.
- The user only changes requested output fields.

---

## Output Format

Return ONLY valid JSON.

No markdown.
No explanation.

{{
  "corrected_query": "LATEST message corrected",
  "related": true or false,
  "notes": "short plain-text notes",
  "needs_clarification": true or false,
  "clarification_message": "question if clarification needed else empty string",
  "explain_request": true or false,
  "resolved_topic_id": "exact unique_topic_id if a previous topic/post reference can be uniquely resolved, otherwise empty string"
  "resolved_profile_username": "username or empty string",
  "resolved_post_context": true or false,
  "extracted_entities": ["proper nouns / named things in corrected_query — person names, handles, hashtags, district/place names, organization names. Empty list if none."]
}}
"""

    raw = await call_llm(prompt)
    corrected_query = query
    rewrite_context = ""
    needs_clarification = False
    clarification_message = ""
    explain_request = False
    explain_answer = ""
    
    extracted_entities: List[str] = []
    try:
        parsed = json.loads(clean_json_string(raw))
        corrected_query = str(parsed.get("corrected_query") or "").strip() or query
        if parsed.get("related"):
            rewrite_context = str(parsed.get("notes") or "").strip()
        extracted_entities = [str(e).strip() for e in (parsed.get("extracted_entities") or []) if str(e).strip()]

        if parsed.get("needs_clarification"):
            needs_clarification = True
            clarification_message = str(parsed.get("clarification_message") or "Could you please clarify what you mean?")
            
        if parsed.get("explain_request"):
            explain_request = True
            explain_prompt = f"The user asked for an explanation: '{query}'. Based on the PAST LOG POINTS:\n{related_history}\nAnd PREVIOUS SQL:\n{last_sql_context}\nWrite a short, friendly explanation of how you arrived at your answer."
            explain_answer = (await call_llm(explain_prompt)).strip()
            
    except Exception as e:
        print(f"⚠️ query_rewriter_node: could not parse JSON ({e}) — falling back")

    # ── Hashtag/mention wording override (deterministic) ───────────────────
    # Belt-and-braces on top of the Job 0 prompt instruction above: even if
    # the model still asked for clarification anyway, never let "hash"/
    # "mentions"/"tags" wording dead-end in a clarification loop. Normalize
    # corrected_query into literal '#' form so downstream nodes
    # (check_query_manager, generate_sql's '#' guard) recognize it exactly
    # like a user-typed '#' reference.
    if hashtag_intent_detected:
        if needs_clarification:
            add_trace("query_rewriter",
                       output="[hashtag intent] overriding model's needs_clarification=true — "
                              "hash/mentions/tags wording is a known pattern, not ambiguous")
        needs_clarification = False
        clarification_message = ""
        if "#" not in corrected_query:
            corrected_query = (
                f"{corrected_query} (#{hashtag_intent_term})" if hashtag_intent_term
                else f"{corrected_query} (#TRENDING_HASHTAGS_TODAY)"
            )

    add_trace("query_rewriter", user_query=query, prompt=prompt,
             output=f"corrected_query={corrected_query}; rewrite_context={rewrite_context or '(none)'}; explain={explain_request}"
                    + (f"; hashtag_intent_term={hashtag_intent_term or '(trending/general)'}" if hashtag_intent_detected else ""))
             
    # Extract resolved topic reference — only trust it if it matches a real ID
    # from this turn's actual SQL results. The LLM is instructed to return ""
    # when it can't resolve a reference, but it can still hallucinate a
    # plausible-looking ID instead of complying, so ground-truth-check it here
    # before it gets treated as fact by query_manager_node/generate_sql_node.
    resolved_topic_id = ""
    try:
        if parsed.get("resolved_topic_id"):
            candidate_id = str(parsed["resolved_topic_id"]).strip()
            valid_ids = {t["topic_id"] for t in last_topic_ids}
            if candidate_id in valid_ids:
                resolved_topic_id = candidate_id
            else:
                print(f"⚠️ query_rewriter_node: discarding resolved_topic_id '{candidate_id}' — not found in last_topic_ids")
    except Exception:
        pass

    result = {
        "corrected_query": corrected_query,
        "rewrite_context": rewrite_context,
        "needs_clarification": needs_clarification,
        "explain_request": explain_request,
        "resolved_topic_reference": resolved_topic_id,
        "hashtag_intent_detected": hashtag_intent_detected,
        "hashtag_intent_term": hashtag_intent_term,
    }
    if needs_clarification:
        result["answer"] = clarification_message
        # ── Grounded clarification (separate instance) ──────────────────────
        # explain_request bypasses this entirely — nothing to search for there.
        if not explain_request:
            grounding = await _query_rewriter_grounded_clarification(corrected_query)
            if grounding["candidate_entity"]:
                result["answer"] = grounding["grounded_message"] or clarification_message
                result["pending_keyword_confirmation"] = {
                    "term": corrected_query,
                    "resolved_entity": grounding["candidate_entity"],
                    "resolved_query": grounding["candidate_entity"],
                    "source": "query_rewriter_grounded",
                    "internal_alternative": grounding.get("internal_alternative", False),
                }
                add_trace("query_rewriter", user_query=query,
                         output=f"grounded clarification: '{corrected_query}' -> candidate '{grounding['candidate_entity']}'")
        # ──────────────────────────────────────────────────────────────────
    if explain_request:
        result["answer"] = explain_answer

    # ── Voice entity grounding (Phase 5) ────────────────────────────────
    # Only for voice-originated turns (input_source == "voice", set by
    # server.py from ChatRequest.input_source — see Phase 1), and only if
    # the LLM's own needs_clarification/explain_request didn't already
    # claim this turn. Cross-checks extracted_entities against real DB
    # values before they're treated as fact by table_selector/generate_sql.
    if (
        state.get("input_source") == "voice"
        and extracted_entities
        and not needs_clarification
        and not explain_request
    ):
        grounding = _ground_voice_entities(extracted_entities)
        for original, matched in grounding["substitutions"].items():
            # High-confidence (ratio >= 0.92): STT almost certainly misheard
            # `original` for this real known value — substitute silently.
            corrected_query = re.sub(re.escape(original), matched, corrected_query, flags=re.IGNORECASE)
            result["corrected_query"] = corrected_query
            add_trace("query_rewriter", output=f"[voice grounding] substituted '{original}' -> '{matched}'")
        if grounding["ambiguous"]:
            # Medium-confidence (0.65-0.92): don't guess — ask, reusing the
            # same pending_keyword_confirmation shape the LLM-driven
            # clarification path uses above, so the next turn is handled
            # identically either way.
            original, best = grounding["ambiguous"][0]
            ask_message = f"I heard \"{original}\" — did you mean **{best}**?"
            result["needs_clarification"] = True
            result["answer"] = ask_message
            result["pending_keyword_confirmation"] = {
                "term": original,
                "resolved_entity": best,
                "resolved_query": corrected_query.replace(original, best),
                "source": "voice_grounding",
                "internal_alternative": False,
            }
            add_trace("query_rewriter",
                       output=f"[voice grounding] ambiguous '{original}' ~ '{best}' — asking for confirmation")
        # Entities below the 0.65 cutoff (grounding["unmatched"]) are left
        # untouched — no plausible match in our known lists is NOT proof the
        # term is wrong, it may simply be a real subject this candidate set
        # doesn't cover (e.g. an incident name, not a profile/hashtag/district).

    return result


# =========================
# QUERY MANAGER — writes the final standalone query
# =========================
async def query_manager_node(state: State) -> dict:
    """The only node that writes state["query"].
    Consumes query_rewriter_node output and constructs a fully standalone query.
    """

    corrected_query = state.get("corrected_query") or state["query"]
    rewrite_context = state.get("rewrite_context", "")
    last_sql_context = state.get("last_sql_context", "")
    resolved_topic_id = state.get("resolved_topic_reference", "")
    messages = state.get("messages", [])
    history_block = format_history(messages) or "(none — this is the first message of the conversation)"
    feedback = state.get("query_manager_feedback", "")

    # Inject resolved topic reference if available
    if resolved_topic_id:
        topic_note = (
            f"\n- RESOLVED TOPIC: User is referring to topic "
            f"unique_topic_id='{resolved_topic_id}'. "
            f"Use this exact ID instead of searching by title."
        )
        rewrite_context = (rewrite_context or "") + topic_note

    # Only skip rewriting when there is absolutely no previous context and no feedback
    if not rewrite_context and not last_sql_context and not feedback:
        return {"query": corrected_query}

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    last_sql_block = last_sql_context or "(none)"
    feedback_block = f"\nVALIDATOR FEEDBACK FROM PREVIOUS ATTEMPT:\nThe previous generated query was rejected because: {feedback}\nPlease fix the standalone query based on this feedback." if feedback else ""

    prompt = f"""Current Date: {today}
Yesterday: {yesterday}

You are an expert query-rewriting assistant for a police social-media monitoring database.

Your ONLY task:
Convert the user's latest message into ONE fully self-contained natural language query.

You do NOT answer the user.
You do NOT write SQL.
You only rewrite the request so another AI can generate SQL correctly.

==========================================================
PREVIOUS SUCCESSFUL QUERY CONTEXT:
{last_sql_block}

CONVERSATION HISTORY:
{history_block}

RELATION NOTES:
{rewrite_context}
{feedback_block}

LATEST USER MESSAGE:
{corrected_query}
==========================================================


## Rules

### 1. Resolve references — produce CONCRETE queries

Replace words referring to previous results with the actual concrete context.
The output MUST be understandable by someone who has never seen the conversation.

Examples:

Previous query:
"viral topic of Lucknow today"

User:
"show all"

CORRECT Output:
"Show all viral topics of Lucknow today."

WRONG Output:
"Show all posts of the viral topic identified from the previous query."
(This references "previous query" — not self-contained!)


Previous query:
"fire incident in Lucknow"

User:
"show posts"

CORRECT Output:
"Show all posts related to fire incidents in Lucknow."

WRONG Output:
"Show posts from the previously identified fire incident."


Previous query:
"show details of this topic"

If RELATION NOTES contains a resolved topic ID:
Output:
"Show details of topic unique_topic_id='xxxxx'."


### 2. Handle short follow-up messages

Treat these as continuation commands when previous context exists:

- show all
- show posts
- details
- more
- list them
- open this
- explain this

Never treat them as independent queries if a previous subject exists.


### 3. Preserve previous constraints — ONLY for the SAME subject

Carry forward previous filters (district, date range, category, incident
type, topic, platform, sorting requirement) ONLY when the LATEST message is
clearly a continuation, refinement, or follow-up of the SAME
subject/investigation as PREVIOUS SUCCESSFUL QUERY CONTEXT — e.g. it's a
short follow-up (see Rule 2), it only changes one attribute (see Rule 4), or
it explicitly references "this"/"that"/the previous result.

Do NOT carry forward ANY previous filter when the LATEST message introduces
a new, unrelated subject, incident, or category that does not reference the
previous query at all — treat it as a fresh, unconstrained request instead,
even if a PREVIOUS SUCCESSFUL QUERY CONTEXT exists from earlier in the
conversation. A change of subject silently inheriting an old district/date
range/category is a bug, not a feature — never do it.

Example (do NOT carry forward):

Previous query:
"viral topics of Lucknow last week"

User:
"any bad words about the ministers of UP"

CORRECT Output:
"Any bad words/negative posts about ministers of UP." (no district or date
range carried forward — this is a new, unrelated subject)

WRONG Output:
"Any bad words about the ministers of UP in Lucknow last week." (silently
inherited an unrelated previous filter)

Example (broadening scope — drop district filter):

Previous query:
"show murder cases in Lucknow"

User:
"what about all over UP?"

CORRECT Output:
"Show murder cases across all of Uttar Pradesh." (The district filter MUST be 
dropped because the scope expanded to the entire state).


### 4. Attribute changes

If the user changes or adds only one attribute, modify ONLY that attribute in the previous query.

Example 1:

Previous:
"viral topic of Lucknow today"

User:
"yesterday"

Output:
"Find the viral topics of Lucknow yesterday."


Example 2:

Previous:
"what are viral topics of Lucknow"

User:
"of today"

Output:
"What are the viral topics of Lucknow today?"

(Do NOT change the query structure. Just add the date filter.)


Example 3:

Previous:
"show murder cases in Lucknow"

User:
"Kanpur"

Output:
"Show murder cases in Kanpur."

Keep all other constraints.


### 5. Topic ID priority

If a resolved topic ID exists, always preserve it.

Example:

"Show all posts for unique_topic_id='abc123'"

Do not replace it with title matching.


### 6. No clarification

Never ask questions.
Always produce the best possible standalone query.


### 7. NEVER use vague references

NEVER use phrases like:
- "previously identified"
- "from the previous query"
- "the viral topic identified earlier"
- "topics found in the last search"

These make the query NOT self-contained.
Always replace such references with the actual concrete subject.


## Output Rules

Return ONLY the rewritten standalone query.

No markdown.
No explanation.
No quotes.

"""

    written_query = (await call_llm(prompt)).strip()
    if written_query.startswith('"') and written_query.endswith('"'):
        written_query = written_query[1:-1].strip()
    if written_query.startswith("'") and written_query.endswith("'"):
        written_query = written_query[1:-1].strip()

    final_query = written_query or corrected_query
    add_trace("query_manager", user_query=corrected_query, prompt=prompt, output=final_query)
    return {"query": final_query}


# =========================
# CHECK QUERY MANAGER — decides if the standalone query needs keyword extraction
# =========================

def _term_exists_in_internal_data(term: str) -> bool:
    """DB-FIRST GATE for the acronym/short-form live-classification step below.
    Cheap existence check (LIMIT 1, no COUNT) against the two columns that
    actually hold post/topic content — analyzed_data.input_text and
    analyzed_data.topic_title. If the term already shows up in real posts our
    system has ingested, it is NOT an unresolved external acronym; it is a
    real subject we have data on, and DuckDuckGo must never be consulted for
    it. Fails OPEN (returns False -> falls through to web grounding) only on
    a genuine DB error, so a transient connection hiccup doesn't silently
    hide real data — but a normal empty result correctly returns False too.
    """
    like_term = f"%{term}%"
    sql = (
        "SELECT 1 FROM analyzed_data "
        "WHERE input_text LIKE %s OR topic_title LIKE %s LIMIT 1"
    )
    conn = None
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST, port=int(MYSQL_PORT), user=MYSQL_USER,
            password=MYSQL_PASSWORD, database=MYSQL_DB, connection_timeout=8,
        )
        cursor = conn.cursor()
        cursor.execute(sql, (like_term, like_term))
        found = cursor.fetchone() is not None
        cursor.close()
        return found
    except Exception as e:
        print(f"⚠️ _term_exists_in_internal_data DB check failed for '{term}': {e}")
        return False
    finally:
        if conn is not None:
            conn.close()


async def _check_query_manager_grounded_classification(term: str, original_query: str = "") -> dict:
    """Independent copy of the "7 questions -> DuckDuckGo" pattern, used ONLY by
    check_query_manager_node's live classification step below. Not shared code
    with query_rewriter_node's own grounded-clarification instance — the two
    fire at different, non-overlapping points in the pipeline (this one only
    once a standalone_query already exists and a specific term in it is
    unresolved), so they're kept as deliberately separate call sites.

    `original_query` is passed in ONLY so grounded_message can be written in
    whatever language the user actually typed in — `term` alone (a short
    acronym) isn't enough signal for that.

    Returns {"candidate_entity", "grounded_message", "internal_alternative"} —
    candidate_entity/grounded_message are empty if no confident candidate was found."""
    question_angles = [
        "Who is involved in this",
        "Why is this involved / happening",
        "When did this start",
        "Where — location",
        "What is this about",
        "Which entities are involved",
        "How is this important",
    ]
    questions = [f"{angle} — {term}?" for angle in question_angles]

    async def _answer_one(q: str) -> str:
        results = await asyncio.to_thread(duckduckgo_search_sync, q, 3)
        if not results:
            return f"Q: {q}\nA: (no results)"
        snippet = " | ".join(r["snippet"] for r in results if r["snippet"])[:400]
        return f"Q: {q}\nA: {snippet or '(no snippet)'}"

    answered = await asyncio.gather(*[_answer_one(q) for q in questions])
    findings_text = "\n".join(answered)

    prompt = f"""The term below was flagged by check_query_manager as an unresolved
acronym/short-form inside "Matrix" — a police social-media monitoring platform. Below
are DuckDuckGo-grounded answers to 7 investigative questions about it:

{_LANGUAGE_MATCH_INSTRUCTION} (applies to grounded_message below — match the language of
the ORIGINAL USER MESSAGE, not necessarily the bare TERM.)

ORIGINAL USER MESSAGE (for language matching only): {original_query or term}

TERM: {term}

{findings_text}

Based ONLY on these grounded search results, is there ONE specific, concrete named
entity/topic the term most likely refers to? Only answer with high confidence — if the
results are vague, contradictory, or give no clear single answer, return an empty string
instead of guessing.

IMPORTANT: if the grounded answers point to a generic EXTERNAL web tool/concept that has
no connection to police work or social-media monitoring of India/UP incidents (e.g. a
generic dictionary definition, a general news aggregator, an unrelated global brand) —
that is a real, valid candidate_entity, but it is very likely NOT what the user meant,
since this system has no access to external data. In that case set
internal_alternative=true and phrase grounded_message as an explicit CHOICE between the
external candidate and Matrix's OWN trending topics (based on post volume in Matrix's
monitored data) — tell the user they can reply with the candidate's name for the external
meaning, or reply "matrix" for trending topics within Matrix itself.

If the candidate is clearly domain-relevant (a person, organization, political party,
incident, movement, acronym tied to India/UP/policing/social media) set
internal_alternative=false and phrase grounded_message as a normal yes/no confirmation.

Output ONLY a JSON object:
{{
  "candidate_entity": "specific name or empty string",
  "confidence": "high" or "low",
  "internal_alternative": true or false,
  "grounded_message": "the phrased clarification question, per the rules above"
}}
"""
    raw = await call_llm(prompt)
    try:
        parsed = json.loads(clean_json_string(raw))
        if str(parsed.get("confidence", "low")).strip().lower() == "high" and parsed.get("candidate_entity"):
            return {
                "candidate_entity": str(parsed["candidate_entity"]).strip(),
                "grounded_message": str(parsed.get("grounded_message") or "").strip(),
                "internal_alternative": bool(parsed.get("internal_alternative")),
            }
    except Exception:
        pass
    return {"candidate_entity": "", "grounded_message": "", "internal_alternative": False}


async def check_query_manager_node(state: State) -> dict:
    """After query_manager_node: validates if the standalone query correctly captures
    the user's intent based on the conversation history. If not, sets up a retry back to
    query_rewriter. If correct, decides if it needs keyword extraction."""
    original_query = state.get("original_query") or state.get("query", "")
    standalone_query = state["query"]
    messages = state.get("messages", [])
    history = format_history(messages)
    retry_count = state.get("query_manager_retry_count", 0)

    prompt = f"""You are a strict query validator for a police social-media monitoring database.

Your job is to validate whether the GENERATED STANDALONE QUERY correctly and completely represents the user's intent based on the conversation history.

CONVERSATION HISTORY:
{history}

USER'S LATEST PROMPT:
{original_query}

GENERATED STANDALONE QUERY:
{standalone_query}

You have TWO responsibilities:

----------------------------------------
TASK 1 — Validate the standalone query
----------------------------------------

Determine whether the GENERATED STANDALONE QUERY correctly captures the user's intent.

Check the following:

1. Is the standalone query complete and understandable on its own?
2. Did it preserve all important context from the conversation?
   Examples:
   - district
   - city
   - state
   - date
   - time period
   - crime type
   - incident
   - person
   - organization
   - event
   - report type
3. If it is incorrect, explain exactly what information was lost or changed.

----------------------------------------
TASK 2 — Decide whether keyword lookup is required
----------------------------------------

The field "has_table_topic" is ONLY a routing decision.

It DOES NOT mean:
- whether you personally know what the topic means
- whether the abbreviation is recognizable
- whether you can expand the abbreviation

Instead, it means:

"Should the query be sent to keyword_of_post_maker so it can search the recycle_search table for topic keywords?"

Return:

has_table_topic = true

ONLY if the query is asking about a KNOWN, nameable subject/topic — something a
keyword-combination search could actually be built for right now. Examples include:

- crime category
- incident
- protest
- campaign
- movement
- hashtag
- slogan
- event
- organization
- a political party or person referred to BY NAME or by a widely-recognized
  abbreviation (e.g. "BJP", "UPSSSC") — not a bare, unrecognized short form
- operation
- named case
- topic name
- festival
- scheme
- policy
- group
- trend
- social issue

VERY IMPORTANT — bare/unrecognized abbreviations:

If the query's topic signal is a bare abbreviation or acronym you do NOT recognize
and whose full form is not stated anywhere in the query or conversation history
(for example CJP, RHA, XYZ, etc.), it is NOT yet a "known topic" — return:

has_table_topic = false

for that abbreviation. Do NOT try to guess or expand its meaning yourself, and do
NOT set has_table_topic = true just because an abbreviation is present.

(If the SAME query also has other clearly identifiable topic content besides the
unrecognized abbreviation, still return has_table_topic = true based on that other
content — the abbreviation itself will be classified separately.)

Separately (outside this LLM call, and regardless of what you answer here), this node
also deterministically checks the query for exactly this kind of bare abbreviation
against recycle_search. If it's already a known/curated topic there, the query proceeds
to keyword_of_post_maker as normal. If it is NOT found there, the query is classified as
needing clarification and is routed back to query_rewriter's grounded clarification step
BEFORE keyword_of_post_maker runs — keyword_of_post_maker only ever builds the search
combination for an already-classified/resolved topic; it never resolves ambiguous
acronyms itself.

Your job here is ONLY to decide whether keyword lookup should happen at all for a
topic that's already identifiable as-is.

Return:

has_table_topic = false

when the query does NOT require topic lookup, such as:

- counts
- statistics
- dashboards
- summaries
- district_internal_report
- analytics
- report generation
- health checks
- greetings
- help
- metadata queries
- system information
- a bare, unrecognized abbreviation/acronym with no other topic content (see above)

----------------------------------------
TASK 3 — Detect real-world relationship/connection questions
----------------------------------------

Set "is_relationship_query" = true ONLY when the query names TWO OR MORE
distinct, specific entities, incidents, places, or events (e.g. two protest
locations, two organizations, two incidents, two people) AND asks whether/how
they are related — using words like: relationship, connection, link, linked,
related, connected, common thread, tied to, part of the same movement, behind
both.

This is a REAL-WORLD, open-domain reasoning question — it is NOT asking about
account-to-account graph structure (follows/followers), which stays inside
"graph_query" elsewhere in this system. Our database stores posts per single
topic and has no built-in join across two unrelated topics, so this class of
question usually CANNOT be answered from internal data alone and needs an
external check.

Examples of is_relationship_query = true:
"Is there a relationship between the Jantar Mantar protest and the Eco Garden
Lucknow protest?"
"How is the CJP founder connected to the paper-leak agitation in Pune?"
"What's the link between the UP Lekhpal protest and the NEET-UG issue?"

Examples of is_relationship_query = false:
"Show posts about the Jantar Mantar protest" (only one entity)
"Who follows this account?" (account-graph relationship, handled elsewhere)
"What is the relationship between total posts and engagement?" (asking about
data columns, not real-world entities)

If true, also extract "relationship_entities": a list of the specific entity/
incident names involved (2 or more short strings, in the language the user
used).

----------------------------------------
IMPORTANT RULES
----------------------------------------

If the user only changed one attribute, and the standalone query correctly reflects that change, mark it as CORRECT.

Examples:

Previous:
"What are the viral topics of Lucknow"

User:
"today"

Standalone:
"What are the viral topics of Lucknow today."

Result:
is_correct = true

----------------------------------------

Previous:
"Show murder cases in Lucknow"

User:
"Kanpur"

Standalone:
"Show murder cases in Kanpur."

Result:
is_correct = true

----------------------------------------

Do NOT reject a query because it is broad.

If the user asked a broad question,
the standalone query should remain broad.

----------------------------------------

Do NOT reject a query because it asks for all topics.

For example:

"What are the viral topics of Lucknow today?"

is already complete.

----------------------------------------

Examples of has_table_topic = true

"Show posts on Operation Sindoor"

"Show communal violence posts"

"Show cyber fraud posts"

"Show Kanwar Yatra posts"

"Show flood related posts"

"Posts about Yogi"

"Posts about BJP"

"Posts related to Cockroach Janta Party"

(Named/known subjects — a search combination can be built for these right now.)

----------------------------------------

Examples of has_table_topic = false

"How many posts today?"

"Count tweets from yesterday"

"Show district_internal_report"

"Generate district_internal_report"

"Show daily dashboard"

"Show monthly statistics"

"How many FIRs were registered?"

"What is today's ingestion count?"

"What protest made by CJP?"

"Posts about RHA"

(The last two: bare, unrecognized acronyms with no other topic content — these need
classification/clarification before any keyword search makes sense, NOT a direct
keyword_of_post_maker lookup.)

----------------------------------------

Output ONLY a valid JSON object:

{{
    "is_correct": true or false,
    "reason": "If false, explain what is missing. If true, simply say 'correct'.",
    "has_table_topic": true or false,
    "is_relationship_query": true or false,
    "relationship_entities": ["entity one", "entity two"]
}}
"""

    raw = await call_llm(prompt)
    is_correct = True
    reason = ""
    has_table_topic = True
    is_relationship_query = False
    relationship_entities: List[str] = []

    try:
        parsed = json.loads(clean_json_string(raw))
        is_correct = bool(parsed.get("is_correct", True))
        reason = str(parsed.get("reason", ""))
        has_table_topic = bool(parsed.get("has_table_topic", True))
        is_relationship_query = bool(parsed.get("is_relationship_query", False))
        raw_entities = parsed.get("relationship_entities", []) or []
        if isinstance(raw_entities, list):
            relationship_entities = [str(e).strip() for e in raw_entities if str(e).strip()]
        # Only trust the flag when we actually got 2+ entities to search for.
        if len(relationship_entities) < 2:
            is_relationship_query = False
    except Exception:
        pass

    if not is_correct and retry_count < 3:
        add_trace("check_query_manager", user_query=original_query,
                  output=f"RETRY {retry_count+1}/3. Query incorrect: {reason}")
        return {
            "query_manager_feedback": reason,
            "query_manager_retry_count": retry_count + 1,
            "is_query_correct": False
        }

    # ── Live classification ─────────────────────────────────────────────────
    # Deterministic detection (no LLM/DuckDuckGo call yet), runs REGARDLESS of
    # has_table_topic: if the standalone query contains an acronym/short-form
    # (e.g. CJP, RHA) that ISN'T already a curated topic in recycle_search,
    # this node grounds it DIRECTLY — its own separate 7-questions + DuckDuckGo
    # instance (_check_query_manager_grounded_classification) — and ends the
    # turn here, asking the user. No hop back to query_rewriter for this case.
    # Already-known acronyms (e.g. BJP, if recycle_search has it) proceed
    # normally — this only catches genuinely unresolved short forms.
    #
    # DB-FIRST PRIORITY: before EVER calling out to DuckDuckGo, check whether
    # our own analyzed_data already has posts/topics mentioning this term
    # (_term_exists_in_internal_data). A bare word like "ram" (as in "ram
    # mandir") is NOT an unresolved acronym just because it's short and not
    # yet in recycle_search — it's a real subject our database likely already
    # covers. Internal DB always outranks any external source: only fall
    # through to DuckDuckGo grounding when the internal check comes back
    # empty too.
    # Hashtag/mention wording (see query_rewriter_node) already resolved this
    # turn's intent deterministically — force has_table_topic=true and skip
    # the unresolved-short-form check entirely, since a marker like
    # "#TRENDING_HASHTAGS_TODAY" would otherwise get misread as a bare
    # unrecognized acronym and re-trigger a clarification question.
    if state.get("hashtag_intent_detected"):
        add_trace("check_query_manager", user_query=original_query,
                  output="[hashtag intent] forcing has_table_topic=true, skipping unresolved-short-form check")
        return {
            "is_query_correct": True,
            "has_table_topic": True,
            "is_relationship_query": is_relationship_query,
            "relationship_entities": relationship_entities,
        }

    candidate_term = _find_unresolved_short_form(standalone_query, set(state.get("duck_resolved_terms", [])))
    if candidate_term:
        recycle_rows = await asyncio.to_thread(_fetch_recycle_search_entries)
        already_known = any(
            candidate_term.lower() in str(row.get("query_tag", "")).lower()
            for row in recycle_rows
        )
        if not already_known:
            found_internally = await asyncio.to_thread(_term_exists_in_internal_data, candidate_term)
            if found_internally:
                add_trace("check_query_manager", user_query=original_query,
                         output=f"live classification: '{candidate_term}' found in internal DB — "
                                f"skipping DuckDuckGo, treating as a real internal topic")
                already_known = True  # short-circuits the block below, proceeds to normal DB path

        if not already_known:
            grounding = await _check_query_manager_grounded_classification(candidate_term, original_query)

            if grounding["candidate_entity"]:
                candidate = grounding["candidate_entity"]
                add_trace("check_query_manager", user_query=original_query,
                         output=f"live classification: '{candidate_term}' -> candidate '{candidate}'")
                return {
                    "is_query_correct": True,
                    "has_table_topic": has_table_topic,
                    "needs_clarification": True,
                    "answer": grounding["grounded_message"] or CANDIDATE_CONFIRM_FALLBACK[_query_language(original_query)].format(candidate=candidate),
                    "pending_keyword_confirmation": {
                        "term": candidate_term,
                        "resolved_entity": candidate,
                        # Fully replace the acronym with the resolved name — NOT
                        # "acronym (Full Name)" — so the literal short form no
                        # longer appears in the text. Otherwise the (now
                        # case-insensitive) _find_unresolved_short_form would
                        # match it again on the very next turn and re-trigger
                        # this same classification in a loop, since nothing is
                        # persisted to recycle_search to short-circuit it.
                        "resolved_query": standalone_query.replace(candidate_term, candidate),
                        "source": "check_query_manager_live_classify",
                        "internal_alternative": grounding.get("internal_alternative", False),
                    },
                }

            # No confident grounded candidate — do NOT interrupt the user with a
            # clarification question. _find_unresolved_short_form is a broad,
            # case-insensitive regex heuristic (it has to catch lowercase
            # acronyms like "cjp"), so it will occasionally flag an ordinary
            # word that just isn't in the stopword list (e.g. "made", "viral").
            # A real acronym grounds to something concrete via DuckDuckGo; an
            # ordinary word won't. Only ask when there's something real to
            # confirm — otherwise silently proceed with the query as-is.
            add_trace("check_query_manager", user_query=original_query,
                     output=f"live classification: '{candidate_term}' — no confident candidate grounded, not a real acronym — proceeding normally")
    # ─────────────────────────────────────────────────────────────────────

    add_trace("check_query_manager", user_query=original_query,
              output=f"Correct={is_correct}; has_table_topic={has_table_topic}; "
                     f"is_relationship_query={is_relationship_query}; entities={relationship_entities}")
    return {
        "is_query_correct": True,
        "has_table_topic": has_table_topic,
        "is_relationship_query": is_relationship_query,
        "relationship_entities": relationship_entities,
    }


# =========================
# KEYWORD OF POST MAKER — matches query against recycle_search entries
# =========================

def _fetch_recycle_search_entries() -> List[Dict]:
    """Fetch all entries from the recycle_search table for keyword matching."""
    try:
        return execute_sql("SELECT id, query_tag, searched_term FROM recycle_search;")
    except Exception as e:
        print(f"⚠️ Failed to fetch recycle_search entries: {e}")
        return []


def _parse_searched_term_keywords(searched_term: str) -> List[str]:
    """Extract individual keyword strings from a searched_term OR expression.
    Input:  '("दुष्कर्म" OR "बलात्कार" OR "rape" OR "रेप")'
    Output: ['दुष्कर्म', 'बलात्कार', 'rape', 'रेप']
    """
    return re.findall(r'"([^"]+)"', searched_term)


# =========================
# DUCKDUCKGO SHORT-FORM RESOLVER — shared by go_duck_search / go_duck_search_verify
# =========================

_KNOWN_ACRONYMS = {"SQL", "PDF", "USA", "FIR", "OK", "URL", "ID", "UP", "UK", "US"}

# Common query words that must NOT be mistaken for an acronym now that matching
# is case-insensitive (users type acronyms lowercase too, e.g. "cjp" not "CJP").
_COMMON_QUERY_WORDS = {
    "what", "is", "are", "was", "were", "the", "a", "an", "and", "or", "for", "to",
    "in", "on", "of", "at", "by", "with", "from", "this", "that", "these", "those",
    "show", "all", "top", "get", "find", "list", "post", "posts", "today", "now",
    "recent", "latest", "related", "about", "how", "many", "who", "which", "when",
    "where", "why", "trend", "trends", "trending", "news", "detail", "details",
    "more", "give", "me", "any", "some", "count", "total", "each", "per", "did",
    "does", "can", "you", "please", "yes", "no", "based", "on", "made", "make",
    "viral", "hot", "big", "new", "old", "over", "under", "near", "have", "has",
    "had", "want", "need", "help", "tell", "know", "like", "used", "case", "cases",
    "type", "kind", "here", "just", "very", "such", "only", "same", "both", "most",
    "then", "than", "also", "into", "out", "up", "down", "not", "no", "yes", "it",
    "its", "his", "her", "their", "our", "your", "my", "he", "she", "they", "we",
    # People/account/engagement vocabulary that shows up in ordinary questions —
    # without these, an innocent word here gets mistaken for an unresolved
    # acronym and sent out to live DuckDuckGo grounding (see
    # _find_unresolved_short_form / _check_query_manager_grounded_classification).
    "name", "names", "user", "users", "account", "accounts", "handle", "handles",
    "author", "authors", "tweet", "tweets", "tweeted", "retweet", "retweets",
    "retweeted", "reply", "replies", "replied", "like", "likes", "liked",
    "comment", "comments", "commented", "share", "shares", "shared", "view",
    "views", "viewed", "follower", "followers", "following", "profile", "profiles",
    "district", "districts", "topic", "topics", "sentiment", "platform",
    "platforms", "category", "categories", "keyword", "keywords", "report",
    "reports", "ticket", "tickets", "status", "date", "time", "week", "month",
    "year", "day", "days", "hour", "hours",
    # App/domain vocabulary — never real unresolved acronyms in this context.
    "police", "matrix", "social", "media", "monitor", "monitored", "monitoring",
    "search", "data", "record", "records", "engagement", "engagements",
    "incident", "matters", "matter", "wise",
}


def _find_unresolved_short_form(query: str, already_resolved: set) -> str:
    """Finds the first short (2-6 letter) acronym/short-form in the query that
    hasn't already been looked up this turn. Case-insensitive against known/
    already-resolved acronyms and common query words — users often type
    acronyms in lowercase (e.g. "cjp" not "CJP") — but returns the term exactly
    as it appears in the query so downstream string-replace still works.
    Returns "" if none found."""
    already_resolved_lower = {r.lower() for r in already_resolved}
    for candidate in re.findall(r'\b[A-Za-z]{2,6}\b', query):
        lower = candidate.lower()
        if candidate.upper() in _KNOWN_ACRONYMS or lower in already_resolved_lower:
            continue
        if lower in _COMMON_QUERY_WORDS:
            continue
        return candidate
    return ""


def duckduckgo_search_sync(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Lightweight DuckDuckGo search via the no-JS HTML endpoint (no API key needed)."""
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠️ DuckDuckGo search failed: {e}")
        return []

    def _strip_tags(html: str) -> str:
        return re.sub(r'<[^>]+>', '', html).strip()

    results: List[Dict[str, str]] = []
    pattern = re.compile(
        r'class="result__a"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
        re.S,
    )
    for title_html, snippet_html in pattern.findall(resp.text):
        results.append({"title": _strip_tags(title_html), "snippet": _strip_tags(snippet_html)})
        if len(results) >= max_results:
            break
    return results


async def _resolve_short_form_via_duckduckgo(short_form: str) -> str:
    """Searches DuckDuckGo for a short form/acronym and asks the LLM to pick the
    most likely full form from the results. Returns "" if nothing usable is found."""
    results = await asyncio.to_thread(duckduckgo_search_sync, f'"{short_form}" full form organization India')
    if not results:
        return ""

    snippet_block = "\n".join(f"- {r['title']}: {r['snippet']}" for r in results if r["title"] or r["snippet"])
    if not snippet_block:
        return ""

    prompt = f"""You are resolving an abbreviation/short form found in a police social-media
monitoring query. Below are DuckDuckGo search results for the short form "{short_form}".

SEARCH RESULTS:
{snippet_block}

Based on these results, what is the most likely full form of "{short_form}"
(e.g. an organization, party, or entity name)? If the results don't give a
clear answer, return an empty string.

Output ONLY a JSON object:
{{"full_form": "..."}}
"""
    raw = await call_llm(prompt)
    try:
        parsed = json.loads(clean_json_string(raw))
        return str(parsed.get("full_form", "")).strip()
    except Exception:
        return ""


async def go_duck_search_node(state: State) -> dict:
    """NEW — fires only when keyword_of_post_maker found no matching keywords and
    the query contains an unresolved short form/acronym (e.g. CJP). Resolves the
    full form via DuckDuckGo, expands the query, and hands control back to
    keyword_of_post_maker so keyword extraction can retry with the resolved name."""
    query = state["query"]
    short_form = state.get("duck_search_term", "")
    resolved_terms = list(state.get("duck_resolved_terms", []))

    if not short_form:
        add_trace("go_duck_search", output="no short form detected — skipping")
        return {"duck_search_done": True}

    full_form = await _resolve_short_form_via_duckduckgo(short_form)
    resolved_terms.append(short_form)

    if not full_form:
        add_trace("go_duck_search", user_query=query, output=f"'{short_form}' — no resolution found")
        return {"duck_search_done": True, "duck_resolved_terms": resolved_terms}

    expanded_query = query.replace(short_form, f"{short_form} ({full_form})")
    add_trace("go_duck_search", user_query=query, output=f"'{short_form}' → '{full_form}'")
    return {
        "query": expanded_query,
        "duck_search_done": True,
        "duck_resolved_terms": resolved_terms,
    }


async def go_duck_search_verify_node(state: State) -> dict:
    """NEW — same idea, one step later. Fires when keyword_of_post_maker_and_checker
    dropped every candidate keyword and the query still has an unresolved short
    form/acronym (e.g. RHA). Resolves via DuckDuckGo, then hands control back to
    keyword_of_post_maker_and_checker with the expanded query."""
    query = state["query"]
    short_form = state.get("duck_search_verify_term", "")
    resolved_terms = list(state.get("duck_resolved_terms", []))

    if not short_form:
        add_trace("go_duck_search_verify", output="no short form detected — skipping")
        return {"duck_search_verify_done": True}

    full_form = await _resolve_short_form_via_duckduckgo(short_form)
    resolved_terms.append(short_form)

    if not full_form:
        add_trace("go_duck_search_verify", user_query=query, output=f"'{short_form}' — no resolution found")
        return {"duck_search_verify_done": True, "duck_resolved_terms": resolved_terms}

    expanded_query = query.replace(short_form, f"{short_form} ({full_form})")
    add_trace("go_duck_search_verify", user_query=query, output=f"'{short_form}' → '{full_form}'")
    return {
        "query": expanded_query,
        "duck_search_verify_done": True,
        "duck_resolved_terms": resolved_terms,
    }


# =========================
# WEB RELATIONSHIP SEARCH — real-world "is A connected to B" checks via DuckDuckGo
# =========================
# NOTE ON RELIABILITY: DuckDuckGo here is scraped via the no-JS HTML endpoint —
# no API key, no SLA, no ranking/authority signal, and it can go silent on
# breaking regional news faster than Google does. Treat its output as an
# unverified external LEAD, never as a confirmed fact — the prompt below and
# the final answer both say so explicitly. Swap in a paid search API (Bing/
# Serper/Tavily) later by only touching this function.

async def web_relationship_search_node(state: State) -> dict:
    """Fires when check_query_manager flagged the query as a real-world
    relationship/connection question between 2+ named entities that our
    internal DB has no join for. Searches DuckDuckGo for each entity pair,
    then asks the LLM to summarize what the open web does/doesn't support —
    labeled as an external, unverified lead rather than a DB-confirmed fact."""
    query = state["query"]
    entities = state.get("relationship_entities", []) or []

    if len(entities) < 2:
        add_trace("web_relationship_search", user_query=query,
                  output="no 2+ entities to check — skipping")
        return {"relationship_search_done": True, "external_relationship_context": ""}

    search_terms = [
        " ".join(entities),                      # combined
        f"{entities[0]} {entities[1]} connection",
        f"{entities[0]} {entities[1]} relationship",
    ]

    all_results: List[Dict[str, str]] = []
    for term in search_terms:
        try:
            results = await asyncio.to_thread(duckduckgo_search_sync, term, 5)
            all_results.extend(results)
        except Exception as e:
            print(f"⚠️ web_relationship_search term failed ({term}): {e}")

    if not all_results:
        add_trace("web_relationship_search", user_query=query,
                  output="DuckDuckGo returned nothing for any search term")
        return {
            "relationship_search_done": True,
            "external_relationship_context": "",
            "reasoning": (
                "No internal database record links these — and an external web "
                "check did not return any usable results either. This does not "
                "confirm there is no connection, only that neither source could "
                "verify one right now."
            ),
        }

    # De-dupe by title, cap to keep the synthesis prompt small
    seen_titles = set()
    deduped = []
    for r in all_results:
        t = r.get("title", "")
        if t and t not in seen_titles:
            seen_titles.add(t)
            deduped.append(r)
    deduped = deduped[:10]

    snippet_block = "\n".join(f"- {r['title']}: {r['snippet']}" for r in deduped if r.get("title") or r.get("snippet"))

    synth_prompt = f"""You are a research assistant summarizing OPEN-WEB search results
(via DuckDuckGo — not an authoritative or verified source) to help answer a
real-world relationship question for a police social-media monitoring analyst.

USER QUESTION: {query}
ENTITIES BEING CHECKED: {", ".join(entities)}

RAW WEB SEARCH RESULTS (titles + snippets only, unverified):
{snippet_block}

Write 2-4 sentences that:
1. State plainly whether the web results DO or DO NOT support a connection
   between the named entities, and what that connection appears to be if any.
2. Never present this as confirmed fact — call it what it is: an external,
   unverified lead from open web search, not an internal database record.
3. If the results are ambiguous, thin, or off-topic, say so directly rather
   than guessing.

Output ONLY plain text, no markdown, no JSON.
"""
    reasoning = await call_llm(synth_prompt)
    add_trace("web_relationship_search", user_query=query, output=reasoning[:20000])

    return {
        "relationship_search_done": True,
        "external_relationship_context": snippet_block,
        "reasoning": reasoning,
    }


# =========================
# KEYWORD COMBINATION EXPANSION — EN/Hindi spellings + hashtags + related entities
# =========================

async def _generate_keyword_combination_string(query: str, seed_keywords: List[str]) -> str:
    """Expands the topic/entity referenced in the query into every spelling/naming
    variation that could appear in real posts (English + Hindi spelling variants,
    hashtag forms, common misspellings, closely related entity names), formatted as
    a ready-to-use SQL OR-group — same style as recycle_search.searched_term."""
    seed_block = (
        f"\nCandidate keywords found elsewhere in our database for this query "
        f"(these came from a SEPARATE fuzzy tag-matching step and may be WRONG or "
        f"about a different topic entirely — verify each one independently before "
        f"using it; do not trust them by default): "
        f"{json.dumps(seed_keywords, ensure_ascii=False)}"
        if seed_keywords else ""
    )

    prompt = f"""You are a keyword-expansion assistant for a police social-media monitoring database.
The database stores posts in a mix of English, Hindi, and Hinglish, with inconsistent
spellings and hashtag forms. Your job is to expand the main topic/entity/person referenced
in the QUERY below into the actual alternate NAMES/SPELLINGS it could appear under in real
posts, so a SQL LIKE search doesn't miss it under a different spelling.

QUERY:
{query}
{seed_block}

Include ONLY, where relevant to the query's subject:
- English spelling variants and common misspellings of the NAME itself
- Hindi (Devanagari) transliterations/spelling variants of the NAME itself
- Hashtag forms of the NAME itself (no spaces, CamelCase, e.g. #TopicName)
- Specific, real, closely related named people/organizations/events directly tied to this
  topic (e.g. its founder, its official body, a directly linked incident) that a post might
  mention BY NAME instead of the topic name

STRICT RULES:
- Every term must be a NAME or a spelling/hashtag variant of a name. Do NOT output generic
  category/subtopic phrases like "X Admission", "X Canteen", "X Sports Day", "X News",
  "X Update", "X Result", "X Placement" — these are not name variants and must be excluded.
- Every term must be a spelling/hashtag variant of THE SAME entity in the query, or a
  specific named person/org/event directly tied to it. Do NOT output generic standalone
  words (e.g. "आंदोलन", "प्रदर्शन", "movement", "protest") that aren't unique to this
  specific topic — a bare generic word will match hundreds of unrelated topics via LIKE.
- If a candidate keyword from the list above looks like it belongs to a DIFFERENT subject
  than the query (wrong event, wrong person, wrong category), DROP it. Do not include it
  just because it was listed as a candidate.
- Do NOT invent facts, people, or events you are not confident are real.
- Maximum 25 terms. Quality over quantity — a short, precise list beats a long, noisy one.
- If the query has no specific named topic/entity (e.g. it's a plain count or dashboard
  request), return an empty list.
- A broad category/incident-type word (e.g. "protest", "crime", "riot", "murder",
  "accident") is NOT a specific named topic/entity, even when combined with a place name
  ("protest in uttar pradesh", "crime in Lucknow"). Do NOT fabricate compound phrases like
  "up protest", "uttar pradesh riot", "protest march up" — these are not real name
  variants, nobody writes post titles that way, and they will never match real data.
  For these broad/generic queries, return an empty list; the category/keyword filters
  built elsewhere in the pipeline already cover the generic subject term.

BAD example — do NOT do this (query "protest in uttar pradesh" has no specific named
incident — "protest" is a category, "uttar pradesh" is the whole state, not a real place a
post title would combine it with):
{{"combination_terms": ["protest in uttar pradesh", "up protest", "uttar pradesh protest", "uttar pradesh riot", "up demonstration"]}}
→ correct output is an empty list: {{"combination_terms": []}}

GOOD example — topic "Jauhar University":
{{"combination_terms": ["Jauhar University", "Mohammad Ali Jauhar University", "जौहर यूनिवर्सिटी", "मोहम्मद अली जौहर विश्वविद्यालय", "जौहर", "जोहर", "Johar", "Jouhar", "मोहम्मद अली जौहर", "आजम खान", "Azam Khan", "JauharUniversity", "SaveJauharUniversity"]}}

BAD example — do NOT do this (generic categories, not name variants):
{{"combination_terms": ["Jauhar University Admission", "Jauhar University Canteen", "Jauhar University Sports Day", "Jauhar University News", "Jauhar University Update"]}}

BAD example — do NOT do this (candidate keywords from an unrelated topic, kept just because
they were listed as candidates — e.g. query is about "Kawar Yatra" but candidates included
farmer-union/election terms from a different protest topic):
{{"combination_terms": ["कावर यात्रा", "किसान यूनियन", "पंचायत चुनाव", "आंदोलन"]}}
→ correct output would drop "किसान यूनियन", "पंचायत चुनाव", and bare "आंदोलन" — none of them
  are Kawar Yatra name variants, they belong to an unrelated farmer/election protest topic.

Output ONLY a JSON object:
{{
  "combination_terms": ["term1", "term2", ...]
}}
"""
    raw = await call_llm(prompt)
    try:
        parsed = json.loads(clean_json_string(raw))
        terms = [str(t).strip() for t in parsed.get("combination_terms", []) if str(t).strip()]
    except Exception:
        terms = []

    # Trust only what the LLM actually returned — do NOT force-merge the raw seed
    # keywords back in. The seeds came from a separate, unverified matching step
    # (recycle_search tag match) and may belong to a completely different topic;
    # forcing them into the SQL WHERE clause regardless of relevance is what caused
    # unrelated topics to get summed into a count (e.g. "Kawar Yatra" pulling in
    # farmer-union/panchayat-election posts). The LLM above already decides which
    # seed terms are legitimately relevant and includes those on its own.
    seen: set = set()
    ordered: List[str] = []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            ordered.append(t)
        if len(ordered) >= 30:
            break

    if not ordered:
        return ""
    return "(" + " OR ".join(f'"{t}"' for t in ordered) + ")"


# =========================
# KEYWORD_OF_POST_MAKER_NODE — 2 parallel branches (db_recycle_search,
# related_words) + join. See query_pipeline_flow.html for the design doc.
# =========================

async def _db_recycle_search_branch(query: str) -> dict:
    """Branch 1 — matches the query against curated recycle_search tags.
    Unchanged from the original sequential implementation, just extracted so it
    can run concurrently with the other two branches via asyncio.gather."""
    recycle_rows = await asyncio.to_thread(_fetch_recycle_search_entries)
    if not recycle_rows:
        return {"matched_tags": [], "keywords": []}

    tag_list = []
    tag_map = {}  # query_tag -> searched_term
    for row in recycle_rows:
        tag = str(row.get("query_tag", "")).strip()
        searched = str(row.get("searched_term", "")).strip()
        if tag and tag not in tag_map:
            tag_list.append(tag)
            tag_map[tag] = searched

    prompt = f"""You are a keyword-matching assistant for a police social-media monitoring database.

Given the user's QUERY, find which of the AVAILABLE TAGS are relevant to this query.
Match based on meaning — the user might use English, Hindi, or Hinglish.

QUERY:
{query}

AVAILABLE TAGS:
{json.dumps(tag_list, ensure_ascii=False)}

Rules:
1. Select ONLY tags whose subject directly matches the user's query intent.
2. Do NOT select tags that are unrelated even if they share a common word.
3. If no tag matches the query, return an empty list.
4. Return at most 3 most relevant tags.

Output ONLY a JSON object:
{{
  "matched_tags": ["tag1", "tag2", ...]
}}
"""
    raw = await call_llm(prompt)
    matched_tags: List[str] = []
    try:
        parsed = json.loads(clean_json_string(raw))
        matched_tags = [str(t) for t in parsed.get("matched_tags", []) if str(t) in tag_map]
    except Exception:
        matched_tags = []

    keywords: List[str] = []
    for tag in matched_tags:
        keywords.extend(_parse_searched_term_keywords(tag_map[tag]))

    seen: set = set()
    unique_keywords: List[str] = []
    for kw in keywords:
        if kw.lower() not in seen:
            seen.add(kw.lower())
            unique_keywords.append(kw)

    return {"matched_tags": matched_tags, "keywords": unique_keywords}


async def _related_words_branch(query: str) -> List[str]:
    """Branch 2 — generates phonetic variants, common typos, and closely
    associated terms for the query's topic. Independent of recycle_search
    (branch 1) — the fuzzy-matching net that catches misspellings a plain LIKE
    search would miss."""
    prompt = f"""For the main topic/entity/name in this query, generate fuzzy match variants
that could appear in real social-media posts:

QUERY: {query}

Generate up to 12 terms across these categories:
- Phonetic variations of the name
- Common typos of the name
- Closely associated terms (directly tied to this specific topic only)

If the query has no specific named topic (e.g. a plain count/dashboard request), return an
empty list.

Output ONLY a JSON object:
{{"variants": ["term1", "term2", ...]}}
"""
    raw = await call_llm(prompt)
    try:
        parsed = json.loads(clean_json_string(raw))
        return [str(t).strip() for t in parsed.get("variants", []) if str(t).strip()][:12]
    except Exception:
        return []


async def keyword_of_post_maker_node(state: State) -> dict:
    """Runs two independent research branches in parallel — db_recycle_search
    (curated tag match) and related_words (fuzzy variants) — then joins them
    into one keyword_combination_string. Only reached when check_query_manager
    found a table/topic reference.

    By this point the topic is already classified: an unresolved acronym/short
    form not already in recycle_search gets caught, grounded, and asked about
    directly by check_query_manager itself, ending the turn there BEFORE
    reaching here (see _check_query_manager_decision). This node's only job is
    building the best possible search combination for an already-known topic —
    it does not resolve ambiguity or ask the user anything itself."""
    query = state["query"]

    duck_search_term = ""
    if not state.get("duck_search_done"):
        duck_search_term = _find_unresolved_short_form(query, set(state.get("duck_resolved_terms", [])))

    db_result, related_variants = await asyncio.gather(
        _db_recycle_search_branch(query),
        _related_words_branch(query),
    )
    unique_keywords = db_result["keywords"]

    seed_keywords = list(unique_keywords)
    for term in related_variants:
        if term and term not in seed_keywords:
            seed_keywords.append(term)

    going_to_duck_search = not unique_keywords and not state.get("duck_search_done") and bool(duck_search_term)
    keyword_combination_string = ""
    if not going_to_duck_search:
        keyword_combination_string = await _generate_keyword_combination_string(query, seed_keywords)

    add_trace("keyword_of_post_maker", user_query=query,
             output=f"matched_tags={db_result['matched_tags']}; keywords={unique_keywords[:20]}; "
                    f"related_variants={related_variants[:10]}"
                    + (f"; unresolved_short_form={duck_search_term}" if duck_search_term else "")
                    + (f"; keyword_combination_string={keyword_combination_string[:200]}" if keyword_combination_string else ""))
    return {
        "keywords": unique_keywords,
        "duck_search_term": duck_search_term,
        "keyword_combination_string": keyword_combination_string,
    }


# =========================
# KEYWORD OF POST MAKER AND CHECKER — strict validation against the query
# =========================

async def keyword_of_post_maker_and_checker_node(state: State) -> dict:
    """Strictly validates that the keywords from recycle_search actually belong
    to the user's query subject. Drops anything that does not directly relate."""
    query = state["query"]
    keywords = state.get("keywords", [])

    if not keywords:
        duck_search_verify_term = ""
        if not state.get("duck_search_verify_done"):
            duck_search_verify_term = _find_unresolved_short_form(query, set(state.get("duck_resolved_terms", [])))
        add_trace("keyword_of_post_maker_and_checker", user_query=query,
                 output="no keywords to check")
        return {
            "keywords_checked": [],
            "keyword_notes": "no keywords received",
            "duck_search_verify_term": duck_search_verify_term,
        }

    prompt = f"""You are a strict keyword validator for a police social-media monitoring database.

QUERY:
{query}

CANDIDATE KEYWORDS (fetched from recycle_search database):
{json.dumps(keywords[:50], ensure_ascii=False)}

Your task is to keep ONLY the keywords that directly belong to the user's query subject.

Strict Rules:
1. Keep keywords that are directly related to what the user is asking about.
2. Remove keywords that are from completely unrelated categories or subjects.
3. Remove keywords that only partially or loosely match the query intent.
4. If the query is about a specific crime type (e.g. "rape"), keep all terms related
   to that crime type but drop terms from unrelated crime categories.
5. If the query includes a district or location filter, do NOT drop crime/topic
   keywords — only drop keywords from completely unrelated categories.
6. Be strict — when in doubt, drop the keyword.

Output ONLY a JSON object:
{{
  "keywords_checked": ["keyword1", ...],
  "keyword_notes": "brief note on what was dropped and why"
}}
"""

    raw = await call_llm(prompt)
    keywords_checked = keywords
    keyword_notes = ""
    try:
        parsed = json.loads(clean_json_string(raw))
        keywords_checked = [str(k) for k in parsed.get("keywords_checked", keywords)]
        keyword_notes = str(parsed.get("keyword_notes", ""))
    except Exception:
        keywords_checked = keywords
        keyword_notes = "parse error — passing candidates through unchecked"

    # No keywords survived validation — check if the query has an unresolved short
    # form/acronym (e.g. RHA) worth resolving via go_duck_search_verify.
    duck_search_verify_term = ""
    if not keywords_checked and not state.get("duck_search_verify_done"):
        duck_search_verify_term = _find_unresolved_short_form(query, set(state.get("duck_resolved_terms", [])))

    add_trace("keyword_of_post_maker_and_checker", user_query=query,
             output=f"keywords_checked={keywords_checked[:20]}; notes={keyword_notes}"
                    + (f"; unresolved_short_form={duck_search_verify_term}" if duck_search_verify_term else ""))
    return {
        "keywords_checked": keywords_checked,
        "keyword_notes": keyword_notes,
        "duck_search_verify_term": duck_search_verify_term,
    }





# =========================
# TABLE SELECTOR — picks relevant tables from DB_SCHEMA_YAML
# =========================

async def table_selector_node(state: State) -> dict:
    """Reads each table's use_case in DB_SCHEMA_YAML and picks only the tables
    this turn actually needs, with a reason."""
    query = state["query"]
    hint = state.get("content_index_hint", "")
    hint_block = f"\nCONTENT INDEX HINT (from a previous retry — data matching the query was found in these tables/columns):\n{hint}\n" if hint else ""

    prompt = f"""You are an expert database table selector for the UP Police Social Media Monitoring database.

Your task is to analyze the user's query and select ONLY the minimum required database tables needed to answer it correctly.

You must understand table relationships and select supporting lookup tables when required.

DATABASE SCHEMA:
{DB_SCHEMA_YAML}
{hint_block}

USER QUERY:
{query}

TABLE SELECTION RULES:

1. Select tables based on the user's actual information need, not only keywords.

2. Use `topic` when the user asks for:
   - incidents
   - topics
   - summaries
   - category-wise topic analysis
   - district-level incident overview
   - topic statistics

3. Use `analyzed_data` when the user asks for:
   - individual posts
   - post text/content
   - post URLs
   - authors
   - usernames
   - sentiments
   - locations
   - police stations
   - posts related to an incident/topic

4. Use `post_bank` when the user asks for:
   - raw post details
   - engagement metrics stored on original posts
   - likes, retweets, comments, views
   - connecting posts with engagement/interactions

5. Use `post_users` when the user asks about:
   - account/person details
   - follower information
   - profile information
   - actor-level analysis

6. Use engagement tables only when the user specifically asks:
   - who liked a post
   - who retweeted
   - who replied
   - who interacted

7. For monitored profile tagging/mention queries:
   Examples:
   - "Which posts tag DGP?"
   - "Show posts mentioning Traffic Police"
   - "Find posts where @username is mentioned"

   ALWAYS select:
   - `monitor_profiles` to identify the monitored account username
   - `analyzed_data` to find matching posts using mention/tag information

   Relationship:
   monitor_profiles.user_name
   ->
   analyzed_data.mention_ids_extracted

   Do NOT select only monitor_profiles because it does not contain post data.

8. For category/profile monitoring queries:
   - "Which profiles are monitored?"
   - "Show DGP monitored accounts"
   Use only `monitor_profiles`.

9. For taxonomy/category explanation:
   Use:
   - broad_category
   - sub_category
   - keywords
   - hashtags
   depending on the query.

10. For ticket/dashboard queries:
   Use only ticket-related tables described in schema:
   - ticket_raised_table
   - thana_matrix
   - district_internal_report
   when required.

11. Never select tables only because a column name appears similar.
    Select tables only if their data is required to answer the user's question.

12. Always choose the smallest possible set of tables.
    Avoid unnecessary joins.

13. If a query requires joining tables, select all required tables needed for the final answer.

14. Use CONTENT INDEX HINT if available:
    - Prefer tables/columns mentioned in the hint when they match the query.
    - Do not blindly follow the hint if it conflicts with the schema.

OUTPUT FORMAT:
Return ONLY valid JSON.

Format:
{{
  "selected_tables": ["table1", "table2"],
  "reason": "brief explanation of why these tables are required"
}}

Do not include markdown.
Do not include SQL.
Do not include extra explanation.
"""

    raw = await call_llm(prompt)
    selected_tables = []
    table_reason = ""
    try:
        parsed = json.loads(clean_json_string(raw))
        selected_tables = parsed.get("selected_tables", [])
        table_reason = parsed.get("reason", "")
    except Exception as e:
        print(f"⚠️ table_selector_node: could not parse JSON ({e}) — using all tables")
        selected_tables = ["topic", "analyzed_data", "post_bank"]
        table_reason = "fallback: parse error"

    add_trace("table_selector", user_query=query,
             output=f"tables={selected_tables}; reason={table_reason}")
    return {"selected_tables": selected_tables, "table_reason": table_reason}


# =========================
# SQL JUDGE — checks if the SQL actually answers the query
# =========================

async def sql_judge_node(state: State) -> dict:
    """A second pass over the SQL: checks whether it actually answers the
    standalone query. On matches=false, the graph loops back to table_selector."""
    query = state["query"]
    sql = state.get("sql", "")
    retry_count = state.get("retry_count", 0)

    prompt = f"""You are a SQL quality judge for a police social-media monitoring database.

Given the user's QUERY and the generated SQL, determine whether the SQL correctly
answers the query. Check for:
- Wrong table used
- Missing filters (district, date, category)
- Wrong aggregation
- Missing JOIN conditions
- SQL that runs fine but answers a different question
- **Virality/Trending**: If the user asks for plural "viral topics", returning multiple rows via `ORDER BY total_no_of_post DESC LIMIT...` is CORRECT. Do NOT penalize it or demand a `MAX()` subquery, because `MAX()` would incorrectly restrict the result to a single topic.
- **Case Sensitivity**: MySQL string matching (`LIKE`, `=`) is case-insensitive by default. Do NOT reject a query or require `UPPER()`/`LOWER()` functions just because of case differences (e.g., 'Lucknow' vs 'LUCKNOW').

USER QUERY:
{query}

GENERATED SQL:
{sql}

Output ONLY a JSON object:
{{
  "matches": true or false,
  "reason": "brief explanation of why it matches or doesn't"
}}
"""

    raw = await call_llm(prompt)
    matches = True
    reason = ""
    try:
        parsed = json.loads(clean_json_string(raw))
        matches = bool(parsed.get("matches", True))
        reason = str(parsed.get("reason", ""))
    except Exception:
        matches = True  # on parse failure, let it through
        reason = "parse error — defaulting to pass"

    # Cap retries at 2
    if not matches and retry_count >= 2:
        matches = True
        reason += " (retry limit reached — passing through)"

    new_retry = retry_count + 1 if not matches else retry_count

    add_trace("sql_judge", user_query=query,
             output=f"matches={matches}; reason={reason}; retry={new_retry}")
    return {"sql_matches": matches, "sql_match_reason": reason, "retry_count": new_retry}


# =========================
# LLM VALIDATOR — batch-processes rows for detailed summary answers
# =========================

async def llm_validator_node(state: State) -> dict:
    """Batch-processes SQL result rows through the LLM to extract relevant
    information for the user's query. Used when query_intent is 'summary'
    (the user wants to read/understand row content, not just counts).

    - Truncates to 100 rows max
    - Processes in batches of 10 with up to 5 concurrent LLM calls
    - Combines all extracted chunks into a final validated context
    """
    print("llm_validator_node")
    combined_query = f"{state.get('original_query', '')} {state.get('corrected_query', '')} {state.get('query', '')}"

    rows = state.get("rows", [])
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    now_iso = now.isoformat(timespec="seconds")

    if len(rows) > 100:
        print(f"⚠️ Truncating SQL results from {len(rows)} to top 100 to prevent excessive LLM validator calls.")
        rows = rows[:100]

    if not rows:
        add_trace("llm_validator", user_query=state["query"], output="no rows")
        return {"validated_sql_context": ""}

    BATCH_SIZE = 10
    PARALLEL_LIMIT = 5
    semaphore = asyncio.Semaphore(PARALLEL_LIMIT)

    def build_batch_prompt(batch):
        batch_text = ""
        for i, row in enumerate(batch):
            clean_row = dict(row)
            clean_row.pop("post_bank_post_url", None)
            clean_row.pop("source_type", None)
            batch_text += f"""\nRow {i + 1}\n{json.dumps(clean_row, ensure_ascii=False, default=str, indent=2)}\n\n--------------------------------------------------\n"""

        return f"""Current Date: {today}
Yesterday: {yesterday}
Current Time: {now_iso}

You are an expert police intelligence analyst.

Your task is to answer the user's question ONLY using the SQL result rows provided below.

=========================================================
USER QUESTION
=========================================================

{state["query"]}

=========================================================
SQL RESULT ROWS
=========================================================

{batch_text}

=========================================================
INSTRUCTIONS
=========================================================

The SQL query has already been executed.

Your job is to carefully analyze all the provided rows and answer the user's question using ONLY the information present in those rows.

Strict Rules:

1. Read every row before generating the answer.
2. Use ONLY information explicitly present in the SQL result rows.
3. Never use outside knowledge.
4. Never guess, infer, speculate, or assume missing information.
5. Ignore rows that are unrelated to the user's question.
6. Ignore duplicate records and repeated information.
7. If multiple rows describe the same incident, event, person, or post, merge them into a single concise statement.
8. Preserve names, dates, locations, and other facts exactly as they appear.
9. Do not invent or modify any facts.
10. Do not mention SQL, databases, tables, rows, columns, queries, or internal field names except the field `id`.
11. Keep the answer concise while including all relevant information.
12. For every incident, post, or distinct event mentioned, begin the sentence with its exact `id` enclosed in square brackets.

Example:
[12345] A robbery was reported near Hazratganj on 12 June 2025.
[67890] Two individuals were arrested for illegal arms possession.

12a. If the rows include author/username, platform (post_bank_core_source),
a post URL, and post text — and the user's question is about WHO posted
something (e.g. negative/critical posts against an official) — state, per
item: the author name/handle, the platform, the link (only if the URL field
is actually present and non-empty; if it is empty say "link not available",
never invent one), and what they actually posted. Do not collapse this into
just a count of how many posts exist.

13. If the user requests all matching incidents or posts, include every relevant item.
14. Otherwise, combine similar information into a concise response without repetition.
15. Do not output duplicate ids.
16. If the provided rows do not contain information that answers the user's question, return an empty string.
17. If none of the rows are relevant, return an empty string.

=========================================================
OUTPUT RULES
=========================================================

Return ONLY the final answer.

Do NOT include:
- Markdown
- JSON
- XML
- YAML
- Code fences
- Headings
- Explanations
- Reasoning
- Introductory or concluding text
- Messages such as "No data found", "No relevant information", "Not available", or similar.

The output must be either:
- The final answer based only on the provided rows, or
- An empty string.
"""

    # Build all batches
    batches = [
        rows[start:start + BATCH_SIZE]
        for start in range(0, len(rows), BATCH_SIZE)
    ]

    async def process_batch(batch_idx, batch):
        async with semaphore:
            prompt = build_batch_prompt(batch)
            result = (await call_llm(prompt)).strip()
            start = batch_idx * BATCH_SIZE
            print(f"Batch {start + 1}-{start + len(batch)}")
            print(result)
            return result

    # Fire all batches in parallel (up to PARALLEL_LIMIT at once)
    results = await asyncio.gather(*[
        process_batch(i, batch) for i, batch in enumerate(batches)
    ])

    extracted_chunks = [r.strip() for r in results if r.strip()]

    # Combine all extracted information into a final answer
    if extracted_chunks:
        final_prompt = f"""Current Date: {today}
Yesterday: {yesterday}
Current Time: {now_iso}

You are an expert police intelligence analyst.

Your task is to answer the user's question by understanding the intent behind the query and using ONLY the extracted information provided below.

The answer must be complete enough to satisfy the user's request, but must not include unrelated, unnecessary, or extra information.

=========================================================
USER QUESTION
=========================================================

{state["query"]}

=========================================================
EXTRACTED INFORMATION
=========================================================

{chr(10).join(extracted_chunks)}

=========================================================
INSTRUCTIONS
=========================================================

First understand what the user is asking for:
- Identify the main subject, person, incident, location, time period, or information type requested.
- Determine what details are actually needed to answer the query.
- Include only information that helps answer that specific request.

Strict Rules:

1. Use ONLY the extracted information.
2. Never use outside knowledge.
3. Never guess, assume, or infer missing facts.
4. Do not provide background information unless it directly answers the query.
5. Do not include unrelated incidents, people, locations, or events.
6. Do not repeat the same information multiple times.
7. If multiple extracted items describe the same incident, merge them into one complete answer.
8. If multiple IDs belong to the same incident, keep all IDs together.
9. Every incident or post mentioned must start with its exact `[ID]`.
10. Preserve names, dates, locations, police stations, districts, and other facts exactly as provided.
11. If the user asks for a specific field or detail, provide only that detail along with minimum required context.
12. If the user asks for a summary, provide a concise summary containing the important facts only.
13. If the user asks for a list, provide only the matching items.
13a. If the extracted information includes an author/handle, platform, and
link for a "who posted this" style question, preserve that structure per
item (author — platform — link if present — what they posted); do not
compress it down to a bare count.
14. Do not add explanations about your analysis process.
15. If the extracted information does not answer the user's question, return an empty string.

=========================================================
OUTPUT RULES
=========================================================

Return ONLY the final answer.

Do NOT include:
- Markdown
- JSON
- Headings
- Explanations
- Reasoning
- SQL/database references
- Statements like "No information found" or "Not available"

Output must be:
- A direct answer to the user's question, or
- An empty string.
"""

        final_context = (await call_llm(final_prompt)).strip()
    else:
        final_context = ""

    print("Validated SQL Context:")
    print(final_context)

    add_trace("llm_validator", user_query=state["query"],
             prompt="Batch extraction of SQL information",
             output=final_context[:300])

    return {"validated_sql_context": final_context}


# =========================
# JUDGE AND REASON — reasons over the returned rows
# =========================

async def judge_and_reason_node(state: State) -> dict:
    """Reasons over the returned rows against the standalone query — what they
    show, whether the result set answers it, and what's worth calling out."""
    query = state["query"]
    sql = state.get("sql", "")
    rows = state.get("rows", [])
    rows_preview = json.dumps(rows[:30], default=str, ensure_ascii=False)
    content_index_hint = state.get("content_index_hint", "")

    hint_block = ""
    if not rows and content_index_hint:
        hint_block = f"""
NEAR-MATCH CONTENT (found via similarity search over the content index, NOT a
confirmed SQL match against the requested criteria — treat these only as
unconfirmed, possibly-related leads, never as the actual answer, count, or proof):
{content_index_hint}
"""

    prompt = f"""You are an analytical reasoning agent for the UP Police Social Media Monitoring system.

Your job is to evaluate whether the SQL result actually answers the user's query.
Reason only from the returned rows and the executed SQL.

USER QUERY:
{query}

EXECUTED SQL:
{sql}

RESULT ROWS (first 30):
{rows_preview}

TOTAL ROWS:
{len(rows)}

{hint_block}

REASONING RULES:

1. Explain what the returned rows actually represent.
   Examples:
   - If rows contain posts, mention post-level findings.
   - If rows contain topics, mention incident/topic-level findings.
   - If rows contain profiles, mention profile-level findings.
   - If rows contain engagement, mention engagement-level findings.

2. Check whether the result fully answers the user's request.
   - If yes, state that it answers the query.
   - If partially answered, explain what is missing.
   - If not answered, clearly state the limitation.

3. Never assume information that is not present in the rows.
   Do not infer:
   - hidden posts
   - missing users
   - platform details
   - engagement numbers
   - relationships not returned by SQL

4. For mention/tag queries:
   Example:
   "Which posts tag DGP?"
   Verify that returned rows actually represent tagged/mentioned posts.
   Do not describe monitor_profiles rows alone as posts.

5. For zero results:
   - Clearly say that no exact database match was found.
   - If NEAR-MATCH CONTENT is available, describe it only as possible related content requiring human review.
   - Never convert near-match content into counts or confirmed findings.

5a. For ONE OR A FEW results (TOTAL ROWS is 1-5):
   - You MUST restate the actual field values present in those rows — topic
     title/name, category, district/zone, date, counts, status, or any other
     column that is actually populated — directly in your reasoning.
   - It is NEVER acceptable to say only "exactly N matching item(s) was/were
     found" or "no additional details are available" when the row itself
     contains data you have not repeated. The row IS the additional detail —
     if it has a title, category, or date, say what that title/category/date
     is.
   - Only say details are unavailable if the relevant column in the actual
     row is genuinely NULL/empty — never say it because you chose to
     summarize instead of stating the value.
   - This applies even when the result is a single topic-level row with no
     joined post text — a topic row still carries its own title, category,
     district, and counts, and those must be surfaced, not withheld.

6. Highlight useful observations only when supported by data:
   - dominant categories
   - high engagement
   - repeated actors
   - common locations
   - empty results
   - unusual patterns

7. Keep the reasoning concise and suitable for a final answer generation step.

OUTPUT:
Return ONLY plain text.
Length: 2-4 sentences.
No JSON.
No markdown.
No bullet points.
"""

    reasoning = await call_llm(prompt)
    add_trace("judge_and_reason", user_query=query, output=reasoning[:20000])
    return {"reasoning": reasoning}


# =========================
# ANSWER — writes the final user-facing reply
# =========================

async def answer_node(state: State) -> dict:
    """Turns judge_and_reason's reasoning OR llm_validator's context into the 
    plain-language reply the user actually sees — last stop before END."""
    query = state["query"]
    reasoning = state.get("reasoning", "")
    validated_sql_context = state.get("validated_sql_context", "")
    rows = state.get("rows", [])
    sql = state.get("sql", "")
    rows_preview = json.dumps(rows[:20], default=str, ensure_ascii=False)
    intent = state.get("query_intent", "count")

    # ── Pagination phrasing note ─────────────────────────────────────────
    pagination_note = ""
    if state.get("is_pagination_request"):
        if state.get("pagination_exhausted"):
            pagination_note = (
                "\nNOTE: The user asked for more results ('show more'/'next N'), but "
                "there are no additional rows left — everything matching the original "
                "query has already been shown in earlier turns. Tell the user there are "
                "no more results to show, in the style of 'that's all N results' rather "
                "than implying the search itself found nothing.\n"
            )
        else:
            pagination_note = (
                f"\nNOTE: This is a 'show more'/'next N' continuation of the previous "
                f"result list. DATA ROWS below are the NEXT {len(rows)} additional rows "
                f"(not a repeat of what was already shown) — present them as continuing "
                f"the previous list, don't reintroduce the topic from scratch.\n"
            )

    if state.get("relationship_search_done"):
        feedback_block = ""
        if state.get("answer_feedback"):
            feedback_block = f"\nCRITICAL FEEDBACK FROM PREVIOUS DRAFT:\n{state['answer_feedback']}\nYou MUST fix the above issues.\n"

        prompt = f"""You are the final answer writer for a police social-media monitoring assistant.

The user asked a real-world relationship/connection question between named
entities. Our internal database has no cross-topic join for this, so an
external open-web search (DuckDuckGo) was run instead. Below is the synthesis
of that search.
{feedback_block}
- Be concise but complete (2-5 sentences).
- If the user asked in Hindi, reply in Hindi. Otherwise reply in English.
- Clearly mark this as coming from an external web check, not the internal
  database — e.g. "Our internal records don't show a link, but open-web
  sources indicate..." Never state it as a confirmed database fact.
- Do not fabricate any detail beyond what's in the synthesis below.

USER QUERY: {query}
WEB SEARCH SYNTHESIS: {reasoning}

Write your answer:
"""
    elif intent == "summary" and validated_sql_context:
        feedback_block = ""
        if state.get("answer_feedback"):
            feedback_block = f"\nCRITICAL FEEDBACK FROM PREVIOUS DRAFT:\n{state['answer_feedback']}\nYou MUST fix the above issues and include the missing details in your new answer.\n"

        prompt = f"""You are the final answer writer for a police social-media monitoring assistant.

Using the EXTRACTED CONTEXT below, write a clear, helpful, plain-language answer for the user.
{feedback_block}
- Be concise but complete.
- If the user asked in Hindi, reply in Hindi. Otherwise reply in English.
- Use ONLY the provided extracted context.
- Never show raw SQL to the user.
{pagination_note}
USER QUERY: {query}
EXTRACTED CONTEXT: {validated_sql_context}

Write your answer:
"""
    else:
        content_index_hint = state.get("content_index_hint", "")
        hint_block = ""
        if not rows and content_index_hint:
            hint_block = f"""
NEAR-MATCH CONTENT (from similarity search over the content index — NOT a
confirmed database match; present these only as possibly-related leads for a
human to review, never as the actual count/answer):
{content_index_hint}
"""

        feedback_block = ""
        if state.get("answer_feedback"):
            feedback_block = f"\nCRITICAL FEEDBACK FROM PREVIOUS DRAFT:\n{state['answer_feedback']}\nYou MUST fix the above issues and include the missing details in your new answer.\n"

        prompt = f"""You are the final answer writer for a police social-media monitoring assistant.

Using the REASONING (from an analysis step) and the actual data rows, write a
clear, helpful, plain-language answer for the user.
{feedback_block}
- Be concise but complete.
- If the user asked in Hindi, reply in Hindi. Otherwise reply in English.
- Include specific numbers, names, and dates from the data.
- If there are many rows, summarize the key findings.
- If TOTAL ROWS is 1-5, you MUST state the actual field values from those
  rows (title/name, category, district/zone, date, counts, status, etc.) as
  the core of your answer. Do NOT reply with only "a matching item was
  found" or "no additional details are available" — if REASONING or DATA
  ROWS already contains the details, put them in the answer. Only say a
  detail is unavailable when the corresponding field is genuinely empty in
  DATA ROWS, never as a substitute for stating a value that IS present.
- If TOTAL ROWS is 0 and NEAR-MATCH CONTENT is provided below, clearly state
  that no exact database match was found, then list the near-match content as
  possibly-related leads worth a human review — never state them as a
  confirmed count.
- Never show raw SQL to the user.
{pagination_note}
USER QUERY: {query}
REASONING: {reasoning}
DATA ROWS (first 20): {rows_preview}
TOTAL ROWS: {len(rows)}
{hint_block}
Write your answer:
"""

    answer = await call_llm(prompt)
    
    # Append post sources if any were extracted
    post_metadata = state.get("post_metadata", {})
    if post_metadata:
        sources_text = "\n\n--- Source Links ---\n"
        # Deduplicate URLs
        seen_urls = set()
        for meta in post_metadata.values():
            url = meta.get("url")
            source = meta.get("source") or "Link"
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources_text += f"- [{source}] {url}\n"
        if seen_urls:
            answer += sources_text
            
    add_trace("answer", user_query=query, output=answer[:20000])
    return {"answer": answer}


async def answer_checker_node(state: State) -> dict:
    """Checks if the final answer dropped any specific details (like usernames, 
    locations, followers) requested by the user but available in the data."""
    query = state["query"]
    answer = state.get("answer", "")
    reasoning = state.get("reasoning", "")
    validated_sql_context = state.get("validated_sql_context", "")
    rows_preview = json.dumps(state.get("rows", [])[:20], default=str, ensure_ascii=False)
    
    prompt = f"""You are an Answer Checker for a police social-media monitoring assistant.
Your job is to verify that the drafted answer includes all specific details requested by the user, provided those details exist in the retrieved data/reasoning.

Often, the assistant summarizes too much and drops specific details like:
- Usernames
- Locations
- Follower counts
- Specific names or tags

Check if the answer is missing any such details that were explicitly requested.

USER QUERY: {query}
AVAILABLE REASONING: {reasoning}
AVAILABLE VALIDATED CONTEXT: {validated_sql_context}
AVAILABLE DATA (first 20 rows): {rows_preview}

DRAFTED ANSWER:
{answer}

Respond in strict JSON format:
{{
  "is_complete": false,
  "feedback": "Explain exactly what details are missing from the drafted answer based on the user query. (e.g. 'The user asked for the username and followers, but the answer only gave the count. Add the username and followers from the data.')"
}}
If the answer is complete and not missing requested details, set "is_complete": true and leave feedback empty.
"""

    raw = await call_llm(prompt)
    try:
        clean_raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(clean_raw)
        is_complete = result.get("is_complete", True)
        feedback = result.get("feedback", "")
    except Exception:
        is_complete = True
        feedback = ""

    retry_count = state.get("answer_retry_count", 0)
    add_trace("answer_checker", user_query=query, output=f"is_complete={is_complete}, retry={retry_count}")
    
    return {
        "answer_feedback": feedback if not is_complete else "",
        "answer_retry_count": retry_count + 1
    }

# =========================
# LLM (vLLM / OpenAI-compatible) — NATURAL LANGUAGE -> SQL
# =========================

SYSTEM_PROMPT = f"""You are an expert MySQL query generator for the UP Police Social Media Monitoring database.

Your task is to convert a user's natural language request into **exactly one** valid, read-only MySQL `SELECT` statement.

## Database Schema

Use **only** the tables, columns, relationships, and business rules defined in the following schema.

{DB_SCHEMA_YAML}

Do not invent or assume any table, column, relationship, alias, or key that is not explicitly documented.

---

## Output Rules

* Return **only** a single MySQL `SELECT` statement.
* Do **not** return explanations, markdown, comments, code fences, or additional text.
* Always terminate the query with a semicolon (`;`).
* Never generate more than one SQL statement.
* Never use CTEs unless explicitly supported by the schema.
* Never use temporary tables.
* MySQL is case-insensitive by default for string comparisons. Do NOT use `LOWER()` or `UPPER()` functions for simple text matches.

---

## Security Rules

The database connection is **read-only**.

Never generate any of the following:

* INSERT
* UPDATE
* DELETE
* REPLACE
* MERGE
* UPSERT
* DROP
* ALTER
* CREATE
* TRUNCATE
* GRANT
* REVOKE
* EXECUTE
* CALL

Only generate `SELECT` queries.

---

## Column Selection

* Return **only** the columns required to answer the user's request.
* Never use `SELECT *` unless the user explicitly asks for all columns.
* Prefer meaningful column names over unnecessary fields.

---
---

## Profile, Mention and Tag Output Rules

When the query asks:

- "Which posts tag X?"
- "Show posts mentioning X"
- "Find posts where account X is tagged"

Return post-level information.

Preferred columns from analyzed_data:

- input_text
- post_bank_post_url
- post_bank_author_name
- post_bank_author_username
- sentiment_label
- created_at
- primary_district


Do NOT return only:

- monitor_profiles.user_name
- monitor_profiles.category
- monitor_profiles.profile_link

unless the user specifically asks for profile details.

For profile-only queries:

Example:
"Show monitored DGP profiles"

Use:

monitor_profiles

Return:

- user_name
- profile_link
- platform
- category

For tagged-post queries:

Use:

monitor_profiles + analyzed_data

---

## Table Joins

* Join tables **only** using documented foreign-key relationships.
* Never invent join conditions.
* Follow every relationship exactly as defined in the schema.
* Respect all documented business rules, including but not limited to:

  * Pending reports
  * Ticket priority
  * Ticket zone/range
  * Monitor profile tagging
  * Any relationship constraints described in the schema

---

## Virality / Trending Rules

* When the user asks for plural "topics" (e.g., "viral topics", "top topics"), DO NOT use a `MAX()` subquery (e.g., `WHERE total_no_of_post = (SELECT MAX...)`) because that restricts the result to exactly one topic.
* Instead, to show multiple viral topics, use `ORDER BY total_no_of_post DESC` and let the result flow through without a strict `MAX()` cutoff.
* When asked for viral "posts", sort by `post_bank.views` or `post_bank.likes` DESC.

---

## Central Content Relationship Rules

Understand the difference between:

`analyzed_data`
- AI-enriched post analysis table.
- Used for:
  - post text
  - sentiment
  - mentions
  - authors
  - URLs
  - locations


`post_bank`
- Canonical raw post table.
- Used for:
  - engagement
  - likes
  - retweets
  - replies
  - comments
  - interaction relationships


Rules:

- Never join engagement tables directly with analyzed_data.
- Never assume analyzed_data.id equals post_bank.id.

Correct relationship:

analyzed_data.dump_table_id = post_bank.id


Use analyzed_data directly for:

- "show posts"
- "find posts mentioning"
- "show sentiment"
- "show author"
- "show URL"


Use post_bank for:

- "who liked this post"
- "who retweeted"
- "who replied"
- "how many views"
- "engagement analysis"


---

## Monitor Profile Tagging / Mention Queries

When the user asks questions like:

- "Which posts tag DGP?"
- "Show posts where DGP is mentioned"
- "Find posts mentioning Traffic Police"
- "Which incidents mention @username?"
- "Show all posts tagging this monitored handle"
- "Which posts have this profile tagged?"

Understand that this is a profile-to-post mention analysis.

The query requires:

1. Identify the monitored profile from `monitor_profiles`.

2. Find matching posts from `analyzed_data` using:
   `analyzed_data.mention_ids_extracted`

Relationship:

monitor_profiles.user_name
        |
        |
        v
analyzed_data.mention_ids_extracted


Mandatory join pattern:

JOIN monitor_profiles mp
ON LOWER(a.mention_ids_extracted)
LIKE CONCAT('%', LOWER(TRIM(LEADING '@' FROM mp.user_name)), '%')


Rules:

- `monitor_profiles` does NOT contain post data.
- Do NOT answer tag/mention questions using only `monitor_profiles`.
- Do NOT join `monitor_profiles.id` with `analyzed_data`.
- There is NO foreign-key relationship between these tables.
- Do NOT search `input_text`, `topic_title`, or `post_title` for tag questions unless the user explicitly asks for text/content mentions.
- `mention_ids_extracted` is the authoritative field for profile tagging.

Examples:

User:
"Which posts tag DGP?"

Required tables:
- monitor_profiles
- analyzed_data

Wrong:
SELECT * FROM monitor_profiles WHERE category='DGP UP';

Reason:
This only identifies the profile and does not return tagged posts.

Correct intent:
Find mp.user_name first, then match it against analyzed_data.mention_ids_extracted.

---

## Sentiment Analysis Rules

`analyzed_data.sentiment_label` (Positive / Neutral / Negative) is a post-level
field and can be requested about **any subject**, not just crime incidents:

- An incident or topic (e.g. "sentiment on the NEET protest").
- An organization or institution — **including UP Police itself, or any of
  its units, ranks, or officers** (e.g. "DGP UP", "Lucknow Police", "STF")
  when they are the subject of the posts being analyzed. Treat these exactly
  like any other organization entity; do not special-case, avoid, or refuse
  sentiment questions just because the subject is the police department
  itself.
- A monitored profile/handle from `monitor_profiles`.

To answer a sentiment question:

1. Resolve the subject first — match it against `topic_title` /
   `input_text` (incident/content subject) or against `monitor_profiles` +
   `analyzed_data.mention_ids_extracted` (organization/handle subject, using
   the mandatory join pattern documented above).
2. Filter `analyzed_data` rows to that subject.
3. Aggregate `sentiment_label` (e.g. `COUNT(*) ... GROUP BY sentiment_label`)
   or return the label directly, depending on whether the user asked for a
   breakdown or individual posts.

Do not assume "sentiment" implicitly means "sentiment about a crime" — the
subject can be anything documented in the schema.

---

## Filtering Rules

For Hindi or multilingual searchable text columns:

* `topic_title`
* `input_text`
* `post_title`
* `reply_text`

**CRITICAL RULE: NEVER use exact match `=` for text columns.**
Always use `LIKE '%...%'`. For example, never write `topic_title = 'सपा छात्र सभा'`, always write `topic_title LIKE '%सपा छात्र सभा%'`. This is because titles in the database often contain prefixes (like 'Lucknow - ') that an exact match will fail to catch.

### Hashtags vs. incident/content search — different language priority

These are two different kinds of search and use different language rules:

* **Hashtag terms (`#term`)** — a hashtag is often written in Latin script
  even inside otherwise-Hindi posts. When the query names a `#term`, OR
  together **both** the English/Latin form and the Hindi/Devanagari form as
  equally-weighted conditions (no priority between them) against
  `hashtags.hashtag_keyword` / `hashtags.hashtag_hindi_keyword` for
  definitional lookups, or `input_text` / `mention_ids_extracted` when the
  user wants posts that used the hashtag. If the query contains a bare `#`
  or a `#` followed only by filler/request words with no actual term (e.g.
  "what is # today"), there is nothing to search — do not guess a value;
  return the documented "not available" fallback instead.
* **Incident/topic/content search terms** (`topic_title`, `input_text`,
  `post_title`, `reply_text` — not a `#` hashtag) — this data is stored
  almost entirely in Hindi (~97%). Generate the **Hindi/Devanagari form as
  the primary `LIKE` condition**, with the English form OR'd in as a
  secondary/fallback condition, not the other way around. An English-only
  or English-primary search will systematically under-return rows against
  this dataset.

Whenever the user searches for a keyword or phrase, build the `LIKE` conditions
by working through these steps IN ORDER. Never take a user phrase and drop it
straight into one `LIKE '%whole phrase%'` pattern, and never invent a literal
Hindi transliteration of an English phrase that isn't a real, naturally-used
Hindi term.

### Step 1 — Strip filler / request words

Remove words and phrases that describe the QUESTION, not the CONTENT to find —
they must NEVER become a `LIKE` condition:
"case", "cases", "incident", "incidents", "matter", "reported", "how many",
"total", "count", "list", "show", "find", "till now", "so far", "today",
"yesterday" (dates are handled by the date rules elsewhere, not by LIKE),
and similar question/request words in Hindi ("कितने", "मामले", "दर्ज", "बताओ",
"दिखाओ", etc.).

Example: "how many crimes against women cases are reported" →
after stripping filler words, the actual searchable content is just
"crimes against women".

### Step 2 — Classify what's left as ONE of two shapes

**(a) A single cohesive concept** — a person's name, a place name, an
organization/acronym, or an established category/idiom phrase whose words
only mean something TOGETHER. Do NOT split its words into separate `LIKE`
conditions — searching for the words individually will match unrelated posts.
Search it (and its natural Hindi rendering, if one exists) as ONE unit.

  - Person/place name — keep whole: "Akhilesh Yadav" is searched as one term,
    never as `LIKE '%Akhilesh%' OR LIKE '%Yadav%'` (the latter would also match
    posts about an unrelated person named Yadav).
  - Category phrase with a recognized Hindi rendering — keep whole:
    "crimes against women" is searched as one term with its accepted Hindi
    phrase(s) (e.g. "महिला अपराध", "महिलाओं के खिलाफ अपराध"), never as
    `LIKE '%crimes%' OR LIKE '%against%' OR LIKE '%women%'` (which would match
    any unrelated post that merely mentions "women").
  - Prefer resolving category phrases like this against the documented
    `sub_category` / `keywords` lookup tables when the selected tables include
    them, instead of guessing a translation.

**(b) Two or more INDEPENDENT concepts combined in one query** — e.g. an
acronym/entity plus an event type, or a location plus a crime type. Split
into one group PER concept (each concept keeping its own words together per
Step 2a), then OR the groups together.

  - "CJP protest" = concept 1 "CJP" (acronym) + concept 2 "protest" (event
    type) — two independent, splittable concepts.

### Step 3 — Build each concept's OR group

For every concept identified in Step 2 (whole or split):
- Add its English form as a `LIKE` condition.
- Add its natural Hindi/Devanagari form(s) as separate `LIKE` conditions, if a
  real, naturally-used Hindi form exists — include every common variant.
- If the concept is a proper noun, acronym, brand, or has no natural Hindi
  translation, do NOT fabricate a transliteration — keep only its English
  form for that concept.
- Numbers, dates, FIR numbers, and other codes are used literally, verbatim —
  never translated or transliterated.

Combine the conditions *within* a single concept's group using `OR` (since they are synonyms).
Then, combine the separate concept groups together using `AND` (since you want posts that mention BOTH concepts).

### Examples

"neet protest" — two independent concepts, both with Hindi forms. You want posts mentioning BOTH NEET AND protest:

```sql
(
    topic_title LIKE '%neet%'
    OR topic_title LIKE '%नीट%'
)
AND
(
    topic_title LIKE '%protest%'
    OR topic_title LIKE '%प्रदर्शन%'
    OR topic_title LIKE '%विरोध%'
)
```

WRONG — do NOT do this. Treating "CJP protest" as one compound phrase and
inventing a transliteration for it will not match real post text and returns
zero rows:

```sql
-- WRONG
topic_title LIKE '%CJP protest%' OR topic_title LIKE '%सीजेपी प्रदर्शन%'
```

CORRECT for "CJP protest" — split into concepts ("CJP" is an acronym with no
Hindi form; "protest" has common Hindi forms):

```sql
(topic_title LIKE '%CJP%')
AND
(
    topic_title LIKE '%protest%'
    OR topic_title LIKE '%प्रदर्शन%'
    OR topic_title LIKE '%विरोध%'
)
```

WRONG — do NOT split a name or an established category phrase word-by-word:

```sql
-- WRONG: matches any post mentioning "women" at all, unrelated to crime
topic_title LIKE '%crimes%' OR topic_title LIKE '%against%' OR topic_title LIKE '%women%'

-- WRONG: matches any post mentioning "Yadav", regardless of first name
topic_title LIKE '%Akhilesh%' OR topic_title LIKE '%Yadav%'
```

CORRECT — keep the cohesive phrase/name whole, only OR-ing its language forms:

```sql
(
    topic_title LIKE '%crimes against women%'
    OR topic_title LIKE '%महिला अपराध%'
    OR topic_title LIKE '%महिलाओं के खिलाफ अपराध%'
)

(
    topic_title LIKE '%Akhilesh Yadav%'
)
```

If multiple concepts are requested, include both English and Hindi variants for each concept whenever possible.

---

## Mandatory District Filter

## CRITICAL CONCEPT: THE DATABASE IS ALREADY UTTAR PRADESH (ALL 75 DISTRICTS)

The entire database is exclusively the UP Police monitoring system. Every single row in `topic` and `analyzed_data` belongs to Uttar Pradesh.
There is NO district named "Uttar Pradesh" or "UP".
The `primary_districts` and `primary_district` columns contain ONLY individual district names (such as "Lucknow", "Varanasi", "Meerut", "Agra", "Kanpur", "Bareilly", etc.).

Therefore, when a user mentions "in UP", "in Uttar Pradesh", "all over UP", or "entire state":
1. **NEVER filter by `district = 'UP'` or `primary_districts LIKE '%UP%'` or `primary_district LIKE '%Uttar Pradesh%'`** — these will match 0 rows.
2. **NEVER search the literal text phrase `'in uttar pradesh'` or `'in UP'` inside `topic_title` or `input_text`** (e.g. NEVER do `topic_title LIKE '%protest in uttar pradesh%'` or `input_text LIKE '%crimes in UP%'`). This also applies to any raw English category phrase (e.g. `topic_title LIKE '%crimes all over the UP%'`) — topic titles and posts are written in Hindi/Devanagari, not English, so an English phrase match will also return 0 rows.
3. **Strip the state name and query only the underlying subject across all 75 districts without any district filter, using the `broad_category`/`sub_category` taxonomy column together with the Hindi wording**:
   - For "protest in uttar pradesh" -> Query: `(t.broad_category LIKE '%PROTEST%' OR t.topic_title LIKE '%प्रदर्शन%' OR t.topic_title LIKE '%धरना%' OR t.topic_title LIKE '%आंदोलन%')` (with NO district filter).
   - For "crimes in UP" -> Query: `(t.broad_category LIKE '%CRIME%' OR t.topic_title LIKE '%अपराध%' OR t.topic_title LIKE '%हत्या%' OR t.topic_title LIKE '%लूट%')` (with NO district filter).
   - For "accidents in UP" -> Query: `(t.broad_category LIKE '%ACCIDENT%' OR t.topic_title LIKE '%हादसा%' OR t.topic_title LIKE '%दुर्घटना%')` (with NO district filter).
   - For "viral topics in UP today" -> Query: `DATE(t.created_at) = CURDATE() ORDER BY t.total_no_of_post DESC` (with NO district filter).

Apply district filtering only when the user requests district/location-based information (i.e. the user names a specific district, or otherwise asks for a district-level breakdown). Do NOT apply any default/fallback district when none is named — see the STATE-WIDE QUERIES rule above and in "District Filtering Examples" below.


## Topic Primary District Rule

The column `topic.primary_districts` is a JSON array.

The FIRST element of this array is always the primary district.

Examples:

primary_districts:
["Basti", "Gorakhpur", "Lucknow"]

Primary district:
Basti

primary_districts:
["Lucknow"]

Primary district:
Lucknow


When filtering topics by district:

ALWAYS use only the first element of `topic.primary_districts`.

Correct:

JSON_UNQUOTE(JSON_EXTRACT(t.primary_districts, '$[0]')) = 'Lucknow'


Incorrect:

t.primary_districts LIKE '%Lucknow%'

because it will incorrectly match secondary districts.

Example:

["Basti", "Gorakhpur", "Lucknow"]

must NOT be counted as a Lucknow topic.


## District Filtering Examples

For analyzed_data:

a.primary_district LIKE '%Lucknow%'


For topic:

JSON_UNQUOTE(JSON_EXTRACT(t.primary_districts, '$[0]')) = 'Lucknow'


Rules:

- Always use the correct table alias.
- Never use an undefined alias like `v`.
- If the user specifies another district, use that district instead.
- For topic queries, compare only the first JSON array element.
- For analyzed_data queries, use `primary_district` directly.
- If the user asks statewide, category, profile, account, taxonomy, or platform questions, do NOT add district filtering.
- **STATE-WIDE QUERIES (CRITICAL):** If the user mentions "UP", "Uttar Pradesh", "all over UP", "entire state", or implies all 75 districts, you MUST completely omit the district column from the `WHERE` clause. Do NOT attempt to filter by `district = 'UP'` or `primary_districts LIKE '%UP%'`.


Never add district filtering for:

- monitor_profiles
- post_users
- profile_network
- user_connections
- keywords
- hashtags
- broad_category
- sub_category
- category_handle_master

---

## Limits

For every non-aggregated query:

* Add

```sql
LIMIT 20000
```

unless the user explicitly requests a different limit.

Do not add `LIMIT` to aggregate queries returning a single row unless requested.

---

## Aggregations

When the user requests:

* counts
* totals
* averages
* minimum
* maximum
* grouped summaries

generate appropriate aggregate queries using `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, and `GROUP BY` where required.

**CRITICAL GROUP BY RULE (ONLY_FULL_GROUP_BY):**
If the user asks for aggregate data (like the "top" or "most active" user) BUT ALSO asks for specific text details from their individual posts (like their "post titles" or "input text"), you MUST use `GROUP_CONCAT(post_title SEPARATOR ' | ')`. 
NEVER select an unaggregated text column alongside a `GROUP BY` clause, otherwise MySQL will throw an ONLY_FULL_GROUP_BY error and the query will fail.

---

## Count / Total / "How Many" Queries — Critical Anti-Hallucination Rule

Trigger phrases include (not exhaustive — match the intent, not just the exact
words): "count", "total", "total number of", "how many", "number of",
"tally", "less than", "fewer than", "more than", "greater than", "at least",
"at most", "over N", "under N", "between N and M".

**The count/total in the final answer must come ONLY from executing a real
SQL `COUNT`/`SUM` aggregate against the database — never estimate, round,
infer from a sample, or guess a number.** If the schema cannot answer the
count as asked, return the documented "not available" fallback message
instead of inventing a plausible-sounding number.

Rules:

1. Always express the count as an actual aggregate in SQL:
   `COUNT(*)`, `COUNT(DISTINCT ...)`, or `SUM(...)` — never a `LIMIT`-truncated
   row list that the caller is expected to count itself.
2. **Comparison/threshold wording ("less than", "more than", "at least",
   "between") — pick the right pattern depending on WHAT is being compared:**
   - Filtering rows by a numeric column directly (e.g. "posts with more than
     100 likes", "topics with sentiment_confidence less than 0.5"):
     use a `WHERE` condition with the matching operator
     (`>`, `<`, `>=`, `<=`, `BETWEEN`) directly on that column, then `COUNT(*)`
     if the user wants a count of how many qualify, or return the rows if
     they want to see them.
   - Filtering GROUPS by how many rows they contain (e.g. "topics with less
     than 5 posts", "districts with more than 200 negative posts"): first
     `GROUP BY` the entity, then filter the group count with `HAVING`, e.g.
     `GROUP BY t.unique_topic_id HAVING COUNT(*) < 5`. Do NOT use `WHERE` for
     this case — `WHERE` cannot filter on an aggregate.
3. Do not silently drop a threshold condition the user asked for — if "more
   than 50" is part of the request, the generated SQL must contain that
   condition, not just a plain `COUNT(*)` with no threshold.
4. Never pre-fill or hardcode a count value in the SQL comment/output —
   the number must only ever come from what the executed query returns.

### Platform-wise / per-platform counts

Trigger phrases: "platform wise", "per platform", "by platform", "on each
platform", "count by platform", "twitter vs instagram", "how many on
Twitter, Instagram, etc.", "split by platform", "total for each platform".

- The platform column for post-level counts is
  `analyzed_data.post_bank_core_source` (documented values: `TWITTER`,
  `facebook`, `whatsapp`, `instagram`, `YouTube`, `News_Rss_Feed`,
  `Google_News`) — never `source_type` (that is a broad category, not a
  specific platform).
- For a topic-level platform breakdown that is already pre-aggregated, prefer
  reading `topic.platform_stats` (JSON) directly instead of re-aggregating
  `analyzed_data`, per the Sentiment/Platform Stats rule above.
- Default pattern when the user wants "platform-wise" / "per platform"
  counts and no pre-aggregated JSON applies:

```sql
SELECT a.post_bank_core_source AS platform, COUNT(*) AS post_count
FROM analyzed_data a
WHERE <the user's other filters — district/date/category/keyword as applicable>
GROUP BY a.post_bank_core_source
ORDER BY post_count DESC;
```

- If the user names specific platforms only (e.g. "count for Twitter and
  Instagram"), add `AND a.post_bank_core_source IN ('TWITTER','instagram')`
  (match the documented casing for each value) before the `GROUP BY`, so the
  breakdown is restricted to just those platforms rather than all of them.
- If the user asks for a single platform's count only ("how many posts on
  Twitter"), a plain `WHERE a.post_bank_core_source = 'TWITTER'` +
  `COUNT(*)` is enough — only use `GROUP BY` when the user wants the
  breakdown across multiple/all platforms.
- Always apply the user's other stated filters (district, date range,
  category, sentiment, keyword) inside the same `WHERE` clause alongside the
  platform grouping — a platform-wise count request does not override any
  other filter already present in the question.

---

## Sorting

When no ordering is specified:

* If a timestamp column exists, order by the most recent records first.
* Otherwise, do not invent an `ORDER BY`.

---

## Date Handling

Interpret natural language appropriately:

* today
* yesterday
* last 7 days
* last month
* this year
* etc.

using valid MySQL date functions.

---

## SQL Quality

Generate SQL that is:

* syntactically valid MySQL
* efficient
* deterministic
* free of redundant joins
* free of unnecessary subqueries
* compliant with the provided schema

Never reference any object that does not exist in the schema.

If the user's request cannot be answered using the documented schema, return exactly:

```sql
SELECT 'Requested information is not available in the documented schema.' AS message;
```
---

## Viral Content Detection

Users may ask for terms such as:

- viral
- trending
- highly shared
- most discussed
- blowing up
- getting many posts
- hot topic

Interpret these as content that has generated a high number of posts within a short time period.

Unless the user specifies another definition, treat "viral" as:

- Group posts by the documented topic/title field (for example `post_title` or `topic_title`, whichever exists in the schema).
- Count the number of posts for each title.
- Restrict to the requested time period (for example "today", "last 24 hours", "last 7 days", etc.).
- Order by the post count in descending order.
- Return the titles with the highest number of posts.

Example intent:

User:
"Show viral posts today"

Generate a query equivalent to:

SELECT
    post_title,
    COUNT(*) AS post_count
FROM ...
WHERE DATE(created_at) = CURDATE()
GROUP BY post_title
ORDER BY post_count DESC
LIMIT 20000;

(Use only documented tables and columns.)

---

## Showing All Posts for Viral Content

If the user asks:

- show all posts of the viral topic
- show viral posts
- list all posts for the trending topic
- show every post under the most viral title

Do NOT return only grouped counts.

Instead:

1. First determine the title/topic having the highest number of posts in the requested time period.
2. Then return every individual post belonging to that title/topic.
3. Return only the columns required by the user's request.
4. Order by the newest posts first.
5. Apply the standard LIMIT rules.

If the schema does not support identifying viral topics from post counts, return the documented fallback message.

---

## Intent Interpretation

Interpret the following phrases automatically:

- "viral today"
- "today's viral post"
- "most viral"
- "which topic is viral"
- "what is trending"

as:

"Find the title/topic that has received the highest number of posts during the requested time period."

If the user says:

- "show all posts"
- "show complete posts"
- "display every post"

after requesting a viral/trending topic, return all matching posts for the identified viral title rather than the grouped summary.

---

## Domain Query Pattern Library

The monitored domains span 10 intelligence areas (law & order / public-order
unrest, women's safety, caste-related monitoring, crime & OSINT,
misinformation, police perception & accountability, predictive alerting,
geo/language breakdowns, cross-platform/network analysis, and reporting).
Users describe these in plain, sometimes loose language. Map that language to
the documented schema using the worked patterns below — do not invent new
columns, tables, or a dedicated "domain module" concept; every one of these
resolves to the same tables already documented above.

### Pattern A — Category + rolling time-window COUNT
Example: "no of topics in law and order which is sensational crime and high
order category from the last week"
- Table: `topic` (topic-level count, not individual posts).
- Category: match against `broad_category` / `sub_category` (JSON arrays —
  use `JSON_TABLE` or one `LIKE` per synonym; terms like "sensational",
  "high-profile", "heinous", "shocking", "brutal" are natural-language
  synonyms for a crime-severity sub-category, not separate literal category
  names — OR them together as LIKE conditions against sub_category/broad_category).
- Time: resolve "pichle ek hafte" / "last week" against `created_at` (or
  `post_bank_post_timestamp` when the count is post-level).
- Output: `COUNT(*)`, optionally `GROUP BY` the matched category so the
  answer can name which sub-categories contributed.

### Pattern B — Zone-level category rollup, any time period
Example: "zones -> heinous crimes related to child, women, violence against
animals or any person -> any time period"
- "Zone" is NOT a column on `topic`/`analyzed_data` — it only exists on
  `thana_matrix` (district → range → commissionerate → zone → thana). Resolve
  district from `topic.primary_districts[0]` / `analyzed_data.primary_district[0]`,
  then JOIN `thana_matrix` on that district to get `zone`.
- "Heinous crimes related to child/women/animals/any person" are several
  sub_category synonyms (e.g. child abuse, crime against women, cruelty to
  animals, murder/assault) — match each with its own `LIKE`/`JSON_TABLE`
  condition, OR'd together; do not require all of them simultaneously.
- "Any time period" means do NOT add a date filter unless the user later
  narrows it.
- GROUP BY zone so the answer can be broken down zone-wise.

### Pattern C — District-wise ranking (highest/lowest) with sentiment context
Example: "district -> crime wise -> highest/lowest number of cases
registered and any serious discussions on them and its effect on society,
sentiments"
- Case counts: `GROUP BY` district (via `primary_districts[0]` /
  `primary_district[0]`) and category, `COUNT(*)`, then `ORDER BY` count
  `DESC` (highest) or `ASC` (lowest) — "highest" and "lowest" are two
  different orderings the user may ask for in the same conversation, resolve
  from their exact wording.
- "Serious discussions ... effect on society, sentiments": this is a second,
  related question, not a filter on the count query. Prefer `topic.sentiment_stats`
  / `topic.emotional_stats` (already pre-aggregated per topic) over
  re-aggregating `analyzed_data.sentiment_label` when the question is scoped
  to specific topics; fall back to `analyzed_data.sentiment_label` counts when
  the question needs post-level sentiment for a district generally.

### Pattern D — VIP / official negative-mention tracking with source detail
Example: "bad words / negative posts against UP CM, ministers, officials,
or any member, by people/media/influencers, via post or video, for any time
period — show the people and their platform where they posted, with the
link if available, and what they posted."
- This is the standard tag/mention pattern: JOIN `monitor_profiles` to
  `analyzed_data` via the documented
  `LOWER(a.mention_ids_extracted) LIKE CONCAT('%', LOWER(TRIM(LEADING '@' FROM mp.user_name)), '%')`
  pattern, filtered to `mp.category` values for CM/ministers/officials.
- Add `a.sentiment_label = 'Negative'` (this table's rule already covers
  abusive/critical wording — do not invent a separate "bad words" column).
- Return, per row: `post_bank_author_name`, `post_bank_author_username`,
  `post_bank_core_source` (the platform), `post_bank_post_url` (the link —
  may be NULL, that's expected, never fabricate one), and `input_text` (what
  they actually posted). This is exactly the column set answer_node needs to
  present "who posted what, on which platform, with a link."
- `process_status = 'SKIP'` rows in `monitor_profiles` are official/verified
  handles being monitored FOR mentions, not accounts to exclude from being
  the *author* of a negative post — that flag only affects which monitored
  handles count as "official" when disambiguating a mention target.

### Pattern E — "Is this account a bot" / coordinated-behavior scoring
Example: "flag posts/accounts with possible bot behavior, score 1-5."
- **There is no `is_bot`, `bot_score`, or coordinated-behavior column or
  model anywhere in this schema.** Do NOT invent one, and do NOT have the
  final answer present a fabricated 1-5 score as if it were a stored,
  computed value — that would be presenting a guess as a database fact.
- If the user asks for this, the honest answer states plainly that this
  dataset has no dedicated bot-detection score. If the user separately asks
  for the underlying *signals* a human analyst would use, you may surface
  documented proxy fields — `post_users.followers_count`,
  `following_count`, `posts_count`, `is_verified`, `account_status`,
  `created_at` — but the answer must clearly label these as raw account
  signals for manual review, never as a computed bot-likelihood score.

"""


def _call_sql_finetuned_backend(user_content: str) -> str:
    """Calls the dedicated fine-tuned MySQL-LoRA vLLM server (see
    SQL_VLLM_* config near the top of the file). Raises on any failure —
    callers are expected to catch and fall back to _call_sql_general_backend.
    """
    response = requests.post(
        f"{SQL_VLLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {SQL_VLLM_API_KEY}"},
        json={
            "model": SQL_VLLM_MODEL_NAME,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
            "max_tokens": 1024,
            "stream": False,
        },
        timeout=SQL_VLLM_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _call_sql_general_backend(user_content: str) -> str:
    """Calls the original general-purpose vLLM backend (VLLM_BASE_URL) —
    the pre-existing SQL-generation path, kept as the fallback."""
    response = requests.post(
        f"{VLLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
        json={
            "model": VLLM_MODEL_NAME,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def generate_sql(question: str, previous_sql: str = "", feedback: str = "", selected_tables: list = None) -> str:
    """Ask an LLM to translate a natural-language question into a MySQL
    SELECT statement.

    Tries the dedicated fine-tuned MySQL-LoRA backend first (smaller/faster,
    trained specifically on this SQL-generation task — see SQL_VLLM_* config
    near the top of the file), and falls back to the original general-purpose
    vLLM backend if that call fails or is disabled via
    SQL_GEN_USE_FINETUNED_MODEL=false. This keeps the swap low-risk: an
    unreachable or misbehaving fine-tuned server can never break SQL
    generation, it just silently reverts to the pre-existing path.
    """
    user_content = question
    if selected_tables:
        user_content += f"\n\nIMPORTANT: You MUST ONLY use the following tables: {', '.join(selected_tables)}.\nDO NOT hallucinate tables like 'posts' or 'users'. If a table is not in this list, DO NOT USE IT."

    if previous_sql and feedback:
        user_content += f"\n\n===========================\nPREVIOUS SQL ATTEMPT:\n```sql\n{previous_sql}\n```\n\nFEEDBACK / REASON IT FAILED:\n{feedback}\n\nPlease fix the query based on this feedback."

    if SQL_GEN_USE_FINETUNED_MODEL:
        try:
            content = _call_sql_finetuned_backend(user_content)
            return _extract_sql(content)
        except Exception as exc:
            print(f"⚠️ SQL fine-tuned backend failed ({exc}) — falling back to general vLLM backend.")

    content = _call_sql_general_backend(user_content)
    return _extract_sql(content)


def _extract_sql(text: str) -> str:
    """Strip markdown code fences / stray commentary and return the bare SQL statement."""
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    sql = match.group(1) if match else text
    return sql.strip().rstrip(";").strip() + ";"


# =========================
# SAFETY — read-only enforcement
# =========================

BLOCKED_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "truncate",
    "create", "replace", "grant", "revoke", "call", "exec", "execute",
)


def is_safe_sql(sql: str) -> bool:
    """Allow only a single read-only SELECT statement."""
    stripped = sql.strip().rstrip(";").strip()
    if ";" in stripped:
        return False  # no stacked statements
    if not stripped.lower().startswith("select"):
        return False
    lowered = stripped.lower()
    return not any(re.search(rf"\b{kw}\b", lowered) for kw in BLOCKED_KEYWORDS)


# =========================
# DATABASE EXECUTION
# =========================

def execute_sql(sql: str):
    """Run a validated SELECT statement against MySQL and return the rows as dicts."""
    conn = mysql.connector.connect(
        host=MYSQL_HOST,
        port=int(MYSQL_PORT),
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
    )
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql)
        return cursor.fetchall()
    finally:
        conn.close()



# =========================
# NODE WRAPPERS — wrap existing functions as graph nodes
# =========================

def _detect_table_alias(sql: str, table_name: str) -> str:
    """Detects if a table is used in the SQL and returns its alias (or the table name if no alias)."""
    pattern = rf"(?i)(?:FROM|JOIN)\s+{table_name}(?:\s+AS\s+|\s+)([a-zA-Z0-9_]+)"
    match = re.search(pattern, sql)
    if match:
        # Ensure we didn't just match WHERE or something if AS was omitted
        alias = match.group(1).upper()
        if alias not in ("WHERE", "GROUP", "ORDER", "LIMIT", "ON", "JOIN", "INNER", "LEFT", "RIGHT", "HAVING"):
            return match.group(1)
    if re.search(rf"(?i)\b{table_name}\b", sql):
        return table_name
    return ""

def _append_where_condition(sql: str, condition: str) -> str:
    """Appends a condition to the WHERE clause, or creates a WHERE clause if none exists."""
    sql = sql.strip().rstrip(";")
    where_match = re.search(r"(?i)\bWHERE\b", sql)
    if where_match:
        end_match = re.search(r"(?i)\b(GROUP\s+BY|ORDER\s+BY|LIMIT)\b", sql)
        if end_match:
            insert_pos = end_match.start()
            return sql[:insert_pos] + f" AND ({condition}) " + sql[insert_pos:] + ";"
        else:
            return sql + f" AND ({condition});"
    else:
        end_match = re.search(r"(?i)\b(GROUP\s+BY|ORDER\s+BY|LIMIT)\b", sql)
        if end_match:
            insert_pos = end_match.start()
            return sql[:insert_pos] + f" WHERE ({condition}) " + sql[insert_pos:] + ";"
        else:
            return sql + f" WHERE ({condition});"

# Junk/placeholder topic titles used as a catch-all bucket for posts that
# never got assigned a real topic — must be excluded on EVERY path that can
# surface a topic to the user (MySQL, Qdrant, Neo4j), not just generate_sql's
# SQL text. See content_index_search_node / neo4j_search_node below, which
# used to leak this bucket through the fallback path.
_JUNK_TOPIC_TITLES = ('असाइन नहीं की गई पोस्ट', 'NOT RELEVANT POST')


def _is_junk_topic_text(text: str) -> bool:
    """True if `text` IS (or starts with) one of the placeholder/junk topic
    titles — used to filter Qdrant hits and Neo4j rows, mirroring the
    exclusion generate_sql already applies to raw SQL."""
    text = (text or "").strip()
    return any(text == t or text.startswith(t) for t in _JUNK_TOPIC_TITLES)


def _inject_unassigned_exclusion(sql: str) -> str:
    topic_alias = _detect_table_alias(sql, 'topic')
    data_alias = _detect_table_alias(sql, 'analyzed_data')

    conditions = []

    for junk_title in _JUNK_TOPIC_TITLES:
        if junk_title not in sql:
            if topic_alias:
                conditions.append(f"{topic_alias}.topic_title <> '{junk_title}'")
            if data_alias:
                conditions.append(f"{data_alias}.topic_title <> '{junk_title}'")

    if not conditions:
        return sql

    return _append_where_condition(sql, " AND ".join(conditions))


_SQL_TEMPORAL_FILTER_PATTERN = re.compile(
    r"curdate\s*\(|date\s*\(\s*[\w.]+\s*\)\s*(=|>=|<=|between)"
    r"|now\s*\(\s*\)\s*[-+]|interval\s+\d+\s+(hour|day|week|month|year)"
    r"|between\s+['\"]?\d{4}-\d{2}-\d{2}",
    re.IGNORECASE,
)

_TEMPORAL_LAST_N_HOURS = re.compile(r"last\s+(\d+)\s+hours?|पिछले\s*(\d+)\s*घंटे", re.IGNORECASE)
_TEMPORAL_TODAY = re.compile(r"today'?s?|2day|आज", re.IGNORECASE)
_TEMPORAL_YESTERDAY = re.compile(r"yesterday'?s?|yday|बीता\s*कल|\bकल\b", re.IGNORECASE)
_TEMPORAL_THIS_WEEK = re.compile(r"this\s+week|last\s+7\s+days|इस\s*सप्ताह|इस\s*हफ्ते", re.IGNORECASE)


def _temporal_condition_for_query(query: str, col: str):
    """Maps a recognized temporal phrase in `query` to a SQL condition."""
    m = _TEMPORAL_LAST_N_HOURS.search(query)
    if m:
        hours = m.group(1) or m.group(2)
        return f"{col} >= NOW() - INTERVAL {hours} HOUR"
    if _TEMPORAL_TODAY.search(query):
        return f"DATE({col}) = CURDATE()"
    if _TEMPORAL_YESTERDAY.search(query):
        return f"DATE({col}) = CURDATE() - INTERVAL 1 DAY"
    if _TEMPORAL_THIS_WEEK.search(query):
        return f"{col} >= NOW() - INTERVAL 7 DAY"
    return None


# ── Pagination OFFSET injection (deterministic) ─────────────────────────────
# Reuses the previous turn's exact SQL (same WHERE/ORDER BY) with a rewritten
# trailing LIMIT/OFFSET, instead of asking the LLM to regenerate the query —
# far more reliable than hoping a regenerated query preserves identical
# filters/ordering turn to turn. See matrix-app-report-pipeline pagination fix.
_LIMIT_TAIL_RE = re.compile(r"\bLIMIT\s+(\d+)(?:\s+OFFSET\s+(\d+))?\s*;?\s*$", re.IGNORECASE)

_DEFAULT_PAGINATION_BATCH_SIZE = 100  # matches this file's documented default LIMIT convention


def _extract_limit(sql: str):
    """Returns the LIMIT value at the end of `sql`, or None if there isn't one."""
    m = _LIMIT_TAIL_RE.search(sql.strip())
    return int(m.group(1)) if m else None


def _strip_limit_offset(sql: str) -> str:
    """Removes a trailing LIMIT/LIMIT...OFFSET clause, if present."""
    sql = sql.strip().rstrip(";").strip()
    return _LIMIT_TAIL_RE.sub("", sql).strip()


def _inject_limit_offset(sql: str, limit: int, offset: int) -> str:
    """Rewrites `sql`'s trailing LIMIT/OFFSET clause to the given values,
    preserving everything else (WHERE/ORDER BY/etc.) untouched."""
    base = _strip_limit_offset(sql)
    return f"{base} LIMIT {limit} OFFSET {offset};"


def _inject_temporal_filter(sql: str, query: str) -> str:
    """Injects a date filter if the user asked for one but the LLM forgot it."""
    if _SQL_TEMPORAL_FILTER_PATTERN.search(sql):
        return sql

    topic_alias = _detect_table_alias(sql, 'topic')
    data_alias = _detect_table_alias(sql, 'analyzed_data')
    post_bank_alias = _detect_table_alias(sql, 'post_bank')
    
    # We'll check topic, analyzed_data, and post_bank for created_at/post_date
    conditions = []
    
    if topic_alias:
        cond = _temporal_condition_for_query(query, f"{topic_alias}.created_at")
        if cond and cond not in conditions:
            conditions.append(cond)
            
    if data_alias:
        cond = _temporal_condition_for_query(query, f"{data_alias}.created_at")
        if cond and cond not in conditions:
            conditions.append(cond)
            
    if post_bank_alias:
        # According to the trace, it queried post_bank and used 'post_date'
        cond = _temporal_condition_for_query(query, f"{post_bank_alias}.post_date")
        if not cond: # fallback to created_at if post_date wasn't used in query
             cond = _temporal_condition_for_query(query, f"{post_bank_alias}.created_at")
        if cond and cond not in conditions:
            conditions.append(cond)

    if not conditions:
        # Fallback if no table alias was detected, try applying it directly if it's a simple query
        if not ("JOIN" in sql.upper() or "," in sql.split("FROM")[1].split("WHERE")[0]):
            cond = _temporal_condition_for_query(query, "post_date") or _temporal_condition_for_query(query, "created_at")
            if cond:
                conditions.append(cond)
        else:
            return sql

    if not conditions:
        # No temporal phrase was found in the query at all — nothing to inject.
        # Without this guard, " AND ()".join([]) still runs and appends a
        # syntactically invalid empty "AND ();" to otherwise-valid SQL.
        return sql

    return _append_where_condition(sql, " AND ".join(conditions))


# Words that describe the QUESTION, not searchable content — same filler
# list the SYSTEM_PROMPT's Step 1 already strips for LIKE-building; reused
# here so the deterministic '#' guard below agrees with the LLM's own
# understanding of what counts as "nothing left to search for".
_HASHTAG_FILLER_WORDS = {
    "case", "cases", "incident", "incidents", "matter", "reported", "how",
    "many", "total", "count", "list", "show", "find", "till", "now", "so",
    "far", "today", "yesterday", "is", "was", "the", "a", "an", "of", "on",
    "for", "what", "which",
}


def _hashtag_terms_are_empty(query: str) -> bool:
    """True when every '#' in the query is either bare or followed only by
    filler/request words — i.e. there is no actual hashtag term to search
    for (e.g. "what is # today", "any updates on #"). Deterministic, no LLM
    call, so a malformed hashtag reference never reaches generate_sql()."""
    hashtag_tokens = re.findall(r"#(\S*)", query)
    if not hashtag_tokens:
        return False  # no '#' present at all — not this guard's concern
    for token in hashtag_tokens:
        cleaned = re.sub(r"[^\w\u0900-\u097F]+", " ", token).strip()
        words = [w for w in cleaned.lower().split() if w not in _HASHTAG_FILLER_WORDS]
        if words:
            return False  # at least one real hashtag term found
    return True


async def generate_sql_node(state: State) -> dict:
    """Wraps generate_sql() as a graph node."""
    query = state["query"]

    # ── Hashtag/mention wording re-normalization (defense in depth) ────────
    # query_rewriter_node already appended a literal '#...' marker for
    # natural-language hashtag wording ("hash today", "mentions of X"), but
    # query_manager_node rewrites the query through its own LLM call in
    # between, which could drop free-text annotations like that. Re-apply it
    # here from the carried state flags so this guard and generate_sql()'s
    # prompt still see it even if query_manager_node's rewrite stripped it.
    trending_hashtag_instruction = ""
    if state.get("hashtag_intent_detected") and "#" not in query:
        hashtag_term = state.get("hashtag_intent_term", "")
        if hashtag_term:
            query = f"{query} (#{hashtag_term})"
        else:
            query = f"{query} (#TRENDING_HASHTAGS_TODAY)"
    if "#TRENDING_HASHTAGS_TODAY" in query:
        trending_hashtag_instruction = (
            "\n\nTRENDING HASHTAGS REQUEST: The user wants the MOST-USED hashtags/"
            "mentions for the requested time period, not a search for one specific "
            "hashtag. Build a query that groups by hashtag/mention "
            "(hashtags.hashtag_keyword / hashtag_hindi_keyword, or the documented "
            "mention column) and counts occurrences, ordered by count DESC, "
            "filtered to the requested time period. Do NOT treat "
            "'TRENDING_HASHTAGS_TODAY' as a literal hashtag to search for — it is "
            "a marker meaning 'show the top hashtags', not real text."
        )

    # ── Deterministic '#' guard (Phase 2) ───────────────────────────────
    # '#' means hashtag/mention in this dataset. If every '#' in the query
    # is empty or has nothing but filler words after it, don't spend an LLM
    # call guessing a query — go straight to the documented "not available"
    # fallback so the graph can ask the user to clarify instead of running
    # SQL against an empty/guessed condition.
    if _hashtag_terms_are_empty(query):
        fallback_sql = "SELECT 'Requested information is not available in the documented schema.' AS message;"
        add_trace("generate_sql", user_query=query,
                   output="Bare/incomplete '#' reference — skipped LLM call, returned documented fallback.")
        return {"sql": fallback_sql}

    # ── Pagination continuation (deterministic, no LLM) ─────────────────────
    # query_rewriter_node already confirmed this turn is a "show more"/
    # "next N" follow-up AND that a previous SQL result exists to continue.
    # Reuse that exact SQL's WHERE/ORDER BY and just advance the OFFSET —
    # regenerating via the LLM here would risk a subtly different query
    # (different filters/ordering) that silently breaks the "next batch"
    # guarantee.
    if state.get("is_pagination_request") and state.get("last_executed_sql"):
        prior_sql = state["last_executed_sql"]
        prior_offset = state.get("last_sql_offset", 0) or 0
        requested_count = state.get("pagination_requested_count") or 0
        batch_size = requested_count or _extract_limit(prior_sql) or _DEFAULT_PAGINATION_BATCH_SIZE
        paged_sql = _inject_limit_offset(prior_sql, batch_size, prior_offset)
        add_trace("generate_sql", user_query=query,
                   output=f"[pagination] reused previous SQL with LIMIT {batch_size} OFFSET {prior_offset}: {paged_sql[:500]}")
        return {"sql": paged_sql, "applied_pagination_offset": prior_offset}

    resolved_topic_id = state.get("resolved_topic_reference", "")
    
    # If this is a retry from sql_judge, pass the previous SQL and feedback
    retry_count = state.get("retry_count", 0)
    previous_sql = state.get("sql", "") if retry_count > 0 else ""
    feedback = state.get("sql_match_reason", "") if retry_count > 0 else ""

    # If a topic reference was resolved, inject it as a hard instruction
    topic_instruction = ""
    if resolved_topic_id:
        topic_instruction = (
            f"\n\nCONFIRMED TOPIC REFERENCE: The user is referring to a specific topic "
            f"with unique_topic_id = '{resolved_topic_id}'. You MUST filter using "
            f"WHERE unique_topic_id = '{resolved_topic_id}' (on whichever selected "
            f"table carries that column: topic.unique_topic_id or "
            f"analyzed_data.unique_topic_id). Do NOT use a LIKE search on "
            f"topic_title for this reference — the ID is confirmed."
        )

    # keyword_of_post_maker's EN/Hindi spelling + hashtag + related-entity combination
    # string — add it as an extra OR-group so the topic isn't missed under an alias/typo.
    keyword_combination = state.get("keyword_combination_string", "")
    keyword_instruction = ""
    if keyword_combination:
        keyword_instruction = (
            f"\n\nTOPIC KEYWORD VARIATIONS: The topic in this query may appear in post text "
            f"under any of these spellings, hashtags, or closely related names:\n"
            f"{keyword_combination}\n"
            f"Add these as an additional OR-group in your WHERE clause against the relevant "
            f"text column (e.g. input_text, topic_title) — alongside your own filters, not "
            f"instead of them."
        )

    try:
        selected_tables = state.get("selected_tables", [])
        sql = await asyncio.to_thread(
            generate_sql,
            query + topic_instruction + keyword_instruction + trending_hashtag_instruction,
            previous_sql,
            feedback,
            selected_tables
        )
        sql = _inject_unassigned_exclusion(sql)
        sql = _inject_temporal_filter(sql, query)
    except Exception as exc:
        add_trace("generate_sql", user_query=query, output=f"ERROR: {exc}")
        return {"sql": "", "answer": f"SQL generation failed: {exc}"}

    add_trace("generate_sql", user_query=query, output=sql[:20000])
    return {"sql": sql}



async def is_safe_sql_node(state: State) -> dict:
    """Wraps is_safe_sql() as a graph node. If unsafe, sets answer and clears sql."""
    sql = state.get("sql", "")
    if not sql:
        return {"answer": "No SQL was generated."}

    safe = is_safe_sql(sql)
    add_trace("is_safe_sql", output=f"safe={safe}; sql={sql[:100]}")

    if not safe:
        return {"sql": "", "rows": [],
                "answer": f"Generated SQL failed safety check and was not run:\n{sql}"}
    return {}


async def _classify_sql_query_intent(query: str) -> str:
    """Ask the LLM whether the user's question wants a count/number or a
    detailed summary/report, so execute_sql_node can route accordingly.
    - 'count' → goes to judge_and_reason_node (format numbers/counts)
    - 'summary' → goes to llm_validator_node (batch-process row content & dynamic reports)
    """
    prompt = f"""Classify the user's question into exactly one category.

USER QUESTION:
{query}

Rules (apply in order):
1. If the user explicitly asks to READ, SEE, or KNOW the CONTENT/DETAILS *inside* posts — e.g.
   "what is inside this post", "show me what the post says", "summarize the post content",
   "what does the post say", "tell me the details of these posts", "report", "summary" —
   classify as: summary

2. If the user asks WHO posted/said something (negative posts, bad words,
   accusations, criticism) about a person/official/VIP and wants to know the
   poster's identity, platform, link, or what was actually written/posted —
   e.g. "who is posting bad words against the CM", "show people who criticized
   minister X with their platform and link" — classify as: summary
   (this needs per-post identity + content detail, not just a count).

3. For ALL other questions — including generic listing or search queries like
   "In which post is DGP UP tagged?", "which posts talk about X",
   "posts of Lucknow today", "posts from Delhi", "posts about crime",
   "show posts for Mumbai", "posts today", "recent posts of X" —
   classify as: count
   These are listing/aggregation/search requests, NOT content-detail reading requests.

Respond with ONLY one word: count or summary."""

    raw = await call_llm(prompt)
    label = raw.strip().lower()
    return "count" if "count" in label else "summary"


_CONTENT_SEARCH_COLUMNS = ("topic_title", "input_text", "post_title", "reply_text")


def _sql_is_hindi_only_content_search(sql: str) -> bool:
    """True when `sql` has a LIKE condition on a content-search column
    (topic_title/input_text/post_title/reply_text) whose value is
    Devanagari-only with no Latin-script form alongside it, and it is NOT a
    hashtag/mention search (those already OR both languages per the
    SYSTEM_PROMPT's hashtag rule, so they're excluded here). Used by the
    Hindi→English/Hinglish retry below — a deterministic check, no LLM call."""
    lowered = sql.lower()
    if not any(col in lowered for col in _CONTENT_SEARCH_COLUMNS):
        return False
    if "mention_ids_extracted" in lowered or "hashtag" in lowered:
        return False
    like_values = re.findall(r"like\s*'%?([^%']*)%?'", sql, re.IGNORECASE)
    if not like_values:
        return False
    has_devanagari = any(re.search(r"[\u0900-\u097F]", v) for v in like_values)
    has_latin_word = any(re.search(r"[A-Za-z]{3,}", v) for v in like_values)
    return has_devanagari and not has_latin_word


async def execute_sql_node(state: State) -> dict:
    """Wraps execute_sql() as a graph node. Classifies query intent to decide
    routing: 'count' → judge_and_reason, 'summary' → llm_validator."""
    sql = state.get("sql", "")
    if not sql:
        return {"rows": [], "query_intent": "count"}

    try:
        rows = await asyncio.to_thread(execute_sql, sql)

        # ── Hindi → English/Hinglish retry (Phase 4) ────────────────────
        # A content search (not hashtag/mention, which already ORs both
        # languages) that used only Hindi conditions and returned 0 rows
        # gets one more explicit shot at adding English/Hinglish OR
        # conditions before this turn falls through to the Qdrant fallback
        # (see _execute_decision's "zero_rows" branch below). Reuses
        # generate_sql()'s existing previous_sql/feedback mechanism — this
        # is one extra inline attempt within this node call, not a new
        # graph loop, so it can't run more than once per turn.
        if not rows and _sql_is_hindi_only_content_search(sql):
            hindi_retry_feedback = (
                "The previous SQL used only Hindi/Devanagari LIKE conditions "
                "for a content search (topic_title/input_text/post_title/"
                "reply_text) and returned 0 rows. Regenerate the SAME query, "
                "but ADD explicit English/Hinglish OR conditions for the same "
                "search terms alongside the existing Hindi conditions — do "
                "not remove the Hindi conditions, add to them."
            )
            add_trace("execute_sql", user_query=state["query"],
                       output="0 rows on Hindi-only content search — retrying with English/Hinglish feedback.")
            try:
                retry_sql = await asyncio.to_thread(
                    generate_sql,
                    state["query"],
                    sql,
                    hindi_retry_feedback,
                    state.get("selected_tables", []),
                )
                retry_sql = _inject_unassigned_exclusion(retry_sql)
                retry_sql = _inject_temporal_filter(retry_sql, state["query"])
                if is_safe_sql(retry_sql):
                    retry_rows = await asyncio.to_thread(execute_sql, retry_sql)
                    if retry_rows:
                        sql = retry_sql
                        rows = retry_rows
                        add_trace("execute_sql", output=f"English/Hinglish retry succeeded — {len(rows)} rows.")
                    else:
                        add_trace("execute_sql", output="English/Hinglish retry also returned 0 rows.")
            except Exception as exc:
                add_trace("execute_sql", output=f"English/Hinglish retry failed: {exc}")

        # Save to session log and last SQL context — capped to the most
        # recent entries so a long-running chat_id's Mongo doc doesn't grow
        # unbounded now that session_log is persisted turn-to-turn (see
        # matrix-app-report-pipeline pagination fix). _search_related_log_points
        # only ever looks at the most recent 5 anyway, so this cap doesn't
        # change behavior, just bounds storage.
        _SESSION_LOG_MAX_ENTRIES = 50
        session_log = state.get("session_log", [])
        session_log.append({
            "query": state["query"],
            "sql": sql,
            "row_count": len(rows)
        })
        if len(session_log) > _SESSION_LOG_MAX_ENTRIES:
            session_log = session_log[-_SESSION_LOG_MAX_ENTRIES:]
        original_query = state.get("original_query", state["query"])
        last_sql_context = f"Previous User Query: {original_query}\nStandalone Query: {state['query']}\nSQL Executed:\n{sql}\nReturned {len(rows)} rows."

        # Extract unique_topic_id + topic_title from results for Topic Reference Resolution
        topic_ids = []
        seen_ids = set()
        post_metadata = {}
        for row in rows:
            # Topic References: only the external unique_topic_id is valid
            # for follow-up endpoint/API calls. The numeric topic_id is an
            # internal DB key and must never be substituted for the UUID.
            tid = row.get("unique_topic_id")
            title = row.get("topic_title", "")
            if tid:
                tid = str(tid).strip()
            if tid and tid not in seen_ids:
                seen_ids.add(tid)
                topic_ids.append({"topic_id": tid, "title": str(title)[:300]})

            # Post Metadata Extraction (for URL sources)
            post_id = row.get("id") or row.get("post_id") or row.get("post_bank_id") or tid
            post_url = row.get("post_bank_post_url", "") or row.get("post_url", "") or row.get("url", "")
            source_type = row.get("source_type", "") or row.get("core_source", "") or row.get("platform", "")

            if post_id and post_url and str(post_url).startswith("http"):
                post_metadata[str(post_id)] = {
                    "url": post_url,
                    "platform": source_type,
                    "title": str(title)[:120],
                }

    except Exception as exc:
        add_trace("execute_sql", error=str(exc))
        return {"rows": [], "answer": f"SQL execution error: {exc}", "query_intent": "count"}

    # Classify query intent checking original query, corrected query, and standalone query
    combined_intent_text = f"{state.get('original_query', '')} {state.get('corrected_query', '')} {state.get('query', '')}"
    query_intent = await _classify_sql_query_intent(combined_intent_text)

    add_trace("execute_sql",
             output=f"{len(rows)} rows; intent={query_intent}")

    # ── Pagination bookkeeping ────────────────────────────────────────────
    # applied_pagination_offset is only set by generate_sql_node's pagination
    # branch (0 for every fresh, non-continuation query). The new cumulative
    # offset — "how many rows of this result set have now been shown in
    # total" — is what the NEXT "show more" continuation will OFFSET by.
    applied_offset = state.get("applied_pagination_offset", 0) or 0
    new_pagination_offset = applied_offset + len(rows)
    pagination_exhausted = bool(state.get("is_pagination_request")) and len(rows) == 0

    # NOTE: last_sql_context/last_topic_ids/post_metadata must be returned here,
    # not set via `state[...] = ...` — LangGraph only persists what a node
    # returns, so a direct mutation of the `state` argument is silently
    # discarded. (This was previously the case and is why post_metadata never
    # reached answer_node's "Source Links" section — URLs were computed here
    # every turn and then thrown away.)
    return {
        "sql": sql,
        "rows": rows,
        "query_intent": query_intent,
        "last_sql_context": last_sql_context,
        "last_topic_ids": topic_ids,
        "post_metadata": post_metadata,
        "last_executed_sql": sql,
        "last_sql_offset": new_pagination_offset,
        "pagination_exhausted": pagination_exhausted,
        "session_log": session_log,
    }


# =========================
# FALLBACK DECIDER NODE
# =========================

_RELATIONSHIP_QUERY_HINTS = (
    "follow", "followers", "following", "connected", "network",
    "related account", "linked to", "who follows", "mutual",
)


async def fallback_decider_node(state: State) -> dict:
    """
    Deterministically decides whether a query that returned NO results from
    MySQL should try Qdrant (keyword_search) first before Neo4j, or go
    straight to Neo4j (graph_query).

    This used to be an LLM call, but the graph wiring means BOTH routes
    always end up at neo4j_search anyway (content_index_search's only
    outgoing edge is straight into neo4j_search) -- so the model was never
    choosing between two independent strategies, only whether the Qdrant
    step ran first. That's a decision a keyword check can make just as
    well, so this removes one full LLM call from every zero-row fallback
    without changing what fallbackchecker (the actual accuracy gate on
    this branch) ever sees.
    """
    query = state["query"]
    retry_count = state.get("fallback_retry_count", 0)
    last_route = state.get("fallback_route", "")

    is_relationship_query = any(h in query.lower() for h in _RELATIONSHIP_QUERY_HINTS)

    if retry_count == 0:
        # First attempt: relationship-flavored queries ("who follows who")
        # skip straight to the graph; everything else tries
        # content_index_search first so its topic_id hints are available
        # to neo4j_search.
        route = "graph_query" if is_relationship_query else "keyword_search"
    else:
        # Retry after a failed attempt: alternate strategy from last time —
        # mirrors what the old LLM prompt's "you must choose the OTHER
        # option" instruction did, just without a model call.
        route = "graph_query" if last_route == "keyword_search" else "keyword_search"

    add_trace("fallback_decider", output=f"Route: {route} (deterministic, retry={retry_count})")
    return {"fallback_route": route}




# =========================
# CONTENT INDEX SEARCH — Qdrant vector + keyword fallback
# =========================

def embed_query_jina(query: str) -> list:
    """Embed a query string via the vLLM embeddings API (see embedder.py)."""
    try:
        return embedder.embed_query(query)
    except Exception as e:
        print(f"⚠️ Embedding error: {e}")
        return []


async def content_index_search_node(state: State) -> dict:
    """Fallback when execute_sql returns 0 rows: searches the Qdrant
    content_index collection (vector search + keyword fallback) and feeds
    the matched metadata back to table_selector_node for a retry.
    """
    query = state["query"]
    ci_retry = state.get("content_index_retry_count", 0)

    # Cap retries at 2
    if ci_retry >= 2:
        add_trace("content_index_search", output="retry limit reached — skipping")
        return {"content_index_hint": "", "answer": "No matching data found after retries."}

    hints = []

    # --- Phase 1: Vector search with Jina v3 embeddings ---
    try:
        vector = await asyncio.to_thread(embed_query_jina, query)
        if vector:
            results = await asyncio.to_thread(
                qdrant.query_points,
                collection_name=QDRANT_COLLECTION,
                query=vector,
                limit=5,
                with_payload=True,
            )
            for point in results.points:
                p = point.payload or {}
                if _is_junk_topic_text(p.get("text_content", "")):
                    continue  # skip the "unassigned/not relevant" catch-all bucket
                hints.append({
                    "source_table": p.get("source_table", ""),
                    "unique_topic_id": p.get("unique_topic_id", ""),
                    "text_preview": (p.get("text_content", ""))[:150],
                    "district": p.get("district", ""),
                    "sub_category": p.get("sub_category", ""),
                    "platform": p.get("platform", ""),
                    "score": round(point.score, 3),
                })
    except Exception as e:
        print(f"⚠️ Qdrant vector search error: {e}")

    # --- Phase 2: Keyword/BM25 fallback if vector search found nothing useful ---
    if not hints or all(h.get("score", 0) < 0.3 for h in hints):
        try:
            keywords = query.split()[:5]  # first 5 words as keyword terms
            for kw in keywords:
                if len(kw) < 3:
                    continue
                scroll_results = await asyncio.to_thread(
                    qdrant.scroll,
                    collection_name=QDRANT_COLLECTION,
                    scroll_filter=qdrant_models.Filter(
                        must=[
                            qdrant_models.FieldCondition(
                                key="text_content",
                                match=qdrant_models.MatchText(text=kw),
                            )
                        ]
                    ),
                    limit=3,
                    with_payload=True,
                )
                for point in scroll_results[0]:
                    p = point.payload or {}
                    if _is_junk_topic_text(p.get("text_content", "")):
                        continue  # skip the "unassigned/not relevant" catch-all bucket
                    hints.append({
                        "source_table": p.get("source_table", ""),
                        "unique_topic_id": p.get("unique_topic_id", ""),
                        "text_preview": (p.get("text_content", ""))[:150],
                        "district": p.get("district", ""),
                        "sub_category": p.get("sub_category", ""),
                        "platform": p.get("platform", ""),
                        "score": 0.0,
                        "match_type": "keyword",
                    })
                if hints:
                    break  # found something via keyword
        except Exception as e:
            print(f"⚠️ Qdrant keyword search error: {e}")

    # --- Build the hint string for table_selector_node ---
    if hints:
        hint_lines = []
        for h in hints[:5]:
            hint_lines.append(
                f"- table={h['source_table']}, unique_topic_id={h['unique_topic_id']}, "
                f"category={h['sub_category']}, district={h['district']}, "
                f"platform={h['platform']}, text={h['text_preview']}"
            )
        content_index_hint = "\n".join(hint_lines)
    else:
        content_index_hint = ""

    add_trace("content_index_search", user_query=query,
             output=f"{len(hints)} hints found; retry={ci_retry + 1}")

    return {
        "content_index_hint": content_index_hint,
        "content_index_retry_count": ci_retry + 1,
    }


# =========================
# NEO4J SEARCH NODE (runs after content_index_search)
# =========================

async def neo4j_search_node(state: State) -> dict:
    """Uses unique_topic_ids extracted by content_index_search to run a Cypher
    graph traversal in Neo4j. Returns rich relational context:
      - Who posted on this incident
      - Connected accounts ([:FOLLOWS])
      - Police tickets raised ([:RAISED_FOR])
      - Internal reports filed ([:FILED_FOR])
      - Locations involved ([:OCCURRED_IN])

    If Neo4j is unavailable or returns nothing, falls through to table_selector
    for the normal SQL retry path.
    """
    if state.get("neo4j_search_done"):
        # Already ran this turn — prevent infinite loop
        return {"neo4j_graph_context": "", "neo4j_search_done": True}

    if _neo4j_driver is None:
        add_trace("neo4j_search", output="skipped — Neo4j driver not available")
        return {"neo4j_graph_context": "", "neo4j_search_done": True}

    query = state.get("query", "")
    hint  = state.get("content_index_hint", "")

    # --- Extract unique_topic_ids from the Qdrant hint string ---
    # Qdrant payloads include unique_topic_id in the hint lines
    topic_ids = list(set(re.findall(r'unique_topic_id[=:]\s*([\w\-]+)', hint)))

    if not topic_ids:
        add_trace("neo4j_search", user_query=query, output="no topic_ids found in Qdrant hint — skipping")
        return {"neo4j_graph_context": "", "neo4j_search_done": True}

    cypher = """
    UNWIND $ids AS tid
    MATCH (i:Incident {topic_id: tid})
    OPTIONAL MATCH (c:Content)-[:BELONGS_TO]->(i)
    OPTIONAL MATCH (a:Account)-[:POSTED]->(c)
    OPTIONAL MATCH (c)-[:OCCURRED_IN]->(l:Location)
    OPTIONAL MATCH (t:Ticket)-[:RAISED_FOR]->(i)
    OPTIONAL MATCH (r:Report)-[:FILED_FOR]->(i)
    RETURN
        i.topic_id                          AS topic_id,
        i.title                             AS title,
        count(DISTINCT c)                   AS post_count,
        collect(DISTINCT a.username)[..10]  AS top_users,
        collect(DISTINCT l.name)[..5]       AS locations,
        count(DISTINCT t)                   AS ticket_count,
        count(DISTINCT r)                   AS report_count
    ORDER BY post_count DESC
    LIMIT 10
    """

    try:
        def _run_cypher():
            with _neo4j_driver.session() as session:
                result = session.run(cypher, ids=topic_ids)
                return [dict(rec) for rec in result]

        rows = await asyncio.to_thread(_run_cypher)
    except Exception as e:
        add_trace("neo4j_search", output=f"Cypher error: {e}")
        return {"neo4j_graph_context": "", "neo4j_search_done": True}

    # Drop the "unassigned/not relevant" catch-all bucket — same exclusion
    # generate_sql applies to raw SQL and content_index_search applies to
    # Qdrant hits. Belt-and-suspenders here in case a junk topic_id reaches
    # this node some other way.
    rows = [r for r in rows if not _is_junk_topic_text(r.get("title") or "")]

    if not rows:
        add_trace("neo4j_search", user_query=query, output="Neo4j returned 0 rows (or only junk/unassigned bucket)")
        return {"neo4j_graph_context": "", "neo4j_search_done": True}

    # --- Build a readable context block for judge_and_reason ---
    lines = ["[Neo4j Graph Context]"]
    for r in rows:
        users_str     = ", ".join(r.get("top_users") or []) or "N/A"
        locations_str = ", ".join(r.get("locations") or []) or "N/A"
        lines.append(
            f"Incident: {r.get('title') or r.get('topic_id')} | "
            f"Posts: {r.get('post_count', 0)} | "
            f"Top accounts: {users_str} | "
            f"Locations: {locations_str} | "
            f"Police tickets: {r.get('ticket_count', 0)} | "
            f"Internal reports: {r.get('report_count', 0)}"
        )

    # --- Also fetch follower connections for top posters ---
    top_users_flat = []
    for r in rows:
        top_users_flat.extend(r.get("top_users") or [])
    top_users_flat = list(set(top_users_flat))[:10]

    if top_users_flat:
        follower_cypher = """
        UNWIND $usernames AS uname
        MATCH (poster:Account {username: uname})
        OPTIONAL MATCH (follower:Account)-[:FOLLOWS]->(poster)
        RETURN poster.username AS poster, count(follower) AS follower_count,
               poster.verified AS verified
        ORDER BY follower_count DESC LIMIT 10
        """
        try:
            def _run_followers():
                with _neo4j_driver.session() as session:
                    result = session.run(follower_cypher, usernames=top_users_flat)
                    return [dict(rec) for rec in result]

            follower_rows = await asyncio.to_thread(_run_followers)
            if follower_rows:
                lines.append("[Account Network]")
                for fr in follower_rows:
                    verified = "✓ verified" if fr.get("verified") else ""
                    lines.append(
                        f"  @{fr.get('poster')} {verified} — "
                        f"{fr.get('follower_count', 0)} followers in graph"
                    )
        except Exception as e:
            print(f"⚠️ Neo4j follower query error: {e}")

    graph_context = "\n".join(lines)

    add_trace(
        "neo4j_search",
        user_query=query,
        output=f"{len(rows)} incidents found via graph traversal; topic_ids={topic_ids}"
    )

    return {
        "neo4j_graph_context": graph_context,
        "neo4j_search_done":   True,
        # Inject as content_index_hint so judge_and_reason / answer nodes see it automatically
        "content_index_hint":  graph_context,
        # Set rows to a non-empty sentinel so _execute_decision doesn't loop again
        "rows": [{"_source": "neo4j", "graph_context": graph_context}],
    }


# =========================
# FALLBACK CHECKER NODE
# =========================

async def fallbackchecker_node(state: State) -> dict:
    """
    Validates if the output from Neo4j (and potentially Qdrant) actually answers the original query.
    - PASS  → builds a MySQL hint from the graph context and routes to table_selector.
    - FAIL  → retries via fallback_decider up to 3 times.
    - 3 fails → sets fallback_exhausted=True and routes to query_rewriter to ask the user.
    """
    query = state["query"]
    # Both Qdrant and Neo4j populate content_index_hint
    graph_context = state.get("content_index_hint", "")
    retry_count = state.get("fallback_retry_count", 0)

    if not graph_context or "No matching data" in graph_context or "returned 0 rows" in graph_context:
        # Fast fail if empty
        add_trace("fallbackchecker", output=f"Fail: Empty context (retry {retry_count+1}/3)")
        return {"fallback_feedback": "Graph/Vector search returned empty results.", "fallback_retry_count": retry_count + 1}

    prompt = f"""
You are a validator. We attempted to answer the following query using a Graph Database (Neo4j) and Vector DB (Qdrant).
Check if the provided context CONTAINS the answer to the user's query.

Query: "{query}"

Context:
{graph_context}

If the context contains a satisfactory answer, reply with:
PASS: <one sentence explaining WHERE the data lives — e.g. which table/topic_id/incident title answered the query>

If the context is irrelevant, empty, or fails to answer the query, reply with:
FAIL: <brief reason why the context does not answer the query>
"""
    result = (await call_llm(prompt)).strip()

    if result.upper().startswith("PASS"):
        # Extract the reason (everything after "PASS: ")
        reason = result[5:].strip().lstrip(":" ).strip()
        # Build a hint that table_selector can use to form smarter SQL
        mysql_hint = (
            f"[Graph Search Hint] The Qdrant+Neo4j search found similar data for this query. "
            f"Reason: {reason}. "
            f"Use this context to write a more targeted MySQL SQL query: {graph_context[:500]}"
        )
        add_trace("fallbackchecker", output=f"Pass — hint built: {reason[:80]}")
        return {
            "fallback_feedback": "PASS",
            "content_index_hint": mysql_hint,
            "neo4j_search_done": False,  # allow re-run in next retry if needed
        }
    else:
        new_retry_count = retry_count + 1
        add_trace("fallbackchecker", output=f"Fail: {result[:60]}... (retry {new_retry_count}/3)")
        updates: dict = {"fallback_feedback": result, "fallback_retry_count": new_retry_count}
        if new_retry_count >= 3:
            updates["fallback_exhausted"] = True  # signal query_rewriter to ask user
        return updates

def _fallbackchecker_decision(state: State) -> str:
    """Routes based on fallbackchecker feedback.
    - PASS         → table_selector  (use graph hint to build smarter SQL)
    - retry (≤3x)  → fallback_decider (try different search strategy)
    - sql_fallback → query_rewriter  (exhausted — ask user for clarification)
    """
    feedback = state.get("fallback_feedback", "")
    if feedback == "PASS":
        return "pass"

    retry_count = state.get("fallback_retry_count", 0)
    if retry_count >= 3:
        return "sql_fallback"
    return "retry"

def _fallback_decider_decision(state: State) -> str:
    """Routes based on fallback_decider choice."""
    return state.get("fallback_route", "keyword_search")


# =========================
# GRAPH WIRING
# =========================
#
# START → query_rewriter → query_manager → check_query_manager
#   ├─ retry → query_rewriter
#   ├─ end → END
#   ├─ has_table_topic → keyword_of_post_maker → keyword_of_post_maker_and_checker → table_selector
#   └─ no_table_topic  → table_selector
#   table_selector → generate_sql → sql_judge
#     ├─ pass  → is_safe_sql → execute_sql
#     └─ retry → table_selector (loop, max 2)
#   execute_sql
#     ├─ judge     → judge_and_reason → answer → answer_checker → END / retry
#     ├─ summary   → llm_validator → judge_and_reason → answer → answer_checker → END / retry
#     └─ zero_rows → fallback_decider → content_index_search → neo4j_search → fallbackchecker
#                                            ├─ pass         → table_selector
#                                            ├─ retry        → fallback_decider
#                                            └─ sql_fallback → query_rewriter

def _sql_judge_decision(state: State) -> str:
    """sql_judge conditional edge: pass or retry."""
    if state.get("sql_matches", True):
        return "pass"
    return "retry"


def _execute_decision(state: State) -> str:
    """execute_sql conditional edge: judge, summary, or zero_rows.
    - 'count' intent → judge_and_reason (just format numbers)
    - 'summary' intent → llm_validator (batch-process row content)
    - 0 rows → content_index_search (fallback)
    """
    rows = state.get("rows", [])
    sql = state.get("sql", "")

    # If sql is empty (safety check failed), go straight to judge→answer
    if not sql:
        return "judge"

    # A pagination continuation ("show more") that legitimately ran out of
    # rows is not a failed search — skip the Qdrant/Neo4j fallback chase
    # (which would otherwise surface unrelated "similar data" for a request
    # that was never about finding new content) and let answer_node phrase
    # it plainly using the pagination_exhausted note.
    if state.get("pagination_exhausted"):
        return "judge"

    is_zero_result = False
    if not rows:
        is_zero_result = True
    elif len(rows) == 1:
        row = rows[0]
        if all(v == 0 or v is None for v in row.values()):
            is_zero_result = True

    if is_zero_result:
        ci_retry = state.get("fallback_retry_count", 0)
        if ci_retry < 3:
            return "zero_rows"
        else:
            return "judge"  # exhausted retries, let answer handle it

    # Route based on query intent classification
    intent = state.get("query_intent", "count")
    if intent == "summary":
        return "summary"

    return "judge"


def _query_rewriter_decision(state: State) -> str:
    if state.get("needs_clarification") or state.get("explain_request"):
        return "end"
    return "query_manager"


def _check_query_manager_decision(state: State) -> str:
    """check_query_manager conditional edge: an unresolved acronym/short-form not
    already in recycle_search gets grounded live and ends the turn HERE, asking
    the user (needs_clarification=True) — no hop back to query_rewriter; a
    real-world "is A connected to B" relationship query (2+ named entities)
    goes straight to web_relationship_search since our DB has no cross-topic
    join for that; queries with a table/topic (already classified) go through
    the keyword steps; everything else skips straight to table_selector."""
    if not state.get("is_query_correct", True):
        return "retry"
    if state.get("needs_clarification"):
        return "end"
    if state.get("is_relationship_query") and not state.get("relationship_search_done"):
        return "relationship_check"
    if state.get("has_table_topic", True):
        return "has_table_topic"
    return "no_table_topic"


def _keyword_of_post_maker_decision(state: State) -> str:
    """keyword_of_post_maker conditional edge: routes to go_duck_search only when
    no keywords were found and an unresolved short form/acronym was detected
    (a fallback for acronyms check_query_manager's classification step didn't
    catch); otherwise continues straight to the checker."""
    if not state.get("keywords") and not state.get("duck_search_done") and state.get("duck_search_term"):
        return "duck_search"
    return "checker"


def _keyword_of_post_maker_and_checker_decision(state: State) -> str:
    """keyword_of_post_maker_and_checker conditional edge: routes to
    go_duck_search_verify only when every keyword was dropped and an unresolved
    short form/acronym was detected; otherwise continues to table_selector."""
    if not state.get("keywords_checked") and not state.get("duck_search_verify_done") and state.get("duck_search_verify_term"):
        return "duck_search_verify"
    return "table_selector"


_builder = StateGraph(State)

# Add all nodes (exactly 20 DB-only nodes)
_builder.add_node("query_rewriter", query_rewriter_node)
_builder.add_node("query_manager", query_manager_node)
_builder.add_node("check_query_manager", check_query_manager_node)
_builder.add_node("keyword_of_post_maker", keyword_of_post_maker_node)
_builder.add_node("keyword_of_post_maker_and_checker", keyword_of_post_maker_and_checker_node)
_builder.add_node("go_duck_search", go_duck_search_node)
_builder.add_node("go_duck_search_verify", go_duck_search_verify_node)
_builder.add_node("web_relationship_search", web_relationship_search_node)
_builder.add_node("table_selector", table_selector_node)
_builder.add_node("generate_sql", generate_sql_node)
_builder.add_node("sql_judge", sql_judge_node)
_builder.add_node("is_safe_sql", is_safe_sql_node)
_builder.add_node("execute_sql", execute_sql_node)
_builder.add_node("fallback_decider", fallback_decider_node)
_builder.add_node("content_index_search", content_index_search_node)
_builder.add_node("neo4j_search", neo4j_search_node)
_builder.add_node("fallbackchecker", fallbackchecker_node)
_builder.add_node("llm_validator", llm_validator_node)
_builder.add_node("judge_and_reason", judge_and_reason_node)
_builder.add_node("answer", answer_node)
_builder.add_node("answer_checker", answer_checker_node)

def _answer_checker_decision(state: State) -> str:
    if state.get("answer_retry_count", 0) >= 2 or not state.get("answer_feedback"):
        return "end"
    return "retry"

_builder.set_entry_point("query_rewriter")

# query_rewriter → query_manager OR END (if needs clarification)
_builder.add_conditional_edges("query_rewriter", _query_rewriter_decision, {
    "end": END,
    "query_manager": "query_manager",
})

# query_manager → check_query_manager
_builder.add_edge("query_manager", "check_query_manager")

# check_query_manager → keyword steps (has table/topic), straight to table_selector,
# or (real-world relationship question) out to web_relationship_search
_builder.add_conditional_edges("check_query_manager", _check_query_manager_decision, {
    "retry": "query_rewriter",
    "end": END,
    "relationship_check": "web_relationship_search",
    "has_table_topic": "keyword_of_post_maker",
    "no_table_topic": "table_selector",
})

# web_relationship_search → answer (it already sets "reasoning" directly;
# rows/sql stay empty so answer_node's normal else-branch just writes from
# that reasoning text)
_builder.add_edge("web_relationship_search", "answer")

# keyword_of_post_maker → go_duck_search (unresolved short form) or checker
_builder.add_conditional_edges("keyword_of_post_maker", _keyword_of_post_maker_decision, {
    "duck_search": "go_duck_search",
    "checker": "keyword_of_post_maker_and_checker",
})
_builder.add_edge("go_duck_search", "keyword_of_post_maker")

# keyword_of_post_maker_and_checker → go_duck_search_verify (unresolved short form) or table_selector
_builder.add_conditional_edges("keyword_of_post_maker_and_checker", _keyword_of_post_maker_and_checker_decision, {
    "duck_search_verify": "go_duck_search_verify",
    "table_selector": "table_selector",
})
_builder.add_edge("go_duck_search_verify", "keyword_of_post_maker_and_checker")

# Database path
_builder.add_edge("table_selector", "generate_sql")
_builder.add_edge("generate_sql", "sql_judge")

# sql_judge → pass (continue) or retry (loop back to table_selector)
_builder.add_conditional_edges("sql_judge", _sql_judge_decision, {
    "pass": "is_safe_sql",
    "retry": "table_selector",
})

_builder.add_edge("is_safe_sql", "execute_sql")

# execute_sql → judge, summary, or zero_rows
_builder.add_conditional_edges("execute_sql", _execute_decision, {
    "judge": "judge_and_reason",
    "summary": "llm_validator",
    "zero_rows": "fallback_decider",
})

# fallback_decider → keyword_search OR graph_query
_builder.add_conditional_edges("fallback_decider", _fallback_decider_decision, {
    "keyword_search": "content_index_search",
    "graph_query": "neo4j_search",
})

# content_index_search → neo4j_search (uses Qdrant topic_ids to do graph traversal)
_builder.add_edge("content_index_search", "neo4j_search")

# neo4j_search → fallbackchecker (evaluate context)
_builder.add_edge("neo4j_search", "fallbackchecker")

# fallbackchecker → table_selector (PASS: smarter SQL with hint), fallback_decider (retry), query_rewriter (exhausted)
_builder.add_conditional_edges("fallbackchecker", _fallbackchecker_decision, {
    "pass": "table_selector",          # graph found similar data → retry MySQL with hint
    "retry": "fallback_decider",        # wrong answer → try different search strategy
    "sql_fallback": "query_rewriter",   # 3 fails → ask user for clarification
})

def _llm_validator_decision(state: State) -> str:
    """llm_validator conditional edge: routes directly to END when clarification is needed;
    otherwise continues to judge_and_reason to reason over the batch-extracted context."""
    if state.get("needs_clarification"):
        return "end"
    return "judge"

# llm_validator → judge_and_reason OR END
_builder.add_conditional_edges("llm_validator", _llm_validator_decision, {
    "end": END,
    "judge": "judge_and_reason",
})

# judge_and_reason → answer → answer_checker
_builder.add_edge("judge_and_reason", "answer")
_builder.add_edge("answer", "answer_checker")

# answer_checker → END or retry(answer)
_builder.add_conditional_edges("answer_checker", _answer_checker_decision, {
    "end": END,
    "retry": "answer",
})

# Compile the graph
graph = _builder.compile()


# =========================
# CLI
# =========================

async def main():
    print("UP Police Matrix SQL assistant (LangGraph pipeline).")
    print("Ask a question in English or Hindi, or type 'exit' to quit.\n")
    messages = []  # in-memory conversation history for this run
    session_log = [] # in-memory history of executed SQL and results
    last_topic_ids = []  # topic IDs from the most recent SQL result
    last_executed_sql = ""  # exact SQL from the most recent turn, for "show more"/"next N" pagination
    last_sql_offset = 0     # cumulative rows already shown for last_executed_sql's result set
    pending_keyword_confirmation = None  # set when ask_user/classification is waiting on a yes/no reply

    while True:
        question = input("\n> ").strip()
        if not question or question.lower() in ("exit", "quit"):
            break

        state = {
            "query": question,
            "original_query": question,
            "query_manager_feedback": "",
            "query_manager_retry_count": 0,
            "is_query_correct": True,
            "messages": messages,
            "corrected_query": "",
            "rewrite_context": "",
            "expert_name": "",
            "selected_tables": [],
            "table_reason": "",
            "sql": "",
            "sql_matches": True,
            "sql_match_reason": "",
            "retry_count": 0,
            "content_index_hint": "",
            "content_index_retry_count": 0,
            "rows": [],
            "is_dashboard_query": False,
            "query_intent": "count",
            "validated_sql_context": "",
            "reasoning": "",
            "answer": "",
            "needs_clarification": False,
            "explain_request": False,
            "last_sql_context": session_log[-1].get("sql", "") if session_log else "",
            "session_log": session_log,
            "last_topic_ids": last_topic_ids,
            "last_executed_sql": last_executed_sql,
            "last_sql_offset": last_sql_offset,
            "resolved_topic_reference": "",
            "post_metadata": {},
            "answer_feedback": "",
            "answer_retry_count": 0,
            "pending_keyword_confirmation": pending_keyword_confirmation,
        }

        try:
            result = await graph.ainvoke(state)
        except Exception as exc:
            print(f"Error: {exc}")
            continue

        standalone_query = result.get("query", question)
        if standalone_query != question:
            print(f"Standalone query: {standalone_query}")
        if result.get("selected_tables"):
            print(f"Tables: {result['selected_tables']}")
        if result.get("sql"):
            print(f"\nSQL:\n{result['sql']}")
        rows = result.get("rows") or []
        if rows:
            print(f"\nRows ({len(rows)}):")
            for row in rows[:50]:
                print(row)
        if result.get("answer"):
            print(f"\n{result['answer']}")

        # Persist topic IDs from this turn for next turn's reference resolution
        if result.get("last_topic_ids"):
            last_topic_ids = result["last_topic_ids"]

        # Persist pagination state for a possible "show more"/"next N" next turn
        if result.get("last_executed_sql"):
            last_executed_sql = result["last_executed_sql"]
            last_sql_offset = result.get("last_sql_offset", 0)

        # Carry a pending ask_user/classification confirmation into the next turn
        pending_keyword_confirmation = result.get("pending_keyword_confirmation")

        messages.append({"role": "user", "content": question})
        messages.append({"role": "assistant", "content": result.get("answer") or ""})


if __name__ == "__main__":
    asyncio.run(main())