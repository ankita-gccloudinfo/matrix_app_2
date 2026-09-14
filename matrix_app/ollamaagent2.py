LLM_BACKEND = "vllm" # Change to "ollama" to use the Ollama backend

VLLM_BASE_URL = "http://10.242.71.180:2211/v1"
VLLM_MODEL_NAME = "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8"
VLLM_API_KEY = "EMPTY"  # vLLM ignores this unless it was started with --api-key

OLLAMA_URL = "http://10.242.24.35:11434/api/generate"
OLLAMA_MODEL_NAME = "qwen3-coder:30b"

MYSQL_HOST = "10.242.71.180"
MYSQL_PORT = "3306"
MYSQL_USER = "readUser"
MYSQL_PASSWORD = "readUser@123"
MYSQL_DB = "up_police_matrix"

QDRANT_HOST_DEFAULT = "10.242.24.35"
QDRANT_PORT_DEFAULT = 6333
QDRANT_COLLECTION = "content_index"
JINA_API_URL = "https://api.jina.ai/v1/embeddings"
JINA_MODEL = "jina-embeddings-v3"

NEO4J_URI      = "bolt://10.242.24.35:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "YourStrongPassword"


DB_SCHEMA_YAML = """
database_schema:
  tables:
    - name: topic
      purpose: in this we have one topic of 100 post as like i got muder in jewllery shop then i got 100 post in this i have one topic and that topic is conntected to that 100 post.

      columns:
        id: INT (Primary Key)
        unique_topic_id: VARCHAR (Unique identifier shared across all related tables)
        topic_title: VARCHAR (Title of the topic/incident. STORED IN HINDI/Devanagari — e.g., 'रायबरेली - नशेड़ी पति ने पत्नी पर चाकू से हमला'. To text-search this column you MUST use the HINDI form of the term; an English-only LIKE will match nothing.)
        total_no_of_post: INT (Total posts associated with this topic)
        primary_districts: JSON (List of districts associated with the topic. ALWAYS consider only the first element as the primary district, e.g., ["Gorakhpur", "Varanasi"])
        sub_category: VARCHAR (Category of the topic, e.g., MURDER, FAKE NEWS, COMMUNAL, PROTEST, ACCIDENT amd many more )
        created_at: TIMESTAMP (When the topic created first time )
      use_case: Use when the user asks for topics, incidents, categories, summaries, statistics, metadata, or aggregated information. Use created_at only when the user explicitly wants topic creation time or time-based filtering on topics. this is like overview of 100 post like i asked what is happen in lucknow then use this table

    - name: analyzed_data
       purpose: Stores individual social media posts and their metadata as i told able as 100 post on one topic as in this we have thse 100 post in this related to that one topic .
      columns:
        id: INT (Primary Key)
        unique_topic_id: VARCHAR (Links individual post to its main topic)
        input_text: TEXT (Raw content/text of the social media post. LANGUAGE IS MIXED — the same column holds Hindi (Devanagari), English, and Hinglish across different rows, often within one row. Text-search it with BOTH the English and the Hindi form of the term, OR'd together.) this is given by user on social media 
        primary_district: VARCHAR (District related to the post. If multiple, use the first element) as post is related to which district and given by which district 
        primary_thana: VARCHAR (Police station mentioned in the post, may be NULL) this is not important but you should know as post related to which district
        primary_location: VARCHAR (Specific location of post, e.g. a town/building) this is for small level of search as we will not use this we will use only when query is not match with district then only match 
        topic_title: VARCHAR (Associated topic title. STORED IN HINDI/Devanagari — text-search it with the HINDI form of the term.) this is same topic of database tables name of topic
        created_at: TIMESTAMP (Post creation time)
        sub_category: TEXT (JSON array string of category tags for this post, e.g. '["HATE SPEECH", "TRAFFIC"]'. See CATEGORY COUNTING rule 11a — never GROUP BY directly, use one LIKE per category or JSON_TABLE to explode.)
        sentiment_label: VARCHAR (Sentiment: Positive, Neutral, Negative) by this you can able to understand the post is positive or negative or neutral
        post_bank_post_url: VARCHAR (Original URL of the social media post)as post url is this 
        source_type: VARCHAR (Platform category, e.g. 'social_media', 'news', 'whatsapp', 'other'. NEVER use this column to filter by specific platform names like 'facebook', 'twitter', 'instagram', 'youtube')
        post_bank_core_source: VARCHAR (Core platform source, e.g. 'TWITTER', 'facebook', 'whatsapp', 'instagram', 'YouTube', 'News_Rss_Feed', 'Google_News'. ALWAYS use this column for specific platform filtering like 'facebook', 'twitter', 'instagram', 'youtube')
        post_bank_author_name: VARCHAR (Name of the author/person who created the post on social media ) 
        post_bank_author_username: VARCHAR (Username of the author/person who created the post as this is unique name of author like @username , or akileshyadav , @akileshyadav,yadavakilesh , @yadavakilesh and many more)
      Use only when the user explicitly requests post-level information such as post text, URLs, sources, authors, locations, police stations (thana), sentiments, keywords, or specific social media platforms.when user as like in this fire incident in lucknow then show all the post related to this fire incident in lucknow and show the post url, author name, author username, sentiment of post and many more. then use this 

    # ============================================================
    # CONTENT HUB (raw post record — join target for engagement)
    # ============================================================
    - name: post_bank
      alias: pb
      purpose: Canonical raw social media post table. This is the CENTRAL CONTENT RECORD for every social media post. 
    All engagement-related tables (likes, retweets, replies, comments, interactions) connect to this table using:
    engagement_table.post_bank_id = post_bank.id.
    The analyzed_data table contains AI-enriched analysis of these posts and connects using:
    analyzed_data.dump_table_id = post_bank.id.
    relationship:
    primary_key:
      id -> Referenced by analyzed_data.dump_table_id
      id -> Referenced by all engagement tables as post_bank_id
      columns:
        id: INT (Primary Key — referenced as post_bank_id by every engagement table)
        post_title: TEXT (Raw post content. LANGUAGE IS MIXED — Hindi (Devanagari), English, and Hinglish across rows. Text-search it with BOTH the English and the Hindi form of the term, OR'd together.)
        post_url: TEXT
        core_source: VARCHAR (e.g. TWITTER, facebook, whatsapp, instagram, YouTube, News_Rss_Feed)
        post_timestamp: DATETIME
        author_name: VARCHAR
        author_username: VARCHAR
        likes: INT
        retweets: INT
        comments: INT
        views: BIGINT
        bookmarks: INT
        post_type: VARCHAR
        is_reply: BOOLEAN
        in_reply_to_username: VARCHAR
      use_case: Use as the JOIN ANCHOR whenever the user's question needs to connect a post to WHO engaged with it (liked/retweeted/replied/commented). Also usable directly for raw post lookups by url/author and he give a url and want to know about for specific posts view and comments and to check is this post give reply or not.

    # ============================================================
    # ACTOR HUB (the "person/handle" node of the social graph)
    # ============================================================
    - name: post_users
      alias: pu
    purpose: Canonical identity/profile record for social media users (authors, creators, retweeters, repliers, commenters, and other actors). This table stores complete information about a social media account, including username, display name, profile details, follower/following information, posting activity, verification status, business status, and engagement metrics.
        It acts as the ACTOR HUB referenced by post_user_id in post and engagement tables and by user_id/follower_id in profile_network.

    columns:
        id: INT (Primary Key — referenced as post_user_id / user_id / follower_id elsewhere)
        platform: VARCHAR (twitter, facebook, instagram, youtube)
        username: VARCHAR
        display_name: VARCHAR
        followers_count: BIGINT
        following_count: BIGINT
        posts_count: INT
        is_verified: BOOLEAN
        is_business: BOOLEAN
        account_status: VARCHAR
        location: VARCHAR
        total_engagement: BIGINT
        bio_description: TEXT (Profile bio/description text)
        profile_image_url: TEXT (Profile picture URL)
        use_case:
    Use this table whenever the user asks about a specific person/account/handle, wants user details instead of only a numeric user ID, or needs actor-level analysis.

    Examples:
      - Find details of a social media user/account
      - Get username, display name, bio, location, follower count, verification status
      - Analyze a person's posting activity and engagement
      - Identify who created, replied, retweeted, or interacted with posts

    # ============================================================
    # ACTOR-TO-ACTOR EDGES (who is connected to whom)
    # ============================================================
    - name: profile_network
  alias: pn
    purpose: Stores social connection relationships between two social media accounts from post_users. 
        This table represents the follower/following network graph, where each row shows a connection between a user and another user on the same platform.
        It helps identify who follows an account, who an account follows, and the relationship direction between users.

    relationship:
        user_id -> post_users.id (The account being followed / target account)
        follower_id -> post_users.id (The account that follows the target account)

    columns:
        user_id: INT (Foreign Key -> post_users.id. The account/profile that has followers or the account being followed)

        follower_id: INT (Foreign Key -> post_users.id. The account/person following another account)

        relationship_type: VARCHAR (Type of relationship. Examples: FOLLOWER, FOLLOWING)

        platform: VARCHAR (Social media platform where the relationship exists. Examples: twitter, facebook, instagram, youtube)

        relationship_created_at: DATETIME (Time when the follower/following relationship was recorded)

        status: VARCHAR (Current status of the relationship, if available)

    use_case:
        Use this table for network-based questions involving social media accounts, such as:
        - Who follows this user/account?
        - Who does this account follow?
        - Find followers of a specific person/page
        - Analyze connections between two accounts
        - Build follower network graphs

    - name: user_connections
    alias: uc
    purpose: Stores analyzed relationships between monitored social media actors from user_monitoring. 
        This is the PRIMARY table for "who connects to whom" analytics. 
        Each row represents a relationship edge between two monitored users and describes the type, direction, and strength of the connection.
        It captures both direct social relationships (FOLLOWER/FOLLOWING) and interaction-based relationships (MENTIONED, REPLIED, RETWEETED, MUTUAL).

    relationship:
        source_user_id -> user_monitoring.id (The monitored user who creates or initiates the connection)
        target_user_id -> user_monitoring.id (The monitored user who receives or is connected through the relationship)

    columns:
        source_user_id: INT (Foreign Key -> user_monitoring.id. The actor/user initiating the relationship or interaction)

        target_user_id: INT (Foreign Key -> user_monitoring.id. The actor/user connected with the source user)

        connection_type: ENUM (Defines the relationship type:
        FOLLOWER = source user follows target user,
        FOLLOWING = source user is followed by target user,
        MENTIONED = source user mentioned target user,
        MUTUAL = both users have a mutual relationship,
        REPLIED = source user replied to target user's content,
        RETWEETED = source user reshared target user's content)

        connection_strength: FLOAT (0-1 score representing the strength/intensity of the relationship based on frequency, interactions, or relevance)

        discovered_at: DATETIME (Time when the connection was detected or created)

        is_active: BOOLEAN (Indicates whether the connection is currently active)

    use_case:
        Use this table whenever the user asks about relationship analysis between monitored accounts, such as:
        - Who is connected to whom?
        - What type of connection exists between two accounts?
        - Which accounts frequently interact with each other?
        - Find strongest connections between monitored users
        - Rank users by interaction strength
        - Identify networks through mentions, replies, retweets, or follows

    join_examples:
        Source user information:
        user_connections.source_user_id = user_monitoring.id

        Target user information:
        user_connections.target_user_id = user_monitoring.id

    difference_from_other_tables:
        profile_network:
        Stores raw follower/following relationships between all social media users.

        user_connections:
        Stores analyzed and weighted relationships only between monitored users, including interaction-based links such as mentions, replies, and retweets.
            
    - name: post_user_interactions
    alias: pui
    purpose: Generic interaction log that connects a social media actor (post_user) with a specific post (post_bank).
        This table records individual user actions performed on posts, such as LIKE, RETWEET, QUOTE, REPLY, BOOKMARK, and other engagement activities.
        It is the central table for identifying which users interacted with a particular post and what type of interaction they performed.

    relationship:
        post_bank_id -> post_bank.id (The post/content receiving the interaction)
        post_user_id -> post_users.id (The user/account performing the interaction)

    columns:
        post_bank_id: INT (Foreign Key -> post_bank.id. Identifies the post where the interaction occurred)

        post_user_id: INT (Foreign Key -> post_users.id. Identifies the user/actor who performed the interaction)

        interaction_type: VARCHAR (Type of interaction performed by the user. Examples:
        LIKE,
        RETWEET,
        QUOTE,
        REPLY,
        BOOKMARK,
        and other supported interaction types)

        interacted_at: DATETIME (Timestamp when the interaction happened)

        source: VARCHAR (Platform/source from which the interaction was collected)

    use_case:
        Use this table for post-level engagement questions where the user wants to know:
        - Who liked this post?
        - Who retweeted this post?
        - Who quoted this post?
        - Who replied to this post?
        - Who bookmarked this post?
        - What users interacted with a specific post?
        - What type of interaction did a user perform on a post?

    join_examples:
        Get post details:
        post_user_interactions.post_bank_id = post_bank.id

        Get user details:
        post_user_interactions.post_user_id = post_users.id

    difference_from_other_tables:
        post_bank:
        Stores the original social media content/post.

        post_users:
        Stores user/account profile information.

        post_user_interactions:
        Stores individual user actions on individual posts.

        user_connections:
        Stores broader relationships between monitored users, while this table stores specific interactions with specific posts.
       
    - name: reply
      alias: rp
      purpose: Stores individual replies/comments made on posts from `post_bank`.
    Each record represents a reply event and captures the reply content, the
    person who created the reply, the original post/account being replied to,
    and reply-level engagement details.

    This is the authoritative table for reply-level analysis, including
    conversation threads, reply content analysis, reply authors, and reply
    activity metrics.

  relationship:
    post_bank_id -> post_bank.id (The original post receiving the reply)
    post_user_id -> post_users.id (The original post author/account being replied to)

      columns:
        post_bank_id: INT (FK -> post_bank.id)
        post_user_id: INT (FK -> post_users.id, the ORIGINAL author being replied to)
        reply_text: TEXT (Reply content. LANGUAGE IS MIXED — Hindi (Devanagari), English, and Hinglish across rows. Text-search it with BOTH the English and the Hindi form of the term, OR'd together.)
        reply_author_username: VARCHAR
        reply_author_display_name: VARCHAR
        reply_author_followers_count: INT
        reply_created_at: DATETIME
        reply_like_count: INT
        in_reply_to_user_id: VARCHAR
        conversation_id: VARCHAR
      
     use_cases:
        - Find who replied to a post or account.
        - Analyze reply content.
        - Perform sentiment analysis on replies.
        - Count replies or measure reply volume.
        - Find highly liked replies.
        - Analyze conversation threads.
        - Track reply activity around posts.


    - name: engagement_metric
      alias: em
      purpose:  Stores pre-aggregated engagement statistics for posts from `post_bank`.
        Each record contains post-level engagement totals such as likes, comments,
        shares, views, reach, and engagement rate.

        This table is optimized for performance and should be used whenever only
        overall post engagement metrics are required. It avoids expensive
        aggregation over raw interaction tables when individual actor details are
        not needed.

    This table contains total engagement numbers at post level and should be used when only overall performance metrics are required.
    It avoids expensive aggregation over raw interaction tables when individual actor details are not needed.

  relationship:
    post_bank_id -> post_bank.id (The post for which engagement metrics are calculated)
columns:
        post_bank_id: INT (FK -> post_bank.id)
        platform_type: VARCHAR
        content_type: VARCHAR
        likes: INT
        comments: INT
        shares: INT
        views: BIGINT
        reach: BIGINT
        engagement_rate: FLOAT
    use_cases:
        - Find the most engaged posts.
        - Find the most liked posts.
        - Find the most commented posts.
        - Find the most shared posts.
        - Find the most viewed posts.
        - Compare engagement performance across platforms.
        - Retrieve aggregate post engagement statistics.


    # ============================================================
    # TAXONOMY / LOOKUP TABLES
    # ============================================================
    - name: broad_category
      alias: bc
      purpose:     Master taxonomy of Broad Categories used for content classification. Each
        Broad Category represents a top-level classification (for example, CRIME,
        PROTEST, or ACCIDENT) under which one or more Sub Categories are organized.

        This is the authoritative table for Broad Category definitions and
        category hierarchy.

      columns:
        id: INT (Primary Key)
        broad_category: VARCHAR
        priority: INT
      usage_rules:
        - Use this table for ALL Broad Category master-data queries.
        - Join with `sub_category` using:
        `broad_category.id = sub_category.broad_category_id`
        - Join with `keywords` using:
        `broad_category.id = keywords.broad_category_id`
        - Use `broad_category` as the canonical category name in responses.
        - Use `priority` only for ordering or displaying categories.
        - Do NOT interpret `priority` as a business severity or ticket priority.

    use_cases:
        - List all Broad Categories.
        - Find the Broad Category for a Sub Category.
        - Retrieve all Sub Categories under a Broad Category.
        - Explain the category hierarchy.
        - Join category names for keyword, topic, or ticket classification.
        

    - name: sub_category
      alias: sc
      purpose:     Master taxonomy of Sub Categories used for content classification. Each
        Sub Category belongs to a Broad Category and has an associated business
        priority (HIGH/MEDIUM/LOW) along with an internal ranking used for
        resolving multiple category matches.

        This is the authoritative table for Sub Category definitions, priorities,
        and Broad Category mappings.
      columns:
        id: INT (Primary Key)
        sub_category: VARCHAR
        priority: VARCHAR (HIGH / MEDIUM / LOW — the sub-category's priority level. Compare case-insensitively, stored casing may vary, e.g. 'High'/'HIGH'.)
        classify_sub_priority: INT (Numeric rank used ONLY to pick the WINNING sub-category when a ticket/topic is tagged with several — the match with the LOWEST value wins. See TICKET DASHBOARD rule for the exact pattern; do not use this for general priority filtering, use `priority` for that.)
        broad_category_id: INT (FK -> broad_category.id)
      usage_rules:
        - Use this table for ALL Sub Category master-data queries.
        - Join with `broad_category` using `broad_category_id` to retrieve the parent Broad Category name.
        - Filter by `priority` for HIGH, MEDIUM, or LOW priority queries.
        - Compare `priority` values case-insensitively.
        - Use `classify_sub_priority` ONLY to resolve the winning Sub Category when multiple Sub Categories are assigned.
        - The Sub Category with the smallest `classify_sub_priority` value takes precedence.
        - Do NOT use `classify_sub_priority` for filtering, grouping, sorting by business priority, or reporting.
        use_cases:
        - List all Sub Categories.
        - Show HIGH, MEDIUM, or LOW priority Sub Categories.
        - Find the Broad Category for a Sub Category.
        - Retrieve the priority of a Sub Category.
        - Resolve the winning Sub Category when multiple classifications exist.
        - Join category names for keyword, topic, or ticket classification.


    - name: keywords
      alias: kw
      purpose: Master keyword dictionary used for content classification. Each record maps
    English, Hindi, and Hinglish keywords to their corresponding Broad Category
    and Sub Category.
      columns:
        id: INT (Primary Key)
        english_keyword: TEXT
        hindi_keyword: TEXT
        hinglish_keyword: TEXT
        broad_category_id: INT (FK -> broad_category.id)
        sub_category_id: INT (FK -> sub_category.id)
        usage_rules:
            - Use this table for ALL keyword-to-category mapping queries.
            - Search across `english_keyword`, `hindi_keyword`, and `hinglish_keyword` based on the user's input language.
            - Join with `broad_category` using `broad_category_id` to retrieve the Broad Category name.
            - Join with `sub_category` using `sub_category_id` to retrieve the Sub Category name.
            - Use this table to explain how keywords are classified into categories.
            - When listing keywords for a category, filter by the corresponding Broad Category or Sub Category ID.

        use_cases:
            - List keywords belonging to a Broad Category.
            - List keywords belonging to a Sub Category.
            - Find the category of a given keyword.
            - Explain keyword classification logic.
            - Show English, Hindi, and Hinglish variants of keywords.
            - Retrieve all keywords mapped to a category.


    - name: hashtags
      alias: ht
      purpose: Master list of monitored hashtags used for social media monitoring. Each
    record represents a tracked hashtag along with its English/Hindi variants,
    category, monitoring priority, and vertical classification.

    This is the authoritative table for hashtag monitoring queries.
      columns:
        id: INT (Primary Key)
        hashtag_keyword: VARCHAR
        hashtag_hindi_keyword: VARCHAR
        hastag_keyword_category: VARCHAR
        priority: VARCHAR
        vertical: VARCHAR
       usage_rules:
        - Use this table for ALL monitored hashtag queries.
        - Search both `hashtag_keyword` and `hashtag_hindi_keyword` when users provide hashtag names in English or Hindi.
        - Filter by `hastag_keyword_category` for category-wise hashtag requests.
        - Filter by `vertical` for vertical-specific hashtag requests.
        - Use `priority` when the user requests high-, medium-, or low-priority hashtags.
        - Return both English and Hindi hashtag variants whenever available.

     use_cases:
        - List all monitored hashtags.
        - Show hashtags for a category.
        - Show hashtags for a vertical.
        - List high-priority hashtags.
        - Find whether a hashtag is monitored.
        - Search monitored hashtags in English or Hindi.

    - name: category_handle_master
      alias: chm
      purpose:    Master mapping of monitoring categories to their associated social media
        handles/accounts. Each record represents a monitored account belonging to a
        specific category, along with its display name and profile URL.

        This is the authoritative table for category-to-handle mappings.
      columns:
        id: INT (Primary Key)
        category_name: TEXT
        handle_name: TEXT
        name: TEXT
        profile_url: TEXT
        usage_rules:
            - Use this table whenever the user asks which handles/accounts belong to a category.
            - Filter using `category_name`.
            - Return `handle_name`, `name`, and `profile_url` as appropriate.
            - If the user asks for all monitored handles within a category, query this table.
            - If the user asks whether a specific handle belongs to a category, verify using this table.

        use_cases:
            - List monitored handles under a category.
            - Show all accounts mapped to a category.
            - Find the category for a given handle.
            - Check whether a handle is monitored.
    - Retrieve profile URLs for monitored accounts.

    - name: monitor_profiles
    alias: mp
    purpose: >
        Registry of all monitored social media profiles across supported platforms.
        Each record represents a profile being monitored, along with its platform,
        category, monitoring priority, username/handle, and classification metadata.

        This is the authoritative table for monitored profile lookup and profile-based
        post tagging analysis.

        Use this table to identify monitored accounts and connect them with posts where
        they are mentioned/tagged.

    columns:
        id: INT (Primary Key)
        category: VARCHAR (ALWAYS stored in ENGLISH — e.g. 'DGP UP', 'TRAFFIC POLICE', 'STF', 'CYBER CRIME' — regardless of what language the user's question is in. If the user asks in Hindi/Hinglish, TRANSLATE the category term to its English form before filtering this column. Do NOT apply multilingual/free-text search on this column. This is a closed-set English category field.)
        platform: VARCHAR (Social media platform of the monitored profile, e.g. Twitter, Facebook, Instagram, YouTube)
        profile_link: VARCHAR (Official profile URL/link of the monitored account)
        user_name: VARCHAR (Social media username/handle of the monitored profile. This value is used to match mentions/tags from posts. When checking tagged posts, compare this value with analyzed_data.mention_ids_extracted. Remove leading '@' before matching and use case-insensitive comparison.)
        priority_order: INT (Ranking/order priority of monitored profiles. Use only for sorting or ranking monitored profiles.)
        sub_category: TEXT (Associated sub-categories/classification tags of the monitored profile.)

    usage_rules:
        - Use this table for ALL monitored-profile related queries.
        - When the user asks:
            "Which posts tag DGP?"
            "Show posts mentioning Traffic Police"
            "Find posts where this account is tagged"
        use this table to identify the profile username/handle first.
        - To find posts where a monitored profile is tagged:
        JOIN monitor_profiles mp
        ON LOWER(a.mention_ids_extracted)
        LIKE CONCAT('%', LOWER(TRIM(LEADING '@' FROM mp.user_name)), '%')
        where:
        a = analyzed_data
        - Do NOT join monitor_profiles directly with analyzed_data using id. There is NO foreign key relationship.
        - Use mention_ids_extracted for tag/mention based searches, not input_text or topic_title.
        - Translate Hindi/Hinglish category names to English before filtering category.
        - Match category using exact English values.
        - Use priority_order when ranking or sorting monitored profiles.
        - Filter by platform when the user requests platform-specific profiles.

    use_cases:
        - List monitored profiles.
        - Show monitored profiles by category.
        - Show monitored profiles by platform.
        - List profiles in priority order.
        - Find whether a profile is monitored.
        - Count monitored profiles by category or platform.
        - Find all posts where a monitored profile is tagged/mentioned.
        - Identify which monitored government/person/account handles are mentioned in posts.
        - Answer questions like:
            "DGP is tagged in which posts?"
            "Show posts mentioning @dgpup"
            "Which incidents mention Traffic Police handle?"
            

    # ============================================================
    # WORKFLOW / OPERATIONAL TABLES (pending reports)
    # ============================================================
    - name: district_internal_report
      alias: dir
        purpose: >
            Stores internal reports submitted by districts for topics that have been
            flagged by Headquarters/DGP (`topic.request_internal_report = '1'`).

            This is a workflow tracking table—not a topic/content table.

            The presence of a record indicates the district has submitted its internal
            report. The absence of a record (for the same `unique_topic_id`) indicates
            the report is still pending.
    columns:
        id: INT (Primary Key)
        unique_topic_id: VARCHAR (FK -> topic.unique_topic_id. A row existing here for a topic means that topic's report is no longer pending.)
        district: VARCHAR (District that submitted the report)
        crime_type: VARCHAR
        virality: VARCHAR
        fir: VARCHAR (YES/NO — whether an FIR was registered)
        fir_date: VARCHAR
        fir_no: VARCHAR
        arrest_status: VARCHAR
        creation_date: VARCHAR (When the report was submitted)
    usage_rules:
        - Use this table ONLY for internal-report workflow tracking.
        - Determine report status using the existence of a matching unique_topic_id.
        - A matching row = Submitted.
        - No matching row = Pending.
        - Pending report queries should use NOT EXISTS (or equivalent anti-join) against this table.
        - Only topics with topic.request_internal_report = '1' are eligible for internal reports.
        - Join using:
        topic.unique_topic_id = district_internal_report.unique_topic_id

    use_cases:
        - Count pending internal reports.
        - List pending internal reports.
        - Count submitted internal reports.
        - Check whether a district has submitted a report.
        - Pending Reports dashboard.
        - Workflow monitoring for DGP/HQ requested reports.

    # ============================================================
    # TICKET DASHBOARD TABLES
    # ============================================================
    - name: ticket_raised_table
      alias: trt
    purpose: >
        Stores workflow tickets raised against topics. A ticket is an operational
        tracking record and is NOT the same as a topic. A topic may exist without a
        ticket, and each ticket represents the workflow state of a topic.

        This is the authoritative table for all Ticket Dashboard metrics, including:
        - Total tickets
        - Status-wise counts (Assigned, In Progress, Resolved, Closed, Discarded)
        - District-wise, Zone-wise, Range-wise, Commissionerate-wise, Broad Category-wise,
        and Sub Category-wise ticket analysis.

      columns:
        id: INT (Primary Key. topic.ticket_raised_id -> ticket_raised_table.id)
        step_status: VARCHAR (Workflow status. Practical values: TICKET_ASSIGNED, IN_PROGRESS, VERIFIED, CLOSED_FOR_VERIFICATION. See TICKET DASHBOARD rule for how each maps to a dashboard bucket — VERIFIED means "resolved", NOT "verified/closed".)
        discard_ticket: VARCHAR/INT (1 or '1' means this ticket is DISCARDED. A discarded ticket is EXCLUDED from all other status buckets — always check this FIRST, before step_status.)
        sub_category: TEXT (JSON array string of sub-category tags for this ticket, e.g. '["MURDER", "PROTEST"]' — same JSON-array convention as topic.sub_category / analyzed_data.sub_category. See CATEGORY COUNTING rule 11a for counting, and the TICKET DASHBOARD rule for how a ticket's single HIGH/MEDIUM/LOW priority is derived from it.)
        broad_category: VARCHAR (Broad category of this ticket)
        complaint_assigned_to_district: VARCHAR (District(s) this ticket is assigned to — may be a comma-separated list; ALWAYS take only the FIRST element via TRIM(SUBSTRING_INDEX(complaint_assigned_to_district, ',', 1)), same convention as topic.primary_districts. This is the canonical district column for the Ticket Dashboard — do NOT use the plain `district` or `complaint_assigned_officer` columns for this, their semantics are inconsistent/legacy.)
        date_of_assignee: VARCHAR (Ticket assignment timestamp STORED AS TEXT in 'DD/MM/YYYY HH:mm:ss' format, NOT a native DATE/DATETIME column. NEVER compare it directly to a date string — ALWAYS wrap it: STR_TO_DATE(date_of_assignee, '%d/%m/%Y %H:%i:%s'). See TICKET DASHBOARD rule for the exact date-range pattern.)
        usage_rules:
            - Use this table for ALL ticket-related queries.
            - Never derive ticket status from topic or analyzed_data tables.
            - Status mapping must follow the Ticket Dashboard rules.
            - Always evaluate discard_ticket before step_status.
            - Use complaint_assigned_to_district as the district source.
            - For Zone/Range/Commissionerate/Thana analysis, join with thana_matrix using:
            TRIM(SUBSTRING_INDEX(complaint_assigned_to_district, ',', 1)) = thana_matrix.district
            - Always convert date_of_assignee using STR_TO_DATE() before applying date filters.

        use_cases:
            - Total ticket count
            - Status-wise ticket counts
            - District-wise ticket counts
            - Zone-wise ticket counts
            - Range-wise ticket counts
            - Commissionerate-wise ticket counts
            - Broad Category-wise ticket analysis
            - Sub Category-wise ticket analysis
            - Ticket assignment trends
            - Ticket dashboard metrics


    - name: thana_matrix
      alias: tm
      purpose: Maps districts to their corresponding Zone, Range, Commissionerate, and
        Thana (Police Station). This is the authoritative lookup table for all
        geographical hierarchy queries.
      columns:
        id: INT (Primary Key)
        district: VARCHAR (Join key — match against ticket_raised_table's district, see TICKET DASHBOARD rule)
        dist_range: VARCHAR (Range name)
        commissionarate: VARCHAR (Commissionerate name)
        zone: VARCHAR (Zone name)
        thana: VARCHAR (Police station name)
        usage_rules:
            - Use this table whenever a query involves Zone, Range, Commissionerate, or Thana.
            - Join on `ticket_raised_table.district = thana_matrix.district`.
            - `ticket_raised_table` does NOT contain Zone, Range, Commissionerate, or Thana fields.
            - Any Zone-wise, Range-wise, Commissionerate-wise, or Thana-wise ticket analysis MUST use this table.
            - Use this table to identify which districts belong to a given Zone, Range, or Commissionerate.
            - Do NOT use this table for ticket content, categories, topics, posts, or complaint details.

        examples:
            - "Show Zone-wise ticket count."
            - "How many tickets came from Range X?"
            - "Which districts belong to Zone Y?"

    # ============================================================
    # 5 tables from the custom-template reskin schema audit . All join to
    # topic.unique_topic_id (directly or one hop) and are real/populated.
    # 3 further tables surfaced by that audit — viral_detection_history,
    # notification, user — are deliberately NOT added here: none of them
    # has any column tying a row to a specific unique_topic_id (batch/
    # account-level data, not per-topic), so they can't answer a per-topic
    # question and would mislead the table selector if listed as usable.
    # ============================================================
    - name: viral_alerts
      alias: va
      purpose: Logs every individual viral-detection alert MATRIX has raised for a topic — one row per alert, so a fast-escalating topic has many rows here over time.
      columns:
        id: INT (Primary Key)
        unique_topic_id: VARCHAR (Links the alert to its topic — many alerts per topic, not unique)
        type: VARCHAR (Alert type)
        topic_title: VARCHAR (Denormalized copy of the topic's title at alert time)
        alert_level: VARCHAR (e.g. LOW, MEDIUM, HIGH, CRITICAL)
        viral_score: FLOAT (Computed virality score at the time of this alert)
        posts_5min: INT
        posts_10min: INT
        posts_1hour: INT
        velocity_per_hour: FLOAT
        spike_multiplier: FLOAT
        accel_5min: FLOAT
        platforms_count: INT (Number of distinct platforms the topic was seen on at alert time)
        primary_district: VARCHAR
        engagement_total: BIGINT
        body: TEXT (Alert message body)
        metadata: JSON
        telegram_sent: BOOLEAN (Whether this alert was pushed to Telegram)
        telegram_message_id: VARCHAR
        telegram_sent_at: TIMESTAMP
        created_at: TIMESTAMP
        updated_at: TIMESTAMP
      use_case: Use when the user asks about alert history for a topic — how many alerts fired, alert levels over time, which district/platform an alert flagged, or whether/when a Telegram alert went out. Join on unique_topic_id.

    - name: viral_alert_performance
      alias: vap
      purpose: One summary row per topic (unique_topic_id is UNIQUE here, unlike viral_alerts) capturing how the alerting pipeline performed for that topic end-to-end — first alert, peak alert, and whether it was truly viral.
      columns:
        id: INT (Primary Key)
        unique_topic_id: VARCHAR (Unique — exactly one row per topic)
        first_alert_level: VARCHAR
        first_alert_time: TIMESTAMP
        first_alert_posts: INT
        peak_alert_level: VARCHAR
        peak_alert_time: TIMESTAMP
        peak_posts: INT
        time_to_peak_minutes: INT
        total_alerts_sent: INT
        final_post_count: INT
        was_truly_viral: BOOLEAN (Post-hoc verdict on whether this topic actually went viral, not just alerted)
        created_at: TIMESTAMP
        updated_at: TIMESTAMP
      use_case: Use when the user asks for a single per-topic summary of alerting performance — how fast it escalated, whether it peaked, whether it was confirmed truly viral. Join on unique_topic_id; expect at most one row.

    - name: topic_velocity_snapshots
      alias: tvs
      purpose: Time-series snapshots of a topic's posting velocity/acceleration/viral score, taken repeatedly as the topic develops — many rows per topic, ordered by snapshot_time.
      columns:
        id: INT (Primary Key)
        unique_topic_id: VARCHAR (Links snapshot to its topic — many snapshots per topic)
        topic_title: VARCHAR (Denormalized copy of the topic's title)
        snapshot_time: TIMESTAMP
        posts_5min: INT
        posts_10min: INT
        posts_15min: INT
        posts_30min: INT
        posts_1hour: INT
        accel_5min: FLOAT
        accel_10min: FLOAT
        velocity_per_hour: FLOAT
        spike_multiplier: FLOAT
        viral_score: FLOAT
        platforms_count: INT
        engagement_total: BIGINT
        created_at: TIMESTAMP
      use_case: Use when the user asks how a topic's velocity/spread changed over time — a velocity or virality trend line, or the topic's state at a specific point in time. Join on unique_topic_id, order by snapshot_time.

    - name: news_paper_cutting
      alias: npc
      purpose: Scanned/uploaded newspaper coverage of a topic — one row per physical newspaper cutting logged against that topic.
      columns:
        id: INT (Primary Key)
        file_path: VARCHAR (Path to the scanned cutting image/file)
        unique_topic_id: VARCHAR (Links the cutting to its topic — directly)
        news_paper_name: VARCHAR
        district: VARCHAR
        eidition_name: VARCHAR (Edition name — column name as stored, note the spelling)
        eidition_city: VARCHAR (Edition city — column name as stored, note the spelling)
        published_date: DATE
        published_by: VARCHAR
        remarks: TEXT
        analysis_status: VARCHAR
        created_at: TIMESTAMP
      use_case: Use when the user asks about print/newspaper coverage of a topic — which papers covered it, when, in which district/edition. Join on unique_topic_id.

    - name: sentiment_entities
      alias: se
      purpose: Named entities (people, places, organizations, etc.) extracted from a post's analysis, with the stance/sentiment expressed toward each entity individually — finer-grained than analyzed_data's single overall sentiment_label.
      columns:
        id: INT (Primary Key)
        analyzed_data_id: INT (No direct unique_topic_id column — join to analyzed_data first: analyzed_data_id -> analyzed_data.id -> analyzed_data.unique_topic_id)
        entity_name: VARCHAR
        entity_type: VARCHAR (e.g. PERSON, ORGANIZATION, LOCATION)
        stance: VARCHAR (Stance expressed toward this specific entity in the post)
        confidence: FLOAT
        reasoning: TEXT (Why the model assigned this stance)
        source: VARCHAR
        created_at: TIMESTAMP
        updated_at: TIMESTAMP
      use_case: Use when the user asks which specific people/places/organizations were mentioned in a topic's posts and how they were portrayed (stance), not just the post's overall sentiment. Requires the one-hop join through analyzed_data — never filter this table by unique_topic_id directly, it has no such column.

relationships:
  content_join_key: unique_topic_id (topic.unique_topic_id = analyzed_data.unique_topic_id)
    topic_primary_district_rule: >
    topic.primary_districts is a JSON array containing multiple districts.
    The FIRST element is always the primary district of the topic.
    Never filter topics using:
    topic.primary_districts LIKE '%District%'
    Always extract the first JSON element when performing district-based topic queries:
    JSON_UNQUOTE(JSON_EXTRACT(topic.primary_districts, '$[0]'))
    Example:
    primary_districts = ["Basti", "Gorakhpur", "Lucknow"]
    Primary district = Basti
    The topic must NOT be counted under Gorakhpur or Lucknow because they are
    secondary associated districts only.
  post_hub: >
    post_bank.id is the CENTRAL CONTENT KEY. It is referenced as post_bank_id by:
    post_user_interactions, post_user_engagement, retweet, reply, fb_comments, insta_comments, engagement_metric.
    analyzed_data is a denormalized COPY of post_bank data (columns prefixed post_bank_*) and has NO post_bank_id
    foreign key — never try to JOIN an engagement table directly onto analyzed_data.
  actor_hub: >
    post_users.id is the CENTRAL ACTOR KEY. It is referenced as post_user_id by post_user_interactions,
    post_user_engagement, retweet, reply; and as user_id/follower_id by profile_network.
  monitoring_actor_hub: >
    user_monitoring.id is referenced as source_user_id/target_user_id by user_connections (the typed,
    weighted actor-to-actor relationship graph).
  taxonomy_joins: >
    keywords.broad_category_id -> broad_category.id ; keywords.sub_category_id -> sub_category.id ;
    sub_category.broad_category_id -> broad_category.id
  alias_convention: >
    t=topic, a=analyzed_data, pb=post_bank, pu=post_users, um=user_monitoring,
    pn=profile_network, uc=user_connections, pui=post_user_interactions, pue=post_user_engagement,
    rt=retweet, rp=reply, fc=fb_comments, ic=insta_comments, em=engagement_metric,
    bc=broad_category, sc=sub_category, kw=keywords, ht=hashtags, chm=category_handle_master, mp=monitor_profiles,
    dir=district_internal_report, pt=post_transfer, trt=ticket_raised_table, tm=thana_matrix,
    va=viral_alerts, vap=viral_alert_performance, tvs=topic_velocity_snapshots, npc=news_paper_cutting, se=sentiment_entities
  pending_reports_join: >
    A topic is a PENDING internal report when topic.request_internal_report = '1' AND
    NOT EXISTS (SELECT 1 FROM district_internal_report dir WHERE dir.unique_topic_id = topic.unique_topic_id).
    district_internal_report has NO topic_id foreign key column — it only joins via unique_topic_id.
  monitor_profile_tagging_join: >
    monitor_profiles has NO foreign key into analyzed_data. A post is considered TAGGED under a
    monitor_profiles.category when analyzed_data.mention_ids_extracted CONTAINS that profile's
    user_name (leading '@' stripped, case-insensitive). This is an intentional LIKE-based substring
    join, NOT a defect and NOT expected to be an equality/foreign-key join like the other
    relationships above:
    JOIN monitor_profiles mp ON LOWER(a.mention_ids_extracted)
      LIKE CONCAT('%', LOWER(TRIM(LEADING '@' FROM mp.user_name)), '%')
  ticket_zone_range_join: >
    ticket_raised_table has NO zone/range column of its own. To answer a ZONE-wise or RANGE-wise
    ticket question, join its district to thana_matrix:
    JOIN thana_matrix tm ON LOWER(tm.district) =
      LOWER(TRIM(SUBSTRING_INDEX(trt.complaint_assigned_to_district, ',', 1)))
    Then GROUP BY tm.zone (zone-wise) or tm.dist_range (range-wise), not by any ticket_raised_table
    column directly.
  ticket_priority_join: >
    A ticket's priority is NOT a column on ticket_raised_table — it is the priority of the WINNING
    sub-category among the (possibly several) tags in ticket_raised_table.sub_category, where the
    winner is whichever matched sub_category has the LOWEST sub_category.classify_sub_priority.
    Never treat every tagged sub-category as equally contributing a priority; use one derived value
    per ticket:
    (SELECT sc.priority FROM JSON_TABLE(trt.sub_category, '$[*]' COLUMNS (cat VARCHAR(100) PATH '$')) jt
     JOIN sub_category sc ON sc.sub_category = jt.cat
     ORDER BY sc.classify_sub_priority ASC LIMIT 1) AS ticket_priority
  sentiment_entities_join: >
    sentiment_entities has NO unique_topic_id column of its own — it is one hop from topic via
    analyzed_data: JOIN analyzed_data a ON se.analyzed_data_id = a.id, then filter/join on
    a.unique_topic_id. Never filter sentiment_entities by unique_topic_id directly.
  no_topic_join_tables: >
    viral_detection_history, notification, and user are real, populated tables but have NO column
    tying a row to a specific unique_topic_id (viral_detection_history is batch/detection-run-level;
    notification's object_id is untyped and its topic semantics are unconfirmed; user is the officer/
    account table, not topic content). Do not attempt to answer a per-topic question from these three
    tables — there is no join path, not a missing one you can construct.
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
from services.dynamic_report_service import (
    get_component_catalog,
    get_trending_component_catalog,
    llm_decide_components,
    generate_claude_picker_card,
    build_report,
    ReportValidationError,
    MAX_TOPICS_PER_REPORT,
    V1_TRENDING_COMPONENT_IDS,
    resolve_report_scope,
    _is_freeform_report_request,
    _extract_report_brief,
    build_freeform_report,
    build_adhoc_report_preview,
    confirm_adhoc_report,
    match_design_brief_to_template,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

today = datetime.now().strftime("%Y-%m-%d")
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
now_iso = datetime.now().isoformat()

# Override config from environment if available
QDRANT_HOST = os.environ.get("QDRANT_HOST", QDRANT_HOST_DEFAULT)
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", str(QDRANT_PORT_DEFAULT)))
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")

# All external-endpoint / "MCP tool" configuration, HTTP session, payload
# validation, and result-shaping logic now lives in mcp_services.py —
# this file keeps only the LLM-calling side of the pipeline. See
# check_and_run_endpoint_routes_node / endpoint_write_executor_node /
# endpoint_multi_run_executor_node below for how the two files cooperate.
import mcp_services

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
             output: str = None, retry_count=None):
    """Lightweight local trace log — prints and keeps in-memory for server."""
    print(f"[trace] {node_name}: {output}")
    _TRACE_LOG.append({
        "node": node_name,
        "query": user_query,
        "prompt": prompt,
        "output": output,
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
    route: str                          # "database" or "pdf_chat"
    pdf_uploaded: bool
    pdf_filenames: List[str]
    pdf_results: List[Any]
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
    resolved_topic_reference: str       # confirmed unique_topic_id if user says "this post/topic"
    post_metadata: dict                 # mapping of post_id to {url, source} for the final answer
    has_table_topic: bool               # output of check_query_manager — routes to keyword steps or straight to router
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
    answer_feedback: str                # feedback from answer_checker to add missing details
    answer_retry_count: int             # counter for answer_checker loop
    neo4j_graph_context: str            # structured graph answer from neo4j_search_node
    neo4j_search_done: bool             # flag to avoid re-running neo4j_search in same turn
    fallback_retry_count: int           # counter for Qdrant/Neo4j fallback loops (max 3)
    fallback_feedback: str              # feedback from fallbackchecker when a graph answer is wrong
    fallback_route: str                 # "keyword_search" or "graph_query" picked by fallback_decider
    fallback_exhausted: bool            # True when all 3 fallback retries failed → routes to query_rewriter
    pending_keyword_confirmation: dict  # {"term","resolved_entity","resolved_query","source"} — set when check_query_manager's live classification (or query_rewriter's own grounded clarification) is waiting on a yes/no; checked at the top of query_rewriter_node on the NEXT turn
    report_id: str                      # generated report identifier, set by dynamic_report_maker_node (offer) and re-minted by report_builder_node (build)
    report_pdf_url: str                 # download link for the generated PDF, set by report_builder_node
    report_selection: dict              # {"report_id","topic_id","topic_title","components","custom_instructions"} — supplied directly by the frontend on the SAME turn it confirms a report (see server.py ChatRequest.report_selection); its presence is what routes a turn straight to report_builder_node via the graph's conditional entry point. Never relies on cross-turn State persistence (see the note in query_rewriter_node).
    # NOTE: the free-form (path 4) report request is detected and fully built inline inside llm_validator_node (see "Path 4: Free-Form Prompt-Driven Report Builder" below), where resolved_topic_reference/last_topic_ids from THIS turn's own SQL grounding are already available — that's why
    # it isn't a graph-entry-point flag like report_selection: detection has to happen after this turn's SQL pipeline has run, not before it. An earlier revision also had a separate freeform_report_builder_node reached via a freeform_report_request entry-point flag, but nothing  ever set that flag (ChatRequest has no such field), so that path was dead code and has been removed — llm_validator_node's inline handling is the single, real implementation.
    endpoint_route_matched: bool         # True if check_and_run_endpoint_routes found a usable endpoint
    endpoint_routes_checked: bool        # Per-turn guard preventing duplicate endpoint discovery/pickers
    endpoint_route_name: str             # matched endpoint URL/key from external_endpoints.json
    endpoint_route_result: dict          # raw execution result (status_code + body)
    pending_endpoint_write: dict         # offer payload shown to the user when check_and_run_endpoint_routes finds a write-endpoint match; frontend echoes it back as endpoint_write_confirmation to actually execute (same pattern as report_selection/report_builder_node)
    endpoint_write_confirmation: dict    # supplied by the frontend on the SAME turn it confirms a pending write — its presence routes straight to endpoint_write_executor_node via the graph's conditional entry point, mirroring report_selection
    pending_endpoint_selection: dict    # checkbox-picker payload offered when Stage 2 finds one or more relevant READ endpoints; frontend echoes the user's picks back as endpoint_multi_selection (same pattern as pending_endpoint_write)
    endpoint_multi_selection: list      # supplied by the frontend on the SAME turn it confirms a picked set — its presence routes straight to endpoint_multi_run_executor_node via the graph's conditional entry point
    endpoint_multi_selection_query: str # the real standalone question the picker was originally offered for (echoed back from pending_endpoint_selection.query) — state["query"] on this turn is just the "Run N selected endpoints" button label, not usable for summarization
    is_slash_report: bool               # True if query was triggered via /report or /brief slash command



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
# run query_manager/router_node/check_query_manager yet at this point, so it
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

    # ── Slash Command Handling (Exclusively for /report) ──────────────────────
    trimmed = (query or "").strip()
    if trimmed.lower().startswith("/report"):
        parts = trimmed.split(None, 1)
        sub_query = parts[1].strip() if len(parts) > 1 else ""
        prompt_content = sub_query if sub_query else "Generate a comprehensive trending intelligence report from the verified database."
        add_trace("query_rewriter", user_query=query, output="Slash command /report triggered for report generation")
        return {
            "corrected_query": prompt_content,
            "rewrite_context": "Slash command /report requested: direct report generation pipeline.",
            "needs_clarification": False,
            "explain_request": False,
            "is_slash_report": True,
        }

    # ── Fallback exhaustion shortcut ──────────────────────────────────────
    if state.get("fallback_exhausted"):
        graph_context = state.get("content_index_hint", "")
        # Build a short preview of what we actually found
        preview_lines = [line for line in graph_context.splitlines() if line.strip()][:5]
        preview = "\n".join(preview_lines)
        clarification_msg = (
            f"मैंने आपके प्रश्न के लिए कुछ मिलते-जुलते डेटा ढूंढे हैं, लेकिन मुझे सटीक जानकारी चाहिए:\n\n"
            f"**मिली-जुली जानकारी:**\n{preview}\n\n"
            f"क्या आप बता सकते हैं कि आप किस विशेष व्यक्ति, घटना या जानकारी के बारे में पूछ रहे हैं?"
        )
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
    # NOTE: there is deliberately no "pending_report_selection" cross-turn
    # shortcut here. server.py's chat_endpoint builds a brand-new State dict
    # from scratch on every /api/chat call — it never re-supplies a State
    # field from the previous turn's result (this is also why the
    # pending_keyword_confirmation shortcut immediately below only actually
    # works through ollamaagent2.py's standalone CLI REPL, not the deployed
    # web app). The report-confirmation flow avoids depending on that
    # entirely: the frontend echoes the offered report/topic/components back
    # as `report_selection` in the SAME request that confirms it (see
    # ChatRequest.report_selection in server.py and the graph's conditional
    # entry point below), so there's nothing to "remember" across turns.
    # See report_builder_node / _graph_entry_decision further down.

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
                "answer": f"No problem — could you say exactly what \"{pending['term']}\" refers to?",
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
  "resolved_post_context": true or false
}}
"""

    raw = await call_llm(prompt)
    corrected_query = query
    rewrite_context = ""
    needs_clarification = False
    clarification_message = ""
    explain_request = False
    explain_answer = ""
    
    try:
        parsed = json.loads(clean_json_string(raw))
        corrected_query = str(parsed.get("corrected_query") or "").strip() or query
        if parsed.get("related"):
            rewrite_context = str(parsed.get("notes") or "").strip()
        
        if parsed.get("needs_clarification"):
            needs_clarification = True
            clarification_message = str(parsed.get("clarification_message") or "Could you please clarify what you mean?")
            
        if parsed.get("explain_request"):
            explain_request = True
            explain_prompt = f"The user asked for an explanation: '{query}'. Based on the PAST LOG POINTS:\n{related_history}\nAnd PREVIOUS SQL:\n{last_sql_context}\nWrite a short, friendly explanation of how you arrived at your answer."
            explain_answer = (await call_llm(explain_prompt)).strip()
            
    except Exception as e:
        print(f"⚠️ query_rewriter_node: could not parse JSON ({e}) — falling back")

    add_trace("query_rewriter", user_query=query, prompt=prompt,
             output=f"corrected_query={corrected_query}; rewrite_context={rewrite_context or '(none)'}; explain={explain_request}")
             
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
        "resolved_topic_reference": resolved_topic_id
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

    # For slash command report generation, preserve user's full brief without LLM summarization
    if state.get("is_slash_report"):
        add_trace("query_manager", user_query=corrected_query, output=f"Slash report mode: preserving query '{corrected_query[:100]}...'")
        return {"query": corrected_query, "is_slash_report": True}

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


### 3. Preserve previous constraints

Carry forward all previous filters unless the user changes them:

- district
- date range
- category
- incident type
- topic
- platform
- sorting requirement


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

async def _check_query_manager_grounded_classification(term: str) -> dict:
    """Independent copy of the "7 questions -> DuckDuckGo" pattern, used ONLY by
    check_query_manager_node's live classification step below. Not shared code
    with query_rewriter_node's own grounded-clarification instance — the two
    fire at different, non-overlapping points in the pipeline (this one only
    once a standalone_query already exists and a specific term in it is
    unresolved), so they're kept as deliberately separate call sites.

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
    """After router_node (for database path): validates if the standalone query correctly captures
    the user's intent based on the conversation history. If not, sets up a retry back to
    query_rewriter. If correct, decides if it needs keyword extraction."""
    if state.get("is_slash_report"):
        add_trace("check_query_manager", output="Slash report intent approved directly")
        return {
            "query_manager_approved": True,
            "has_table_topic": False,
            "query_manager_retry_count": 0,
        }

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
    "has_table_topic": true or false
}}
"""

    raw = await call_llm(prompt)
    is_correct = True
    reason = ""
    has_table_topic = True

    try:
        parsed = json.loads(clean_json_string(raw))
        is_correct = bool(parsed.get("is_correct", True))
        reason = str(parsed.get("reason", ""))
        has_table_topic = bool(parsed.get("has_table_topic", True))
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
    candidate_term = _find_unresolved_short_form(standalone_query, set(state.get("duck_resolved_terms", [])))
    if candidate_term:
        recycle_rows = await asyncio.to_thread(_fetch_recycle_search_entries)
        already_known = any(
            candidate_term.lower() in str(row.get("query_tag", "")).lower()
            for row in recycle_rows
        )
        if not already_known:
            grounding = await _check_query_manager_grounded_classification(candidate_term)

            if grounding["candidate_entity"]:
                candidate = grounding["candidate_entity"]
                add_trace("check_query_manager", user_query=original_query,
                         output=f"live classification: '{candidate_term}' -> candidate '{candidate}'")
                return {
                    "is_query_correct": True,
                    "has_table_topic": has_table_topic,
                    "needs_clarification": True,
                    "answer": grounding["grounded_message"] or f'Are you asking about "{candidate}"? (yes/no)',
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
              output=f"Correct={is_correct}; has_table_topic={has_table_topic}")
    return {
        "is_query_correct": True,
        "has_table_topic": has_table_topic,
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
# ROUTER — database vs pdf_chat
# =========================

async def router_node(state: State) -> dict:
    """After query_manager_node: decides whether this turn needs the police
    social-media database or the active uploaded PDF."""
    if state.get("is_slash_report"):
        add_trace("router", output="database route selected for slash report generation")
        return {"route": "database"}

    history = format_history(state.get("messages", []))

    if state.get("pdf_uploaded"):
        pdf_names = ", ".join(state.get("pdf_filenames", [])) or "an uploaded document"
        pdf_status = (
            f"A PDF IS CURRENTLY ACTIVE this session: {pdf_names}. Treat "
            f"topical follow-ups and pronoun references as being about the PDF."
        )
    else:
        pdf_status = "No PDF has been uploaded this session."

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    prompt = f"""Current Date : {today}
Yesterday : {yesterday}
Current Time : {now_iso}

You are an intelligent routing agent.

Your task is to analyze the user's latest message IN THE CONTEXT of the recent
conversation and return exactly one route.

PDF STATUS:
{pdf_status}

Available routes:

### 1. database

Choose `database` ONLY if the user's query clearly needs information stored in the
police social-media database, including:

* Social media posts or activities (Twitter/X, Facebook, Instagram, WhatsApp, Telegram, News, etc.)
* Authors, users, accounts, or platforms
* Counts, statistics, analytics, trends, comparisons, or timelines OF SOCIAL-MEDIA / POLICE data
* News, incidents, crimes, accidents, protests, legal cases, FIRs, court cases, district (UP) updates, or rumors stored in the database
* Viral / trending topics, district-wise activity
* Dashboard-style questions: high-priority categories, category case counts,
  rankings or comparisons of crime categories (murder vs protest, kidnapping vs
  loot, police misconduct vs corruption...), "which categories have more than N
  cases", "top crime concerns", "what should the DGP focus on", "briefing note",
  "urgent intervention", "law-and-order concerns", "public safety concerns",
  "high-priority alerts". The user's dashboard is BUILT FROM this database, so
  every question about it is a `database` question.
* Follow-up questions about previous DATABASE results

### 2. pdf_chat

Choose `pdf_chat` for every other request, including:

* Questions about uploaded PDF documents (summarize, search, "this PDF", "the document", specific pages)
* ANY follow-up that continues the subject of the active PDF (see PDF STATUS) — even
  if it uses date/time words like "when", "how long", "amount", or pronouns like "this"/"it"
* General conversation, general knowledge, coding, writing, math, translation
* Any request that does not clearly require the police social-media database

DECISIVE RULES (apply in order):

1. If a PDF is active (see PDF STATUS) and the query does NOT clearly mention the
   social-media/police-database domain (posts, platforms, districts, viral topics,
   authors, counts of posts, etc.), choose `pdf_chat`. A medical/technical/general
   term that matches the document's subject (e.g. "tuberculosis", "bacilli",
   "infection") is a PDF follow-up, NOT a database incident — choose `pdf_chat`.
2. A question being about a date/time ("when was this...", "how long") does NOT by
   itself mean `database`. Route by TOPIC, using the conversation + PDF STATUS.
3. Only choose `database` when the query is genuinely about the social-media/police data.
4. If NO PDF is active, any question about crime categories, case counts,
   priorities, rankings, comparisons of crime types, the dashboard, briefings,
   alerts, or trends MUST be `database` — NEVER answer these from general
   knowledge. Only clearly unrelated requests (coding, math, translation, small
   talk, world facts) are `pdf_chat` when no PDF is active.

Output format:
* Return exactly one of: `database` or `pdf_chat`.
* Do not explain. Do not return JSON, markdown, or extra text.

----------------------------------------

Recent Conversation (for context):
{history}

Latest User Query:
{state["query"]}
----------------------------------------
"""

    raw_decision = (await call_llm(prompt)).strip().lower()
    match = re.search(r"\b(database|pdf_chat)\b", raw_decision)
    decision = match.group(1) if match else "pdf_chat"
    print(f"Router Output: {state['query']} -> {decision}")

    # Shared database-domain signal words — used by BOTH backstops below.
    # A mention of "post"/"tweet"/"url"/"account" etc. is a database signal
    # regardless of whether a PDF happens to be active this session; keeping
    # one shared list means a query like "give me this post url" can't fall
    # through just because it lacks a crime/dashboard-specific word.
    _DB_DOMAIN_SIGNALS = [
        "post", "tweet", "twitter", "facebook", "insta", "whatsapp", "telegram",
        "news", "viral", "trend", "district", "platform", "account", "author",
        "handle", "retweet", "reply", "comment", "follower", "following",
        "sentiment", "hashtag", "police", "fir", "thana", "count", "how many",
        "incident", "protest", "accident", "crime", "rumor", "topic",
        "url", "link", "username", "user id", "handle", "profile",
        "categor", "case", "dashboard", "priorit", "murder", "kidnap", "loot",
        "riot", "communal", "briefing", "alert", "dgp", "law and order",
        "intervention", "safety concern", "misconduct", "corruption",
    ]

    # Deterministic backstop: PDF active but no DB signal -> pdf_chat
    if state.get("pdf_uploaded") and decision == "database":
        q = state["query"].lower()
        if not any(s in q for s in _DB_DOMAIN_SIGNALS):
            print("↩️ Router override: PDF active, no DB signal → pdf_chat")
            decision = "pdf_chat"

    # Deterministic backstop: No PDF, but a DB-domain signal -> database
    if not state.get("pdf_uploaded") and decision == "pdf_chat":
        q = state["query"].lower()
        if any(s in q for s in _DB_DOMAIN_SIGNALS):
            print("↩️ Router override: no PDF, DB-domain signal → database")
            decision = "database"

    add_trace("router", user_query=state["query"], prompt=prompt,
             output=f"Route: {decision}")
    return {
        "route": decision,
        "retry_count": 0,
        "content_index_hint": "",
        "content_index_retry_count": 0,
    }

async def check_and_run_endpoint_routes_node(state: State) -> dict:
    """Third step after query_rewriter → query_manager, BEFORE router_node.
    Two-stage check against external_endpoints.json:
      Stage 1 — loosely gather candidate endpoints from EVERY batch of
                ENDPOINT_ROUTE_BATCH_SIZE (default 30) endpoints.
      Stage 2 — strictly validate the merged candidate shortlist and pick
                at most one endpoint, with an explicit is_valid decision
                (no numeric confidence threshold).
    If valid, calls that endpoint directly (Option B — no code-gen, no
    subprocess) and answers, ending the turn here. If not, falls through
    unchanged into router_node's existing database/pdf_chat routing —
    router_node itself is not touched.

    All endpoint discovery/validation/HTTP-calling/result-shaping logic
    lives in mcp_services.py; this node only makes the LLM calls (Stage 1
    candidate gathering, Stage 2 relevancy ranking, and — via
    _execute_and_summarize_reads — the final answer generation) and wires
    the results together."""

    query = state["query"]

    # Endpoint discovery is a per-turn operation. If a previous endpoint
    # attempt already ran in this graph invocation (including a multi-select
    # attempt that later fell back to the normal router), do not offer the
    # same picker again.
    if state.get("endpoint_routes_checked"):
        add_trace("check_and_run_endpoint_routes", user_query=query,
                  output="endpoint discovery already checked this turn; skipping duplicate pass")
        return {"endpoint_route_matched": False, "endpoint_routes_checked": True}

    if not mcp_services.EXTERNAL_ENDPOINTS:
        return {"endpoint_route_matched": False, "endpoint_routes_checked": True}

    # Report requests (e.g. ad-hoc AI HTML/PDF reports or component checklist reports)
    # MUST bypass external endpoint matching so they reach the dedicated report generation pipeline.
    if state.get("is_slash_report") or _is_report_request(query) or _is_freeform_report_request(query):
        add_trace("check_and_run_endpoint_routes", user_query=query,
                  output="report generation intent detected; bypassing endpoint routing to report pipeline")
        return {"endpoint_route_matched": False, "endpoint_routes_checked": True}

    batches = mcp_services.get_endpoint_batches()

    # ── Stage 1: gather candidates from every batch (one LLM call/batch) ──
    async def _gather_one_batch(batch: dict) -> list:
        prompt = mcp_services.build_candidate_gather_prompt(query, batch)
        raw = await call_llm(prompt)
        return mcp_services.parse_candidate_gather_response(raw, batch, query)

    batch_results = await asyncio.gather(*[_gather_one_batch(batch) for batch in batches])
    all_candidates: dict = {}
    for batch_idx, found in enumerate(batch_results):
        for ep in found:
            all_candidates[ep] = mcp_services.EXTERNAL_ENDPOINTS[ep]
        add_trace("check_and_run_endpoint_routes", user_query=query,
                  output=f"batch {batch_idx+1}/{len(batches)} candidates={found}")

    if not all_candidates:
        add_trace("check_and_run_endpoint_routes", user_query=query,
                  output=f"no candidates found across {len(batches)} batch(es)")
        return {"endpoint_route_matched": False, "endpoint_routes_checked": True}

    # ── Stage 2: rank the shortlist (one LLM call), split write vs read ──
    rank_prompt = mcp_services.build_endpoint_rank_prompt(query, all_candidates)
    rank_raw = await call_llm(rank_prompt)
    ranked = mcp_services.parse_endpoint_rank_response(rank_raw, all_candidates)
    matches = ranked.get("matches", [])

    if not matches:
        add_trace("check_and_run_endpoint_routes", user_query=query,
                  output=f"relevancy check rejected candidates {list(all_candidates.keys())} "
                         f"(ambiguity: {ranked.get('ambiguity_considered')})")
        return {"endpoint_route_matched": False, "endpoint_routes_checked": True}

    write_matches, read_matches = mcp_services.split_write_read_matches(matches)

    # Write matches: keep the existing single-confirmation behavior,
    # unchanged — take the top-ranked write match only (mutating calls are
    # deliberately not offered as a bulk checkbox list).
    if write_matches and not read_matches:
        write_id = f"wr_{uuid.uuid4().hex[:10]}"
        endpoint, confirm_payload, answer = mcp_services.build_write_confirmation_card(
            write_matches[0], write_id
        )
        add_trace("check_and_run_endpoint_routes", user_query=query,
                  output=f"offered write confirmation {write_id} for {endpoint} "
                         f"(payload={confirm_payload['payload']})")
        return {
            "endpoint_route_matched": True,
            "endpoint_routes_checked": True,
            "needs_clarification": True,
            "answer": answer,
            "pending_endpoint_write": confirm_payload,
        }

    if not read_matches:
        # Only write matches existed but there was more than one — be
        # conservative and don't guess which mutating call the user meant.
        add_trace("check_and_run_endpoint_routes", user_query=query,
                  output=f"multiple write-only matches, refusing to guess: {[m['endpoint'] for m in write_matches]}")
        return {"endpoint_route_matched": False, "endpoint_routes_checked": True}

    # ── Exactly one genuine read match: nothing for the user to choose
    # between, so run it immediately instead of round-tripping through a
    # confirmation card. Confirmation is only useful when there's an
    # actual decision to make (2+ candidates); write endpoints keep their
    # own always-confirm flow above regardless of count, since those
    # mutate data. ───────────────────────────────────────────────────
    if len(read_matches) == 1:
        selected = [mcp_services.resolve_single_read_match(read_matches[0])]
        result = await _execute_and_summarize_reads(selected, query)
        add_trace("check_and_run_endpoint_routes", user_query=query,
                  output=f"single read match, auto-ran without confirmation: {selected[0]} "
                         f"-> {result.get('endpoint_route_result')}")
        result["endpoint_routes_checked"] = True
        return result

    # ── 2+ read matches: offer the checkbox multi-select instead of
    # forcing a single pick ─────────────────────────────────────────────
    selection_id = f"sel_{uuid.uuid4().hex[:10]}"
    selection_card, answer = mcp_services.build_multi_selection_card(read_matches, query, selection_id)
    add_trace("check_and_run_endpoint_routes", user_query=query,
              output=f"offered {len(selection_card['candidates'])} read-endpoint choice(s) "
                     f"{[c['endpoint'] for c in selection_card['candidates']]} "
                     f"(ambiguity: {ranked.get('ambiguity_considered')})")
    return {
        "endpoint_route_matched": True,
        "needs_clarification": True,
        "answer": answer,
        "pending_endpoint_selection": selection_card,
    }


async def _execute_and_summarize_reads(selected: list, query: str) -> dict:
    """Shared LLM-summarization step for read endpoints — used by BOTH
    check_and_run_endpoint_routes_node (single auto-run match) and
    endpoint_multi_run_executor_node (user-picked checkbox selection), so
    both paths behave identically instead of drifting apart.

    All HTTP calling, envelope-unwrapping, and record aggregation is done
    by mcp_services (no LLM involved); this function only decides which
    summarization prompt to build and makes the one LLM call to phrase
    the final answer."""
    results = await mcp_services.call_read_endpoints(selected)
    succeeded, failed, payloads, non_empty_payloads, empty_source_count = (
        mcp_services.classify_read_results(results)
    )

    # NO DATA / NO RESPONSE → fall back to the normal router_node pipeline
    # instead of ending the turn with a canned "nothing found" answer. This
    # covers BOTH failure modes: every selected call erroring/timing out,
    # and every call succeeding but returning zero matching records. Either
    # way, the external-endpoint attempt didn't produce an answer, so the
    # user's question deserves a real shot at the internal DB/pdf_chat
    # pipeline rather than stopping here. quick_total_count is a pure
    # computation (no LLM call), so this check is cheap and skips the
    # summarizer call entirely in the empty case.
    if mcp_services.quick_total_count(non_empty_payloads) == 0:
        add_trace("_execute_and_summarize_reads", user_query=query,
                  output=f"no data from {len(selected)} selected endpoint(s) "
                         f"({len(succeeded)} succeeded, {len(failed)} failed) — "
                         f"falling back to router_node instead of ending the turn")
        return {
            "endpoint_route_matched": False,
            "endpoint_route_result": results,
        }

    # List-of-record responses get summarized from a CODE-COMPUTED
    # aggregate instead of raw JSON when possible — real counts + real
    # sample titles computed in mcp_services are guaranteed accurate; the
    # LLM only has to phrase them.
    record_aggregate = mcp_services.aggregate_records_for_summary(non_empty_payloads)

    if record_aggregate:
        prompt = mcp_services.build_record_aggregate_prompt(query, record_aggregate, failed, results)
        final_answer = await call_llm(prompt)
        return {
            "endpoint_route_matched": True,
            "endpoint_route_result": results,
            "answer": final_answer.strip(),
        }

    trimmed_payloads, total_item_count, was_truncated = mcp_services.prepare_payload_for_summary(
        non_empty_payloads
    )
    prompt = mcp_services.build_raw_json_summary_prompt(
        query, trimmed_payloads, total_item_count, was_truncated,
        empty_source_count, payloads, failed, results,
    )
    final_answer = await call_llm(prompt)

    return {
        "endpoint_route_matched": True,
        "endpoint_route_result": results,
        "answer": final_answer.strip(),
    }


async def endpoint_write_executor_node(state: State) -> dict:
    """Reached directly via the graph's conditional entry point (see
    _graph_entry_decision), NOT through the normal pipeline — the frontend
    echoes back the exact confirm_payload offered by
    check_and_run_endpoint_routes_node's write-confirmation branch as
    `endpoint_write_confirmation` the instant the user confirms.

    Re-validates the endpoint against the CURRENT mcp_services.EXTERNAL_ENDPOINTS
    / WRITE_ENDPOINT_MARKERS before executing — never trusts the echoed
    endpoint/payload blindly, since it round-tripped through the client.

    The HTTP write call itself is fired by mcp_services.execute_write_endpoint
    (no LLM involved there); this node only validates, calls the LLM to
    phrase the confirmation, and returns the result."""
    conf = state.get("endpoint_write_confirmation") or {}
    endpoint = conf.get("endpoint")
    method = (conf.get("method") or "POST").upper()
    payload = conf.get("payload") or {}

    rejection = mcp_services.validate_write_endpoint(endpoint)
    if rejection:
        add_trace("endpoint_write_executor", output=rejection)
        if "not a currently known endpoint" in rejection:
            return {"answer": "I couldn't confirm that action — it may be out of date. Please ask again."}
        return {"answer": "That action isn't recognized as confirmable — please ask again."}

    result = mcp_services.execute_write_endpoint(endpoint, method, payload)

    final_answer = await call_llm(mcp_services.build_write_result_prompt(endpoint, result))

    add_trace("endpoint_write_executor",
              output=f"executed write {endpoint} (payload={payload}) -> {result}")

    return {
        "endpoint_route_matched": True,
        "endpoint_route_name": endpoint,
        "endpoint_route_result": result,
        "answer": final_answer.strip(),
    }


async def endpoint_multi_run_executor_node(state: State) -> dict:
    """Reached directly via the graph's conditional entry point — the
    frontend echoes back the list of candidates the user checked as
    `endpoint_multi_selection`: [{"endpoint","method","payload"}, ...], plus
    the original question as `endpoint_multi_selection_query` (state["query"]
    on this turn is just the "Run N selected endpoints" button label, not
    the actual question — see buildEndpointMultiSelectionCard in script.js).
    Delegates to _execute_and_summarize_reads, which (via mcp_services)
    re-validates every item and never trusts the echoed endpoint/payload
    blindly.

    Falls back to state["query"] if endpoint_multi_selection_query wasn't
    sent (e.g. an older frontend build that hasn't picked up the echo yet),
    so this degrades to the previous (broken but non-crashing) behavior
    instead of raising.

    IMPORTANT: always returns "query": real_query. _execute_and_summarize_reads
    may signal endpoint_route_matched=False (no data found from any selected
    endpoint) — the graph's conditional edge then routes this turn on to
    router_node/the normal DB+pdf pipeline instead of ending here, exactly
    like check_and_run_endpoint_routes_node's existing no-match fallback.
    That downstream pipeline reads state["query"], so it must be the real
    question, never the button-label text this node was entered with."""
    selected = state.get("endpoint_multi_selection") or []
    real_query = state.get("endpoint_multi_selection_query") or state.get("query", "")
    result = await _execute_and_summarize_reads(selected, real_query)
    add_trace("endpoint_multi_run_executor", user_query=real_query,
              output=f"ran {len(selected)} selected endpoint(s) -> {result.get('endpoint_route_result')}")
    # This invocation already represents a completed endpoint discovery
    # decision from the previous turn's picker. If execution is empty and
    # the graph falls back to router -> query_manager, do not rediscover the
    # same endpoint set and show the same picker again.
    result["endpoint_routes_checked"] = True
    result["query"] = real_query
    return result

# =========================
# PDF CHAT — pdf_search -> pdf_answer
# =========================

def search_pdf(query: str, pdf_filenames: list) -> list:
    """Stub for the real PDF vector-search service. Returns no hits until
    the PDF ingestion/embedding pipeline is wired up."""
    return []


async def pdf_search_node(state: State) -> dict:
    """Searches the uploaded PDF(s) for relevant chunks."""
    hits = await asyncio.to_thread(search_pdf, state["query"],
                                   state.get("pdf_filenames", []))
    add_trace("pdf_search", user_query=state["query"],
             output=f"{len(hits)} chunks retrieved")
    return {"pdf_results": hits}


async def pdf_answer_node(state: State) -> dict:
    """Writes the final reply from PDF passages or general knowledge."""
    hits = state.get("pdf_results", [])
    if hits:
        context = "\n\n---\n\n".join(
            f"[{h['filename']} — page {h['page']}]\n{h['text']}" for h in hits
        )
    else:
        context = "No document excerpts were retrieved."

    history = format_history(state.get("messages", []))
    expert_name = state.get("expert_name", "")
    persona = (f'You are "{expert_name}", a specialized AI expert.'
               if expert_name else "You are a helpful, professional assistant.")

    prompt = f"""{persona}

Answer the user's question using BOTH the DOCUMENT EXCERPTS and your own knowledge.
- If about the uploaded document, treat excerpts as primary source.
- If excerpts don't cover it, answer from your own knowledge.
- Never refuse — always provide a useful answer.

DOCUMENT EXCERPTS:
{context}

CONVERSATION HISTORY:
{history}

USER QUESTION:
{state["query"]}
"""

    answer = await call_llm(prompt)
    add_trace("pdf_answer", user_query=state["query"], output=answer[:20000])
    return {"answer": answer}


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


# Multi-word phrases that don't reduce to a single fuzzy-checkable word.
_REPORT_EXACT_PHRASES = ["overview of"]
# Latin words checked with typo tolerance (see _is_report_request) — a plain
# substring check on "report" was silently missing real user typos like
# "repot"/"reprot", causing the whole report flow to never trigger.
_REPORT_FUZZY_WORDS = ["report", "reports", "summary", "briefing"]
# Short and/or non-Latin-script terms — fuzzy matching isn't reliable at
# this length/script, so these stay exact substring checks.
_REPORT_SUBSTRINGS = ["pdf", "रिपोर्ट", "पीडीएफ", "समरी", "विवरण"]


def _is_report_request(text: str) -> bool:
    """True if `text` is asking for a report/summary/pdf/briefing. Tolerant
    of common typos on the Latin trigger words (edit-distance-ish via
    difflib, not just exact substring) since real users mistype "report" as
    "repot"/"reprot" fairly often, and an exact match silently drops the
    whole report feature for them."""
    text_lower = (text or "").lower()
    if any(p in text_lower for p in _REPORT_EXACT_PHRASES + _REPORT_SUBSTRINGS):
        return True
    for w in re.findall(r"[a-z]+", text_lower):
        if len(w) < 4:
            continue
        for target in _REPORT_FUZZY_WORDS:
            if difflib.SequenceMatcher(None, w, target).ratio() >= 0.8:
                return True
    return False


def _lookup_topic_id_by_title(title: str) -> str:
    """Resolves unique_topic_id from a known topic_title via a direct point
    lookup. Used by llm_validator_node's report-picker step when a query
    (e.g. "trending topics today") returned rows with a title but no id
    column, so there's a name to scope a report to but nothing to key SQL
    on yet. Same mysql.connector connection pattern as execute_sql()."""
    if not title or title == "Incident & Topic Intelligence Analysis":
        return ""
    conn = mysql.connector.connect(
        host=MYSQL_HOST, port=int(MYSQL_PORT), user=MYSQL_USER,
        password=MYSQL_PASSWORD, database=MYSQL_DB,
    )
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT unique_topic_id FROM topic WHERE topic_title = %s LIMIT 1",
            (title,),
        )
        row = cursor.fetchone()
        return str(row["unique_topic_id"]).strip() if row else ""
    except Exception:
        return ""
    finally:
        conn.close()


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

    # Path 4: Free-Form Prompt-Driven Report Builder (Ad-hoc Layout Preview & Confirmation)
    if state.get("is_slash_report") or _is_freeform_report_request(combined_query):
        scope = resolve_report_scope(state, combined_query, _lookup_topic_id_by_title, _resolve_report_date_range)
        if scope.get("needs_clarification"):
            clarification = scope.get("clarification_message") or "Could you please specify which topic or date range this report should cover?"
            add_trace("freeform_report_builder", output=f"needs clarification: {clarification}")
            return {"answer": clarification, "needs_clarification": True}
        brief = _extract_report_brief(combined_query, scope)
        topic_label = "Trending Intelligence"
        if scope.get("topics"):
            topic_label = scope["topics"][0].get("topic_title") or "Intelligence Report"

        try:
            preview_res = await asyncio.to_thread(build_adhoc_report_preview, brief)
            template_id = preview_res["template_id"]
            preview_html = preview_res["preview_html"]
            layout_status = preview_res.get("layout_status", "ready")

            preview_payload = {
                "type": "adhoc_report_preview",
                "template_id": template_id,
                "topic_title": topic_label,
                "scope": scope,
                "brief": brief,
                "preview_html": preview_html,
                "layout_status": layout_status,
            }
            preview_text = (
                f"### 📄 Custom Layout Preview Generated\n\n"
                f"I've designed an AI layout preview for **{topic_label}** based on your prompt.\n\n"
                f"Review the preview below. You can **Confirm** to generate the PDF with real data, or **Edit requirements** in the section below."
            )
            answer = f"{preview_text}\n\n```json\n{json.dumps(preview_payload, ensure_ascii=False)}\n```"
            add_trace("freeform_report_builder", output=f"Generated adhoc layout preview {template_id} for {topic_label}")
            return {
                "answer": answer,
                "validated_sql_context": "",
                "needs_clarification": True,
            }
        except Exception as exc:
            print(f"[ollamaagent2] Adhoc preview generation failed: {exc}")
            add_trace("freeform_report_builder", output=f"Adhoc preview failed: {exc}. Trying fallback.")
            try:
                result = await asyncio.to_thread(build_freeform_report, scope, brief)
                report_id = result["report_id"]
                download_url = result.get("download_url", f"/api/reports/download/{report_id}")
                answer = (
                    f"✅ **Your Custom Intelligence Report is ready!**\n\n"
                    f"📄 **Topic/Scope:** {topic_label}\n"
                    f"🎨 **Template Applied:** `{result.get('template_id', 'standard')}`\n"
                    f"📥 **Download PDF:** [Download report (PDF)]({download_url})\n\n"
                    f"*(Archived under Report Reference ID `{report_id}`)*"
                )
                return {"answer": answer, "report_id": report_id, "report_pdf_url": download_url, "needs_clarification": True}
            except Exception as exc2:
                add_trace("freeform_report_builder", output=f"Freeform fallback PDF build failed: {exc2}")
                return {"answer": f"❌ Failed to generate report: {exc2}. Please verify your prompt and try again.", "report_pdf_url": "", "needs_clarification": True}

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

    is_report_request = _is_report_request(combined_query)

    if is_report_request and rows:
        title_to_id = {}
        ordered_titles = []

        # If the user referred to a specific topic ("make a report on THIS")
        # query_rewriter_node already resolved and ground-truth-checked that
        # against last_topic_ids into resolved_topic_reference. That's an
        # explicit single-topic signal and must win over whatever topics the
        # rows for this turn happen to touch — the SQL for "show posts about
        # this topic" often uses broad keyword-expansion LIKE clauses (e.g.
        # a generic '%लखनऊ%' fallback) that can match many OTHER unrelated
        # topics beyond the one the user actually meant. Without this check,
        # a single-topic follow-up like "make report on this" could produce
        # a report covering a dozen unrelated topics that merely share a
        # city name — a real bug this fixes.
        resolved_ref = state.get("resolved_topic_reference")
        if resolved_ref:
            ref_title = ""
            for t in state.get("last_topic_ids", []):
                if t.get("topic_id") == resolved_ref:
                    ref_title = str(t.get("title", "")).strip()
                    break
            if not ref_title:
                for r in rows:
                    if isinstance(r, dict) and str(r.get("unique_topic_id") or "").strip() == resolved_ref:
                        ref_title = str(r.get("topic_title") or "").strip()
                        break
            if ref_title:
                title_to_id[ref_title] = resolved_ref
                ordered_titles.append(ref_title)

        # Otherwise, collect every DISTINCT topic actually present in rows —
        # not just row[0]. A single-incident query's rows are many posts
        # sharing one topic_title/unique_topic_id, so this naturally yields
        # exactly one topic in that case. A genuine multi-topic listing query
        # (e.g. "top 10 trending topics today") has many distinct titles, and
        # "make a report on this all topic" must cover all of them.
        if not ordered_titles:
            for r in rows:
                if not isinstance(r, dict):
                    continue
                t = str(r.get("topic_title") or "").strip()
                tid = str(r.get("unique_topic_id") or "").strip()
                if t and t not in title_to_id:
                    title_to_id[t] = tid
                    ordered_titles.append(t)
                elif t and tid and not title_to_id.get(t):
                    title_to_id[t] = tid

        # Fall back to last_topic_ids (set by execute_sql_node) if rows had
        # no topic_title column at all.
        if not ordered_titles and state.get("last_topic_ids"):
            first = state["last_topic_ids"][0]
            t = str(first.get("title", "")).strip()
            if t:
                title_to_id[t] = str(first.get("topic_id", "")).strip()
                ordered_titles.append(t)
        # Fall back to a quoted title in rewrite_context / the standalone
        # query (covers cases where rows carry neither column at all).
        if not ordered_titles:
            for text in (state.get("rewrite_context"), state.get("query")):
                if not text:
                    continue
                m = re.search(r"['\"]([^'\"]{4,100})['\"]", text)
                if m:
                    t = m.group(1).strip()
                    title_to_id[t] = ""
                    ordered_titles.append(t)
                    break

        ordered_titles = ordered_titles[:MAX_TOPICS_PER_REPORT]
        # Resolve any titles missing an id (the trending-topics-list case —
        # those rows had a title + count but no id column) via a direct
        # lookup rather than giving up. Cheap indexed point queries, run
        # concurrently since there can be up to MAX_TOPICS_PER_REPORT of them.
        need_lookup = [t for t in ordered_titles if not title_to_id.get(t)]
        if need_lookup:
            resolved = await asyncio.gather(*[
                asyncio.to_thread(_lookup_topic_id_by_title, t) for t in need_lookup
            ])
            for t, tid in zip(need_lookup, resolved):
                if tid:
                    title_to_id[t] = tid

        topics = [{"topic_id": title_to_id[t], "topic_title": t} for t in ordered_titles if title_to_id.get(t)]

        # Report-type selection: the picker offers BOTH a "Topic Report" and
        # a "Trending Report" option in one card (see script.js
        # buildReportPickerCard) — the user can switch between them client-
        # side with no extra round trip, so there's no separate confirm step
        # here, just a sensible default. "Topic Report" is unavailable when
        # no specific topic resolved at all (a trending/aggregate report
        # never needed one in the first place, so this no longer bails out
        # the way it used to — see the old fallback message this replaced).
        topic_available = len(topics) > 0
        is_multi = len(topics) > 1
        default_report_type = "topic" if topics and not is_multi else "trending"

        report_id = f"rpt_{uuid.uuid4().hex[:10]}"
        date_range = _resolve_report_date_range(combined_query)

        topic_catalog = get_component_catalog()
        topic_suggested = []
        if topic_available:
            picker_context = final_context or "; ".join(t["topic_title"] for t in topics)
            topic_suggested = await llm_decide_components(state["query"], picker_context, call_llm)

        trending_catalog = get_trending_component_catalog()
        trending_suggested = sorted(V1_TRENDING_COMPONENT_IDS)  # only 5 candidates — all relevant, no LLM call needed

        picker_title = (
            topics[0]["topic_title"] if not is_multi and topics
            else f"{len(topics)} topics ({', '.join(t['topic_title'] for t in topics[:3])}{', …' if len(topics) > 3 else ''})" if topics
            else f"Trending — {date_range['from']}" if date_range["from"] == date_range["to"]
            else f"Trending — {date_range['from']} to {date_range['to']}"
        )
        picker_card = generate_claude_picker_card(
            picker_title,
            trending_catalog if default_report_type == "trending" else topic_catalog,
            trending_suggested if default_report_type == "trending" else topic_suggested,
        )

        # Structured payload for the frontend's interactive picker (report-
        # type radio + checkboxes + Generate button — see script.js
        # buildReportPickerCard()). This is NOT relied on server-side across
        # turns; the frontend echoes it back verbatim as `report_selection`
        # on confirm (see the note at the top of query_rewriter_node and
        # report_builder_node below).
        picker_payload = {
            "type": "report_picker",
            "report_id": report_id,
            "topic_title": picker_title,
            "default_report_type": default_report_type,
            "topic": {
                "available": topic_available,
                "topics": topics,
                "catalog": topic_catalog,
                "suggested": topic_suggested,
            },
            "trending": {
                "available": True,
                "date_range": date_range,
                "catalog": trending_catalog,
                "suggested": trending_suggested,
            },
        }
        answer = f"{picker_card}\n\n```json\n{json.dumps(picker_payload, ensure_ascii=False)}\n```"

        add_trace("llm_validator", user_query=state["query"],
                  output=f"Offered dynamic report picker (default={default_report_type}) — "
                         f"{len(topics)} topic(s) available, window {date_range['from']}..{date_range['to']}")

        return {
            "validated_sql_context": final_context,
            "needs_clarification": True,  # pauses turn and delivers picker card
            "explain_request": False,
            "answer": answer,
            "report_id": report_id,
        }

    return {"validated_sql_context": final_context}


# =========================
# REPORT BUILDER — entry point for the confirm turn (Dynamic Report Maker)
# =========================

async def report_builder_node(state: State) -> dict:
    """Reached directly via the graph's conditional entry point (see
    _graph_entry_decision below), NOT through query_rewriter — the frontend
    supplies `report_selection` in this same turn's request the instant the
    user clicks "Generate report" on the picker card llm_validator_node
    offered, so there's no cross-turn state to recover here.

    Re-fetches all component data fresh from MySQL (build_report ->
    compile_pdf_report -> fetch_topic_report_data) rather than trying to reuse anything from the
    original offering turn — that turn's `rows` live in a State dict this
    process discarded the moment it returned its HTTP response."""
    # Validation + report_id minting + compile dispatch all live in
    # build_report (services/dynamic_report_service.py) — shared with the
    # standalone Report Builder page's POST /api/reports/generate, so the
    # "filter components against the right V1 set, cap topics at 15, require
    # date_range.from for trending" logic can't drift between the two paths.
    sel = state.get("report_selection") or {}
    report_type = sel.get("report_type") or "topic"
    requested_components = sel.get("components") or []
    custom_instructions = str(sel.get("custom_instructions", "")).strip()

    if report_type == "adhoc" or sel.get("template_id"):
        template_id = sel.get("template_id")
        topic_id = sel.get("topic_id")
        date_range = sel.get("date_range")
        scope = sel.get("scope")
        try:
            result = await asyncio.to_thread(
                confirm_adhoc_report,
                template_id=template_id,
                scope=scope,
                topic_id=topic_id,
                date_range=date_range,
                custom_instructions=custom_instructions,
            )
            report_id = result["report_id"]
            download_url = result.get("download_url", f"/api/reports/download/{report_id}")
            report_type_label = "Trending Intelligence" if result.get("report_type") == "trending" else (sel.get("topic_title") or "Intelligence Report")
            answer = (
                f"✅ **Your Custom AI-Designed Report is ready!**\n\n"
                f"📄 **Topic/Scope:** {report_type_label}\n"
                f"🎨 **Template Reference:** `{template_id}`\n"
                f"📥 **Download PDF:** [Download report (PDF)]({download_url})\n\n"
                f"*(Archived under Report Reference ID `{report_id}`)*"
            )
            add_trace("report_builder", output=f"Generated adhoc report {report_id} -> {result['pdf_path']}")
            return {"answer": answer, "report_id": report_id, "report_pdf_url": download_url}
        except Exception as exc:
            add_trace("report_builder", output=f"Adhoc PDF build failed: {exc}")
            return {"answer": f"❌ Failed to compile confirmed PDF report: {exc}. Please try again.", "report_pdf_url": ""}

    if report_type == "trending":
        date_range = sel.get("date_range") or {}
        try:
            result = await asyncio.to_thread(
                build_report, "trending", requested_components, custom_instructions, None, date_range,
            )
        except ReportValidationError:
            add_trace("report_builder", output=f"trending report_selection missing date_range/components — sel_keys={sorted(sel.keys())}")
            return {"answer": "I couldn't confirm which report to build — please ask for the report again."}
        except Exception as exc:
            add_trace("report_builder", output=f"trending PDF build failed: {exc}")
            return {"answer": f"❌ Failed to compile the PDF report: {exc}. Please try again.", "report_pdf_url": ""}

        report_id = result["report_id"]
        download_url = f"/api/reports/download/{report_id}"
        window = date_range["from"] if date_range["from"] == date_range.get("to") else f"{date_range['from']} to {date_range.get('to')}"
        answer = (
            f"✅ **Your Trending Report is ready!**\n\n"
            f"📄 **Window:** {window}\n"
            f"📊 **Sections Generated:** {len(result['components'])} analytical module(s)\n"
            f"📥 **Download PDF:** [Download report (PDF)]({download_url})\n\n"
            f"*(Archived under Report Reference ID `{report_id}`)*"
        )
        add_trace("report_builder", output=f"Generated trending report {report_id} for window {window} -> {result['pdf_path']}")
        return {"answer": answer, "report_id": report_id, "report_pdf_url": download_url}

    # report_type == "topic" (default) — also accepts the older singular
    # topic_id/topic_title shape defensively, in case a stale frontend
    # bundle is still sending it.
    topics = sel.get("topics")
    if not topics and sel.get("topic_id"):
        topics = [{"topic_id": sel["topic_id"], "topic_title": sel.get("topic_title", "")}]
    topic_title = sel.get("topic_title", "") or (topics[0]["topic_title"] if topics else "")

    try:
        result = await asyncio.to_thread(
            build_report, "topic", requested_components, custom_instructions, topics, None,
        )
    except ReportValidationError:
        # Dump exactly what was received (safely — no giant catalog blobs)
        # so a recurrence shows the real cause in the Agent Workflow trace
        # panel instead of forcing a guess: was report_selection itself
        # missing/malformed, was `topics` present but every entry missing
        # topic_id, or was `components` empty?
        diag = {
            "sel_keys": sorted(sel.keys()),
            "raw_topics_type": type(sel.get("topics")).__name__,
            "raw_topics_len": len(sel.get("topics")) if isinstance(sel.get("topics"), list) else None,
            "raw_topics_sample": sel.get("topics")[:2] if isinstance(sel.get("topics"), list) else sel.get("topics"),
            "components_received": sel.get("components"),
        }
        add_trace("report_builder", output=f"report_selection missing topics/components — nothing to build. diag={diag}")
        return {"answer": "I couldn't confirm which report to build — please ask for the report again."}
    except Exception as exc:
        add_trace("report_builder", output=f"PDF build failed: {exc}")
        return {"answer": f"❌ Failed to compile the PDF report: {exc}. Please try again.", "report_pdf_url": ""}

    report_id = result["report_id"]
    topics = result["topics"]
    download_url = f"/api/reports/download/{report_id}"
    topic_summary = topic_title if len(topics) == 1 else f"{len(topics)} topics"
    answer = (
        f"✅ **Your Intelligence Report is ready!**\n\n"
        f"📄 **Report Title:** {topic_summary or 'Untitled Topic'}\n"
        f"📊 **Sections Generated:** {len(result['components'])} analytical module(s) × {len(topics)} topic(s)\n"
        f"📥 **Download PDF:** [Download report (PDF)]({download_url})\n\n"
        f"*(Archived under Report Reference ID `{report_id}`)*"
    )
    add_trace("report_builder", output=f"Generated report {report_id} for {len(topics)} topic(s) -> {result['pdf_path']}")
    return {"answer": answer, "report_id": report_id, "report_pdf_url": download_url}


# NOTE: a standalone freeform_report_builder_node (reached via a freeform_report_request graph-entry-point flag) used to live here. It was dead code — nothing ever set that flag (server.py's ChatRequest has no such field) — and duplicated the logic already running live inside
# llm_validator_node below. Removed rather than wired up, since wiring it as a true entry-point check would run BEFORE this turn's SQL pipeline and lose access to resolved_topic_reference/last_topic_ids, breaking implicit
# references like "make a report on this, dark theme". See the State docstring note above report_selection for the full rationale.


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

    if intent == "summary" and validated_sql_context:
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
- If TOTAL ROWS is 0 and NEAR-MATCH CONTENT is provided below, clearly state
  that no exact database match was found, then list the near-match content as
  possibly-related leads worth a human review — never state them as a
  confirmed count.
- Never show raw SQL to the user.

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

---

## Filtering Rules

For Hindi or multilingual searchable text columns:

* `topic_title`
* `input_text`
* `post_title`
* `reply_text`

**CRITICAL RULE: NEVER use exact match `=` for text columns.**
Always use `LIKE '%...%'`. For example, never write `topic_title = 'सपा छात्र सभा'`, always write `topic_title LIKE '%सपा छात्र सभा%'`. This is because titles in the database often contain prefixes (like 'Lucknow - ') that an exact match will fail to catch.

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

Apply district filtering only when the user requests district/location-based information.

Default district:
Lucknow

However, do NOT blindly add Lucknow filtering.

Use district filters only for:

- topic queries
- incident queries
- post/content queries
- district statistics


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

"""


def generate_sql(question: str, previous_sql: str = "", feedback: str = "", selected_tables: list = None) -> str:
    """Ask the vLLM model to translate a natural-language question into a MySQL SELECT statement."""
    
    user_content = question
    if selected_tables:
        user_content += f"\n\nIMPORTANT: You MUST ONLY use the following tables: {', '.join(selected_tables)}.\nDO NOT hallucinate tables like 'posts' or 'users'. If a table is not in this list, DO NOT USE IT."

    if previous_sql and feedback:
        user_content += f"\n\n===========================\nPREVIOUS SQL ATTEMPT:\n```sql\n{previous_sql}\n```\n\nFEEDBACK / REASON IT FAILED:\n{feedback}\n\nPlease fix the query based on this feedback."

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
    content = response.json()["choices"][0]["message"]["content"]
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


def _resolve_report_date_range(query: str) -> dict:
    """Resolves a {"from","to"} date-range (YYYY-MM-DD) for a trending
    report from the same temporal phrases _temporal_condition_for_query
    already recognizes for SQL generation — reused here instead of a new
    parser. Defaults to "today" when no phrase is found, matching how most
    trending-style queries are actually phrased."""
    today = datetime.now().date()
    if _TEMPORAL_YESTERDAY.search(query or ""):
        d = (today - timedelta(days=1)).isoformat()
        return {"from": d, "to": d}
    if _TEMPORAL_THIS_WEEK.search(query or ""):
        return {"from": (today - timedelta(days=7)).isoformat(), "to": today.isoformat()}
    m = _TEMPORAL_LAST_N_HOURS.search(query or "")
    if m:
        hours = int(m.group(1) or m.group(2))
        days = max(1, -(-hours // 24))  # ceil(hours/24), at least 1 day
        return {"from": (today - timedelta(days=days)).isoformat(), "to": today.isoformat()}
    # _TEMPORAL_TODAY match or no recognizable phrase at all — both default to today.
    return {"from": today.isoformat(), "to": today.isoformat()}


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


async def generate_sql_node(state: State) -> dict:
    """Wraps generate_sql() as a graph node."""
    query = state["query"]
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
            query + topic_instruction + keyword_instruction,
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
    if _is_report_request(query) or _is_freeform_report_request(query) or "/report" in query.lower():
        return "summary"

    prompt = f"""Classify the user's question into exactly one category.

USER QUESTION:
{query}

Rules (apply in order):
1. If the user explicitly asks to READ, SEE, or KNOW the CONTENT/DETAILS *inside* posts — e.g.
   "what is inside this post", "show me what the post says", "summarize the post content",
   "what does the post say", "tell me the details of these posts", "report", "summary" —
   classify as: summary

2. For ALL other questions — including generic listing or search queries like
   "In which post is DGP UP tagged?", "which posts talk about X", "who is mentioned in the posts",
   "posts of Lucknow today", "posts from Delhi", "posts about crime",
   "show posts for Mumbai", "posts today", "recent posts of X" —
   classify as: count
   These are listing/aggregation/search requests, NOT content-detail reading requests.

Respond with ONLY one word: count or summary."""

    raw = await call_llm(prompt)
    label = raw.strip().lower()
    return "count" if "count" in label else "summary"


async def execute_sql_node(state: State) -> dict:
    """Wraps execute_sql() as a graph node. Classifies query intent to decide
    routing: 'count' → judge_and_reason, 'summary' → llm_validator."""
    sql = state.get("sql", "")
    if not sql:
        return {"rows": [], "query_intent": "count"}
        return {"rows": [], "query_intent": "summary" if state.get("is_slash_report") else "count"}

    try:
        rows = await asyncio.to_thread(execute_sql, sql)
        
        # Save to session log and last SQL context
        session_log = state.get("session_log", [])
        session_log.append({
            "query": state["query"],
            "sql": sql,
            "row_count": len(rows)
        })
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
        return {"rows": [], "answer": f"SQL execution error: {exc}",
                "query_intent": "summary" if state.get("is_slash_report") else "count"}

    # Classify query intent checking original query, corrected query, and standalone query
    if state.get("is_slash_report"):
        query_intent = "summary"
    else:
        combined_intent_text = f"{state.get('original_query', '')} {state.get('corrected_query', '')} {state.get('query', '')}"
        query_intent = await _classify_sql_query_intent(combined_intent_text)

    add_trace("execute_sql",
             output=f"{len(rows)} rows; intent={query_intent}")
    # NOTE: last_sql_context/last_topic_ids/post_metadata must be returned here,
    # not set via `state[...] = ...` — LangGraph only persists what a node
    # returns, so a direct mutation of the `state` argument is silently
    # discarded. (This was previously the case and is why post_metadata never
    # reached answer_node's "Source Links" section — URLs were computed here
    # every turn and then thrown away.)
    return {
        "rows": rows,
        "query_intent": query_intent,
        "last_sql_context": last_sql_context,
        "last_topic_ids": topic_ids,
        "post_metadata": post_metadata,
    }


# =========================
# FALLBACK DECIDER NODE
# =========================

async def fallback_decider_node(state: State) -> dict:
    """
    Decides whether a query that failed in MySQL should go to Qdrant (keyword_search)
    to find specific topics/documents first, or directly to Neo4j (graph_query)
    for structural graph traversal.
    """
    query = state["query"]
    feedback = state.get("fallback_feedback", "")
    retry_count = state.get("fallback_retry_count", 0)
    last_route = state.get("fallback_route", "")
    
    feedback_block = ""
    if retry_count > 0 and feedback:
        feedback_block = f"\nWARNING: You previously chose '{last_route}' but it FAILED with this feedback: {feedback}\nYou MUST choose the OTHER option this time!\n"
    
    prompt = f"""
You are a router deciding how to handle a query that returned NO results from a standard SQL database.
The query might be about specific keywords/documents, OR it might be about complex relationships.

Query: "{query}"
{feedback_block}
We have two fallback options:
1. "keyword_search" -> Use Qdrant vector DB. Use this if the user is asking about specific keywords, events, incidents, or text that needs to be matched against documents to find a 'topic_id'. Examples: "Who posted about the Kanwad Yatra?", "What is the URL for the Lucknow library fire?"
2. "graph_query" -> Use Neo4j graph DB directly. Use this if the user is asking about broad relationships, paths, or network structures that do not rely on matching specific text content first. Examples: "Who follows who?", "How many accounts are connected to this user?"

Respond with EXACTLY one word: either "keyword_search" or "graph_query".
"""
    decision = (await call_llm(prompt)).strip().lower()
    
    if "graph" in decision:
        route = "graph_query"
    else:
        route = "keyword_search"
        
    add_trace("fallback_decider", output=f"Route: {route}")
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
# START → query_rewriter → query_manager → router
#   ├─ "database" → table_selector → generate_sql → sql_judge
#   │                                                  ├─ pass  → is_safe_sql → execute_sql
#   │                                                  └─ retry → table_selector (loop, max 2)
#   │                                               execute_sql
#   │                                                  ├─ judge     → judge_and_reason → answer → END
#   │                                                  ├─ summary   → llm_validator → judge_and_reason → answer → END
#   │                                                  └─ zero_rows → content_index_search → table_selector (loop, max 2)
#   └─ "pdf_chat" → pdf_search → pdf_answer → END

def _route_decision(state: State) -> str:
    """Router conditional edge: database or pdf_chat."""
    return state["route"]


def _sql_judge_decision(state: State) -> str:
    """sql_judge conditional edge: pass or retry."""
    if state.get("sql_matches", True):
        return "pass"
    return "retry"


def _execute_decision(state: State) -> str:
    """execute_sql conditional edge: judge, summary, or zero_rows.
    - 'count' intent → judge_and_reason (just format numbers)
    - 'summary' intent → llm_validator (batch-process row content & report generation)
    - 0 rows → content_index_search (fallback)
    """
    # Slash reports or report builder requests MUST always go to llm_validator (summary)
    # even if a specific SQL query returned 0 rows, so the layout preview card is delivered!
    combined_query = f"{state.get('original_query', '')} {state.get('corrected_query', '')} {state.get('query', '')}"
    if state.get("is_slash_report") or _is_report_request(combined_query) or _is_freeform_report_request(combined_query):
        return "summary"

    rows = state.get("rows", [])
    sql = state.get("sql", "")

    # If sql is empty (safety check failed), go straight to judge→answer
    if not sql:
        return "judge"

    is_zero_result = False
    if not rows:
        is_zero_result = True
    elif len(rows) == 1:
        # E.g. {"COUNT(*)": 0} or {"total_posts": 0}
        # A single row with only 0 or None values is functionally "0 rows" for our fallback
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
    the user (needs_clarification=True) — no hop back to query_rewriter; queries
    with a table/topic (already classified) go through the keyword steps;
    everything else skips straight to table_selector."""
    if not state.get("is_query_correct", True):
        return "retry"
    if state.get("needs_clarification"):
        return "end"
    if state.get("has_table_topic", True):
        return "has_table_topic"
    return "no_table_topic"

def _endpoint_route_decision(state: State) -> str:
    """check_and_run_endpoint_routes conditional edge: matched -> answer the
    user and end the turn; no match -> fall through to router_node exactly
    as before."""
    if state.get("endpoint_route_matched"):
        return "matched"
    return "no_match"

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

# Add all nodes
_builder.add_node("query_rewriter", query_rewriter_node)
_builder.add_node("query_manager", query_manager_node)
_builder.add_node("check_and_run_endpoint_routes", check_and_run_endpoint_routes_node)
_builder.add_node("check_query_manager", check_query_manager_node)
_builder.add_node("keyword_of_post_maker", keyword_of_post_maker_node)
_builder.add_node("keyword_of_post_maker_and_checker", keyword_of_post_maker_and_checker_node)
_builder.add_node("go_duck_search", go_duck_search_node)
_builder.add_node("go_duck_search_verify", go_duck_search_verify_node)
_builder.add_node("router", router_node)
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
_builder.add_node("pdf_search", pdf_search_node)
_builder.add_node("pdf_answer", pdf_answer_node)
_builder.add_node("report_builder", report_builder_node)
_builder.add_node("endpoint_write_executor", endpoint_write_executor_node)
_builder.add_node("endpoint_multi_run_executor", endpoint_multi_run_executor_node) 

def _answer_checker_decision(state: State) -> str:
    if state.get("answer_retry_count", 0) >= 2 or not state.get("answer_feedback"):
        return "end"
    return "retry"

def _graph_entry_decision(state: State) -> str:
    if state.get("report_selection"):
        return "report_builder"
    if state.get("endpoint_write_confirmation"):
        return "endpoint_write_executor"
    if state.get("endpoint_multi_selection"):          
        return "endpoint_multi_run_executor"
    return "query_rewriter"

_builder.set_conditional_entry_point(_graph_entry_decision, {
    "query_rewriter": "query_rewriter",
    "report_builder": "report_builder",
    "endpoint_write_executor": "endpoint_write_executor",
    "endpoint_multi_run_executor": "endpoint_multi_run_executor",   
})
_builder.add_edge("report_builder", END)
_builder.add_edge("endpoint_write_executor", END)
# endpoint_multi_run_executor: matched (real data found) -> end the turn;
# no match (every selected endpoint came back empty/unreachable) -> fall
# through to router_node/the normal DB+pdf pipeline instead of ending on
# a dead-end "nothing found", same as check_and_run_endpoint_routes below.
_builder.add_conditional_edges("endpoint_multi_run_executor", _endpoint_route_decision, {
    "matched": END,
    "no_match": "router",
})

# query_rewriter → query_manager OR END (if needs clarification)
_builder.add_conditional_edges("query_rewriter", _query_rewriter_decision, {
    "end": END,
    "query_manager": "query_manager",
})
# query_manager → check_and_run_endpoint_routes
_builder.add_edge("query_manager", "check_and_run_endpoint_routes")

_builder.add_conditional_edges("check_and_run_endpoint_routes", _endpoint_route_decision, {
    "matched": END,
    "no_match": "router",
})

# Router → database (check_query_manager) or pdf_chat (pdf_search)
_builder.add_conditional_edges("router", _route_decision, {
    "database": "check_query_manager",
    "pdf_chat": "pdf_search",
})

# check_query_manager → keyword steps (has table/topic) or straight to table_selector
_builder.add_conditional_edges("check_query_manager", _check_query_manager_decision, {
    "retry": "query_rewriter",
    "end": END,
    "has_table_topic": "keyword_of_post_maker",
    "no_table_topic": "table_selector",
})

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
    """llm_validator conditional edge: routes directly to END when the report
    picker card (or a "can't build that yet" explanation) was delivered as
    `answer` with needs_clarification=True; otherwise continues to
    judge_and_reason to reason over the batch-extracted context."""
    if state.get("needs_clarification"):
        return "end"
    return "judge"

# llm_validator → judge_and_reason (regular summary) OR END (dynamic report picker card offered)
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

# PDF path
_builder.add_edge("pdf_search", "pdf_answer")
_builder.add_edge("pdf_answer", END)

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
            "route": "",
            "pdf_uploaded": False,
            "pdf_filenames": [],
            "pdf_results": [],
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
        print(f"\nRoute: {result.get('route')}")
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

        # Carry a pending ask_user/classification confirmation into the next turn
        pending_keyword_confirmation = result.get("pending_keyword_confirmation")

        messages.append({"role": "user", "content": question})
        messages.append({"role": "assistant", "content": result.get("answer") or ""})


if __name__ == "__main__":
    asyncio.run(main())