import time
import json
from neo4j import GraphDatabase

import config
import db

URI = config.NEO4J_URI
USER = config.NEO4J_USER
PASSWORD = config.NEO4J_PASSWORD

driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

def safe_list(val):
    if not val or val in ("[]", "null"):
        return []
    if isinstance(val, str) and val.startswith("["):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            pass
    if isinstance(val, str):
        return [c.strip() for c in val.split(",") if c.strip()]
    return [val]

def clean_username(username):
    if not username: return "unknown_user"
    return str(username).strip().lower()

def create_indexes(session):
    print("⏳ Creating Neo4j indexes...")
    indexes = [
        "CREATE INDEX IF NOT EXISTS FOR (n:Account) ON (n.username)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Account) ON (n.user_id)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Content) ON (n.post_id)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Incident) ON (n.topic_id)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Category) ON (n.name)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Location) ON (n.name)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Keyword) ON (n.name)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Hashtag) ON (n.name)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Ticket) ON (n.ticket_id)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Report) ON (n.report_id)",
    ]
    for idx in indexes:
        session.run(idx)
    print("✅ Indexes created.")

def run_batch(session, query, data_list, desc=""):
    BATCH_SIZE = 2000
    for i in range(0, len(data_list), BATCH_SIZE):
        batch = data_list[i:i+BATCH_SIZE]
        session.run(query, rows=batch)
    print(f"   ✓ {desc} - {len(data_list):,} records processed")

# --- PHASE 1: CORE ENTITIES ---

def sync_accounts(session):
    print("\n🔄 Syncing Accounts...")
    data = []
    for batch in db.fetch_batches("post_users", ["id", "username", "display_name", "platform", "is_verified", "is_blue_verified", "followers_count", "following_count"]):
        for r in batch:
            data.append({
                "user_id": r["id"],
                "username": clean_username(r["username"]),
                "display_name": r["display_name"],
                "platform": r["platform"],
                "verified": bool(r.get("is_verified") or r.get("is_blue_verified")),
                "followers": r.get("followers_count") or 0,
                "following": r.get("following_count") or 0
            })
    
    query = """
    UNWIND $rows AS row
    MERGE (a:Account {username: row.username})
    SET a.user_id = row.user_id, a.display_name = row.display_name, a.platform = row.platform,
        a.verified = row.verified, a.followers = row.followers, a.following = row.following
    """
    run_batch(session, query, data, "post_users -> Account")

    # Flag monitored profiles
    mon_data = []
    for batch in db.fetch_batches("monitor_profiles", ["id", "user_name", "category", "sub_category"]):
        for r in batch:
            mon_data.append({"username": clean_username(r["user_name"]), "cat": r.get("category")})
    run_batch(session, """
    UNWIND $rows AS row
    MATCH (a:Account {username: row.username})
    SET a.is_monitored = true, a.monitor_category = row.cat
    """, mon_data, "monitor_profiles -> Account (is_monitored)")

def sync_content(session):
    print("\n🔄 Syncing Content...")
    # analyzed_data
    ad_data = []
    for batch in db.fetch_batches("analyzed_data", ["id", "input_text", "sentiment_label", "post_bank_core_source", "post_bank_author_username", "unique_topic_id", "primary_district", "broad_category", "sub_category"]):
        for r in batch:
            post_id = f"ad_{r['id']}"
            ad_data.append({
                "post_id": post_id, "text": r["input_text"][:500] if r["input_text"] else "",
                "sentiment": r.get("sentiment_label"), "platform": r.get("post_bank_core_source"),
                "author": clean_username(r.get("post_bank_author_username")), "topic_id": r.get("unique_topic_id"),
                "district": r.get("primary_district"), "broad": safe_list(r.get("broad_category")), "sub": safe_list(r.get("sub_category"))
            })
    
    query = """
    UNWIND $rows AS row
    MERGE (c:Content {post_id: row.post_id})
    SET c.text = row.text, c.sentiment = row.sentiment, c.platform = row.platform, c.source_table = 'analyzed_data'
    WITH c, row
    WHERE row.author <> 'unknown_user'
    MERGE (a:Account {username: row.author})
    MERGE (a)-[:POSTED]->(c)
    """
    run_batch(session, query, ad_data, "analyzed_data -> Content")

    # Link to incident, location, categories
    run_batch(session, """
    UNWIND $rows AS row
    MATCH (c:Content {post_id: row.post_id})
    WHERE row.topic_id IS NOT NULL
    MERGE (i:Incident {topic_id: row.topic_id})
    MERGE (c)-[:BELONGS_TO]->(i)
    """, ad_data, "Content -> Incident")

    run_batch(session, """
    UNWIND $rows AS row
    MATCH (c:Content {post_id: row.post_id})
    WHERE row.district IS NOT NULL AND row.district <> '[]'
    MERGE (l:Location {name: row.district}) SET l.type = 'DISTRICT'
    MERGE (c)-[:OCCURRED_IN]->(l)
    """, ad_data, "Content -> Location")

    # Replies
    reply_data = []
    for batch in db.fetch_batches("reply", ["id", "post_bank_id", "reply_text", "reply_author_username"]):
        for r in batch:
            reply_data.append({
                "post_id": f"reply_{r['id']}", "text": r["reply_text"][:500] if r["reply_text"] else "",
                "author": clean_username(r.get("reply_author_username")), "orig_id": f"ad_{r.get('post_bank_id')}"
            })
    
    run_batch(session, """
    UNWIND $rows AS row
    MERGE (c:Content {post_id: row.post_id})
    SET c.text = row.text, c.content_type = 'REPLY'
    WITH c, row
    WHERE row.author <> 'unknown_user'
    MERGE (a:Account {username: row.author})
    MERGE (a)-[:POSTED]->(c)
    """, reply_data, "reply -> Content")
    
    run_batch(session, """
    UNWIND $rows AS row
    MATCH (reply:Content {post_id: row.post_id})
    MATCH (orig:Content {post_id: row.orig_id})
    MERGE (reply)-[:REPLIED_TO]->(orig)
    """, reply_data, "reply -> REPLIED_TO -> Content")

def sync_taxonomy_and_workflow(session):
    print("\n🔄 Syncing Taxonomy & Workflow...")
    
    # Topics (Incidents)
    topics = []
    for batch in db.fetch_batches("topic", ["id", "unique_topic_id", "topic_title"]):
        for r in batch:
            topics.append({"topic_id": r.get("unique_topic_id") or f"topic_{r['id']}", "title": r.get("topic_title")})
    run_batch(session, """
    UNWIND $rows AS row
    MERGE (i:Incident {topic_id: row.topic_id})
    SET i.title = row.title
    """, topics, "topic -> Incident")

    # Keywords & Hashtags
    kws = []
    for batch in db.fetch_batches("keywords", ["id", "english_keyword", "broad_category_name"]):
        for r in batch:
            if r.get("english_keyword"):
                kws.append({"name": r["english_keyword"], "cat": r.get("broad_category_name")})
    run_batch(session, """
    UNWIND $rows AS row
    MERGE (k:Keyword {name: row.name})
    WITH k, row
    WHERE row.cat IS NOT NULL
    MERGE (c:Category {name: row.cat})
    MERGE (k)-[:BELONGS_TO_CATEGORY]->(c)
    """, kws, "keywords -> Keyword")

    # Hashtags
    hts = []
    for batch in db.fetch_batches("hashtags", ["id", "hashtag_keyword", "hastag_keyword_category"]):
        for r in batch:
            if r.get("hashtag_keyword"):
                hts.append({"name": r["hashtag_keyword"], "cat": r.get("hastag_keyword_category")})
    run_batch(session, """
    UNWIND $rows AS row
    MERGE (h:Hashtag {name: row.name})
    WITH h, row
    WHERE row.cat IS NOT NULL
    MERGE (c:Category {name: row.cat})
    MERGE (h)-[:BELONGS_TO_CATEGORY]->(c)
    """, hts, "hashtags -> Hashtag")

    # Tickets
    tickets = []
    for batch in db.fetch_batches("ticket_raised_table", ["id", "ticket_unique_id", "author_username", "topic_unique_id"]):
        for r in batch:
            tickets.append({
                "ticket_id": r.get("ticket_unique_id") or f"ticket_{r['id']}",
                "author": clean_username(r.get("author_username")),
                "topic_id": r.get("topic_unique_id")
            })
    run_batch(session, """
    UNWIND $rows AS row
    MERGE (t:Ticket {ticket_id: row.ticket_id})
    WITH t, row
    WHERE row.author <> 'unknown_user'
    MERGE (a:Account {username: row.author})
    MERGE (a)-[:RAISED_TICKET]->(t)
    WITH t, row
    WHERE row.topic_id IS NOT NULL
    MERGE (i:Incident {topic_id: row.topic_id})
    MERGE (t)-[:RAISED_FOR]->(i)
    """, tickets, "ticket_raised_table -> Ticket")

    # Reports
    reports = []
    for batch in db.fetch_batches("district_internal_report", ["id", "crime_type", "district", "thana", "unique_topic_id"]):
        for r in batch:
            reports.append({
                "report_id": f"dir_{r['id']}", "crime_type": r.get("crime_type"),
                "district": r.get("district"), "topic_id": r.get("unique_topic_id")
            })
    run_batch(session, """
    UNWIND $rows AS row
    MERGE (r:Report {report_id: row.report_id})
    SET r.crime_type = row.crime_type
    WITH r, row
    WHERE row.topic_id IS NOT NULL
    MERGE (i:Incident {topic_id: row.topic_id})
    MERGE (r)-[:FILED_FOR]->(i)
    WITH r, row
    WHERE row.district IS NOT NULL
    MERGE (l:Location {name: row.district}) SET l.type = 'DISTRICT'
    MERGE (r)-[:FILED_IN]->(l)
    """, reports, "district_internal_report -> Report")


def sync_social_and_interactions(session):
    print("\n🔄 Syncing Social Graph & Interactions...")
    
    # post_user_interactions
    interactions = []
    for batch in db.fetch_batches("post_user_interactions", ["id", "post_user_id", "analyzed_data_id", "interaction_type"]):
        for r in batch:
            if r.get("post_user_id") and r.get("analyzed_data_id"):
                interactions.append({
                    "user_id": r["post_user_id"],
                    "post_id": f"ad_{r['analyzed_data_id']}",
                    "type": r.get("interaction_type", "INTERACTED")
                })
    run_batch(session, """
    UNWIND $rows AS row
    MATCH (a:Account {user_id: row.user_id})
    MATCH (c:Content {post_id: row.post_id})
    CALL apoc.create.relationship(a, row.type, {}, c) YIELD rel
    RETURN rel
    """, interactions, "post_user_interactions -> INTERACTED_WITH (apoc needed, using fallback)")

    # fallback if APOC is missing
    run_batch(session, """
    UNWIND $rows AS row
    MATCH (a:Account {user_id: row.user_id})
    MATCH (c:Content {post_id: row.post_id})
    MERGE (a)-[:INTERACTED_WITH {type: row.type}]->(c)
    """, interactions, "post_user_interactions -> INTERACTED_WITH")

    # profile_network
    network = []
    for batch in db.fetch_batches("profile_network", ["id", "user_id", "follower_id", "relationship_type"]):
        for r in batch:
            if r.get("user_id") and r.get("follower_id"):
                network.append({
                    "u1": r["follower_id"], "u2": r["user_id"], 
                    "rel": r.get("relationship_type", "FOLLOWS")
                })
    run_batch(session, """
    UNWIND $rows AS row
    MATCH (a1:Account {user_id: row.u1})
    MATCH (a2:Account {user_id: row.u2})
    MERGE (a1)-[:FOLLOWS]->(a2)
    """, network, "profile_network -> FOLLOWS")

def verify_graph(session):
    print("\n📊 NEO4J GRAPH SUMMARY:")
    checks = [
        ("Account", "MATCH (a:Account) RETURN count(a) AS n"),
        ("Content", "MATCH (c:Content) RETURN count(c) AS n"),
        ("Incident", "MATCH (i:Incident) RETURN count(i) AS n"),
        ("Category", "MATCH (c:Category) RETURN count(c) AS n"),
        ("Location", "MATCH (l:Location) RETURN count(l) AS n"),
        ("Keyword", "MATCH (k:Keyword) RETURN count(k) AS n"),
        ("Ticket", "MATCH (t:Ticket) RETURN count(t) AS n"),
        ("Report", "MATCH (r:Report) RETURN count(r) AS n"),
        ("POSTED", "MATCH ()-[r:POSTED]->() RETURN count(r) AS n"),
        ("FOLLOWS", "MATCH ()-[r:FOLLOWS]->() RETURN count(r) AS n"),
        ("INTERACTED_WITH", "MATCH ()-[r:INTERACTED_WITH]->() RETURN count(r) AS n"),
        ("BELONGS_TO", "MATCH ()-[r:BELONGS_TO]->() RETURN count(r) AS n"),
        ("OCCURRED_IN", "MATCH ()-[r:OCCURRED_IN]->() RETURN count(r) AS n"),
    ]
    for label, query in checks:
        result = session.run(query).single()
        count  = result["n"] if result else 0
        print(f"   {'✓' if count > 0 else '✗'} {label:<35}: {count:>10,}")

if __name__ == "__main__":
    print("=" * 60)
    print("  GOD-MODE GRAPH: 18-TABLE NEO4J BUILDER")
    print("=" * 60)
    
    with driver.session() as session:
        create_indexes(session)
        sync_accounts(session)
        sync_content(session)
        sync_taxonomy_and_workflow(session)
        sync_social_and_interactions(session)
        verify_graph(session)

    driver.close()
    print("\n🚀 Done! Open Neo4j Browser at http://localhost:7474 to explore.")
