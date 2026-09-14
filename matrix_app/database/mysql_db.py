import os
from pathlib import Path
from dotenv import load_dotenv
import mysql.connector

# Ensure environment variables from matrix_app/.env are loaded
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

def get_connection():
    user = os.getenv("MYSQL_USER", "readUser").strip()
    password = os.getenv("MYSQL_PASSWORD", "readUser@123").strip()
    
    # Safeguard against accidental username/password mismatch
    if user == "readUser@123":
        user = "readUser"

    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "10.242.71.180"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=user,
        password=password,
        database=os.getenv("MYSQL_DB", "up_police_matrix").strip(),
        connection_timeout=10,
    )

def run_query(sql: str, params: tuple = ()) -> list:
    """Execute an arbitrary read-only SQL query and return rows as a list of
    dicts. Used by the network-graph analysis routes in server.py, which
    generate their SQL dynamically (see check_sql_safety in ollamaagent2.py
    for the safety gate applied before this ever runs)."""
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
        return rows
    finally:
        conn.close()


def get_district_counts(district: str):
    """Single pass over analyzed_data instead of 4 separate COUNT(*) queries —
    each bucket was doing its own full scan of the same LIKE '%district%'
    match, so 4 queries meant scanning the same matching rows 4 times.
    Measured on the real table (2.15M rows): 4 separate queries ~6.8s total,
    this single combined query ~2.0s. Still one scan per district lookup —
    a real index on (primary_district, created_at) would help further, but
    the app's DB user only has SELECT, not the privileges to add one."""
    district_clean = district.strip()
    like_dist = f"%{district_clean}%"

    today_count = yesterday_count = week_count = total_count = 0

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                SUM(CASE WHEN DATE(created_at) = CURDATE() THEN 1 ELSE 0 END) AS today_count,
                SUM(CASE WHEN DATE(created_at) = CURDATE() - INTERVAL 1 DAY THEN 1 ELSE 0 END) AS yesterday_count,
                SUM(CASE WHEN DATE(created_at) BETWEEN CURDATE() - INTERVAL 6 DAY AND CURDATE() THEN 1 ELSE 0 END) AS week_count,
                COUNT(*) AS total_count
            FROM analyzed_data
            WHERE primary_district LIKE %s
        """, (like_dist,))
        row = cursor.fetchone()
        if row:
            today_count = row[0] or 0
            yesterday_count = row[1] or 0
            week_count = row[2] or 0
            total_count = row[3] or 0

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"MySQL Error: {e}")

    return {
        "today": today_count,
        "yesterday": yesterday_count,
        "last_7_days": week_count,
        "total": total_count
    }

def get_feed_posts(district: str, limit: int = 30, offset: int = 0):
    district_clean = district.strip()
    like_dist = f"%{district_clean}%"
    posts = []
    
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, input_text, primary_district, primary_thana, topic_title,
                   sentiment_label, source_type, post_bank_post_url, created_at
            FROM analyzed_data
            WHERE primary_district LIKE %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (like_dist, limit, offset)
        )
        rows = cursor.fetchall()
        for r in rows:
            posts.append({
                "id": r.get("id"),
                "text": r.get("input_text", ""),
                "district": r.get("primary_district", ""),
                "thana": r.get("primary_thana", ""),
                "topic": r.get("topic_title", ""),
                "sentiment": (r.get("sentiment_label") or "neutral").lower(),
                "source": r.get("source_type", "media"),
                "url": r.get("post_bank_post_url", ""),
                "created_at": str(r.get("created_at", ""))
            })
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Feed query error: {e}")
        
    return posts

def get_posts_by_ids(ids: list):
    if not ids:
        return []

    posts = []
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # Create placeholders for IN clause
        format_strings = ','.join(['%s'] * len(ids))
        # LEFT JOIN post_users so the Multi Topic Analysis panel can build a
        # topic->user network graph straight from these already-resolved
        # posts, instead of re-querying /network/agent with fresh keywords
        # (which returns a disconnected, unrelated result set).
        cursor.execute(
            f"""
            SELECT ad.id, ad.input_text, ad.primary_district, ad.primary_thana, ad.topic_title,
                   ad.unique_topic_id, ad.sentiment_label, ad.source_type, ad.post_bank_post_url,
                   ad.created_at, ad.post_user_id, pu.username, pu.display_name, pu.platform,
                   pu.followers_count, pu.is_verified, pu.profile_image_url
            FROM analyzed_data ad
            LEFT JOIN post_users pu ON ad.post_user_id = pu.id
            WHERE ad.id IN ({format_strings})
            ORDER BY ad.created_at DESC
            """,
            tuple(ids)
        )
        rows = cursor.fetchall()
        for r in rows:
            posts.append({
                "id": r.get("id"),
                "text": r.get("input_text", ""),
                "district": r.get("primary_district", ""),
                "thana": r.get("primary_thana", ""),
                "topic": r.get("topic_title", ""),
                "uniqueTopicId": r.get("unique_topic_id"),
                "sentiment": (r.get("sentiment_label") or "neutral").lower(),
                "source": r.get("source_type", "media"),
                "url": r.get("post_bank_post_url", ""),
                "created_at": str(r.get("created_at", "")),
                "userId": r.get("post_user_id"),
                "username": r.get("username"),
                "displayName": r.get("display_name"),
                "platform": r.get("platform"),
                "followersCount": r.get("followers_count"),
                "isVerified": bool(r.get("is_verified") or False),
                "profileImageUrl": r.get("profile_image_url"),
            })
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"SQL posts by IDs query error: {e}")

    return posts
