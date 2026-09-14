#!/usr/bin/env python3
import os
import sys
import time
import argparse
import httpx
from datetime import datetime, timezone, timedelta

try:
    from pymongo import MongoClient
    HAS_MONGO = True
except ImportError:
    HAS_MONGO = False

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, Range, OrderBy
    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False

DEFAULT_SERVER_URL = "http://127.0.0.1:8123"
QUESTIONS_FILE = "question"

# sql_history moved off MongoDB onto a dedicated local Qdrant instance (see
# ollamaagent2.py's QDRANT LOG STORE section / SQL_LOG_COLLECTION) — this
# script must read from there now, not from Mongo's (now permanently empty)
# sql_history collection. agent_review_queue is unaffected — that one is
# still on Mongo, only used for queries the pipeline gave up on entirely.
QDRANT_LOG_HOST = os.environ.get("QDRANT_LOG_HOST", "localhost")
QDRANT_LOG_PORT = int(os.environ.get("QDRANT_LOG_PORT", "6333"))
SQL_LOG_COLLECTION = "sql_history"

def load_questions(filepath):
    """
    Reads the questions file and filters out categories/headers.
    Extracts all lines ending with '?' or specified viral queries.
    """
    questions = []
    if not os.path.exists(filepath):
        print(f"Error: Questions file '{filepath}' not found in current directory.")
        return []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            cleaned = line.strip()
            if not cleaned:
                continue
            
            # Identify questions: lines ending with '?' or specific general questions
            if cleaned.endswith('?') or cleaned.lower() in ["what is viral today", "why it is viral"]:
                questions.append({
                    "id": len(questions) + 1,
                    "original_line_num": line_num,
                    "text": cleaned
                })
    return questions

def clear_session(client, server_url):
    """Calls the /api/clear endpoint to reset agent memory."""
    url = f"{server_url}/api/clear"
    try:
        response = client.post(url, timeout=10.0)
        if response.status_code == 200:
            return True
        else:
            print(f"\n[Warning] Failed to clear session (HTTP {response.status_code})")
            return False
    except Exception as e:
        print(f"\n[Warning] Connection error while clearing session: {e}")
        return False

def query_chat(client, server_url, query_text):
    """Sends a question to /api/chat and streams the response to stdout."""
    url = f"{server_url}/api/chat"
    payload = {"query": query_text, "limit": "50"}
    answer_chunks = []
    
    try:
        with client.stream("POST", url, json=payload, timeout=360.0) as response:
            if response.status_code != 200:
                err_msg = f"\n[Error] API returned HTTP {response.status_code}"
                print(err_msg)
                return err_msg
                
            for chunk in response.iter_text():
                sys.stdout.write(chunk)
                sys.stdout.flush()
                answer_chunks.append(chunk)
    except httpx.RequestError as e:
        err_msg = f"\n[Error] Connection failed: {e}"
        print(err_msg)
        return err_msg
    except Exception as e:
        err_msg = f"\n[Error] An unexpected error occurred: {e}"
        print(err_msg)
        return err_msg
        
    print()  # Add trailing newline after stream completion
    return "".join(answer_chunks)

def _get_latest_qdrant_sql_doc(qdrant_client, since_ts):
    """Most recent sql_history point from the local Qdrant log store, or None
    if there isn't one at/after since_ts. Mirrors ollamaagent2.py's own
    _get_latest_log_point, minus the session_id filter (this script has no
    session concept — it just wants "whatever was logged since call_start")."""
    if qdrant_client is None:
        return None
    try:
        points, _ = qdrant_client.scroll(
            collection_name=SQL_LOG_COLLECTION,
            scroll_filter=Filter(must=[FieldCondition(key="created_at_ts", range=Range(gte=since_ts))]),
            order_by=OrderBy(key="created_at_ts", direction="desc"),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        return points[0].payload if points else None
    except Exception as e:
        print(f"\n[Warning] Failed to read from Qdrant sql_history: {e}")
        return None


def get_latest_sql_query(mongo_db, qdrant_client, since=None):
    """
    Retrieves the most recent SQL query executed or blocked by checking
    sql_history (local Qdrant instance — see ollamaagent2.py's QDRANT LOG
    STORE section) and agent_review_queue (still MongoDB).

    `since` should be the UTC timestamp captured right BEFORE the /api/chat
    call was made. We accept any doc created at or after that point (minus a
    small clock-skew buffer), rather than "within N seconds of now" — the SQL
    insert happens mid-pipeline (before judge_and_reason/answer_node), and a
    local LLM backend can easily take longer than a few seconds for the
    remaining steps, so comparing against "now" (i.e. after the full answer
    has streamed back) systematically misses genuine matches on slower runs.

    Returns (generated_sql, rewritten_query, retry_count) — retry_count is
    the SQL-planning loop's attempt number for that query (see
    ollamaagent2.py's "🔄 Graph execution loop count" — table_selector_and_decider_node
    increments state["retry_count"] each pass, capped at 3 before falling
    back to semantic search), or None if it wasn't recorded.
    """
    if mongo_db is None and qdrant_client is None:
        return None, None, None

    if since is None:
        since = datetime.now(timezone.utc)
    cutoff = since - timedelta(seconds=2)  # small buffer for clock skew

    doc = _get_latest_qdrant_sql_doc(qdrant_client, cutoff.timestamp())

    rev_doc = None
    if mongo_db is not None:
        try:
            rev_doc = mongo_db["agent_review_queue"].find_one(sort=[("created_at", -1)])
        except Exception as e:
            print(f"\n[Warning] Failed to read from MongoDB: {e}")

    selected_doc = None
    doc_type = None

    docs_to_compare = []
    if doc and "created_at" in doc:
        # created_at was stored via .isoformat() (see _qdrant_payload_safe)
        t = datetime.fromisoformat(doc["created_at"])
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        docs_to_compare.append((t, doc, "history"))

    if rev_doc and "created_at" in rev_doc:
        t = rev_doc["created_at"]
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        docs_to_compare.append((t, rev_doc, "review"))

    if docs_to_compare:
        docs_to_compare.sort(key=lambda x: x[0], reverse=True)
        newest_time, newest_doc, dtype = docs_to_compare[0]

        # Accept anything written at/after the call started (not "near now")
        if newest_time >= cutoff:
            selected_doc = newest_doc
            doc_type = dtype

    if selected_doc:
        if doc_type == "history":
            return selected_doc.get("generated_sql"), selected_doc.get("query"), selected_doc.get("retry_count")
        else:
            reason = selected_doc.get("reason", "Unknown block")
            stage = selected_doc.get("stage", "Unknown stage")
            details = selected_doc.get("details", {})
            sql = details.get("generated_sql") or details.get("sql") or f"Blocked at {stage} (Reason: {reason})"
            return sql, selected_doc.get("query"), details.get("retry_count")

    return None, None, None

def run_tests(questions_to_run, mode, server_url):
    """Runs the queries in either 'memory', 'no_memory', or 'both' modes."""
    print(f"\n🚀 Starting test execution targeting: {server_url}")
    print(f"📋 Mode: {mode.upper()}")
    print(f"📊 Total Questions: {len(questions_to_run)}")
    
    client = httpx.Client()
    
    # Check server availability
    try:
        health_check = client.get(f"{server_url}/", timeout=3.0)
        print("✅ Server is online and reachable.")
    except Exception as e:
        print(f"❌ Error: Cannot connect to server at {server_url}. Is it running?")
        print(f"Details: {e}")
        sys.exit(1)

    # Connect to MongoDB for SQL tracking
    mongo_db = None
    if HAS_MONGO:
        try:
            mongo_client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=2000)
            mongo_client.server_info()  # Test connection
            mongo_db = mongo_client["ai_agent"]
            print("✅ Successfully connected to MongoDB for SQL logging.")
        except Exception as e:
            print(f"⚠️ Warning: Could not connect to MongoDB ({e}). Review-queue tracking will be skipped.")
    else:
        print("⚠️ Warning: pymongo not installed. Review-queue tracking will be skipped.")

    # Connect to the local Qdrant log store for SQL tracking (sql_history —
    # see get_latest_sql_query's docstring for why this isn't MongoDB anymore)
    qdrant_log_client = None
    if HAS_QDRANT:
        try:
            qdrant_log_client = QdrantClient(QDRANT_LOG_HOST, port=QDRANT_LOG_PORT, check_compatibility=False, timeout=10)
            qdrant_log_client.get_collection(SQL_LOG_COLLECTION)  # Test connection + collection exists
            print("✅ Successfully connected to Qdrant for SQL logging.")
        except Exception as e:
            print(f"⚠️ Warning: Could not connect to Qdrant sql_history ({e}). SQL queries tracking will be skipped.")
            qdrant_log_client = None
    else:
        print("⚠️ Warning: qdrant_client not installed. SQL queries tracking will be skipped.")

    # Establish output files
    with_mem_file = "with_memory.txt"
    no_mem_file = "without_memory.txt"
    
    modes_to_run = []
    if mode == "both":
        modes_to_run = ["no_memory", "memory"]
    else:
        modes_to_run = [mode]

    for current_mode in modes_to_run:
        print(f"\n=======================================================")
        print(f" Running Mode: {current_mode.upper()} ")
        print(f"=======================================================")
        
        output_file = with_mem_file if current_mode == "memory" else no_mem_file
        queries_file = "queries_with_memory.txt" if current_mode == "memory" else "queries_without_memory.txt"
        
        # If running memory-based, clear session once at the start of the sequence
        if current_mode == "memory":
            print("🧹 Clearing session to start memory-based run with a clean slate...")
            clear_session(client, server_url)
            
        with open(output_file, "w", encoding="utf-8") as out, \
             open(queries_file, "w", encoding="utf-8") as q_out:
             
            out.write(f"=== TEST RUN IN MODE: {current_mode.upper()} AT {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
            q_out.write(f"=== SQL QUERIES LOG IN MODE: {current_mode.upper()} AT {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
            
            for i, q in enumerate(questions_to_run, 1):
                q_text = q["text"]
                print(f"\n[{i}/{len(questions_to_run)}] Query: {q_text}")
                
                # If running no-memory, clear session before EVERY question
                if current_mode == "no_memory":
                    clear_session(client, server_url)
                
                out.write(f"Q{i}: {q_text}\n")
                out.write("A: ")
                
                print("Response: ", end="", flush=True)
                call_start = datetime.now(timezone.utc)
                answer = query_chat(client, server_url, q_text)

                out.write(f"{answer}\n")
                out.write("-" * 50 + "\n\n")
                
                # Fetch generated SQL query (+ loop count) from MongoDB
                sql, rewritten, retry_count = get_latest_sql_query(mongo_db, qdrant_log_client, since=call_start)
                if not sql:
                    sql = "N/A (No SQL generated)"

                print(f"Generated SQL: {sql}")
                if retry_count is not None:
                    print(f"🔄 Graph execution loop count: {retry_count}")

                q_out.write(f"Question: {q_text}\n")
                if rewritten and rewritten.lower() != q_text.lower():
                    q_out.write(f"Rewritten: {rewritten}\n")
                q_out.write(f"Query: {sql}\n")
                if retry_count is not None:
                    q_out.write(f"🔄 Graph execution loop count: {retry_count}\n")
                q_out.write("-" * 50 + "\n\n")
                q_out.flush()
                
                # Small pause to avoid overloading system
                time.sleep(0.5)
                
        print(f"\n💾 Saved responses to: {output_file}")
        print(f"💾 Saved SQL queries to: {queries_file}")
        
    client.close()
    print("\n🎉 Test execution completed successfully!")

def main():
    parser = argparse.ArgumentParser(description="Automate querying the Police Intel search/chat backend.")
    parser.add_argument("--url", default=DEFAULT_SERVER_URL, help="Base URL of the FastAPI server")
    parser.add_argument("--file", default=QUESTIONS_FILE, help="Path to questions file")
    parser.add_argument("--mode", choices=["memory", "no_memory", "both"], help="Run mode (memory, no_memory, both)")
    parser.add_argument("--indices", help="Comma-separated question numbers or ranges (e.g. 1,2,5-8)")
    
    args = parser.parse_args()
    
    questions = load_questions(args.file)
    if not questions:
        sys.exit(1)
        
    print(f"📚 Loaded {len(questions)} questions from '{args.file}'.")

    # Determine mode (CLI argument or interactive prompt)
    mode = args.mode
    if not mode:
        print("\nSelect execution mode:")
        print("  1. Memory-based (Session preserved across questions - context builds up)")
        print("  2. Without memory (Session cleared before each question - stateless)")
        print("  3. Both (Run both modes sequentially and generate comparison outputs)")
        while True:
            choice = input("Enter choice (1/2/3): ").strip()
            if choice == "1":
                mode = "memory"
                break
            elif choice == "2":
                mode = "no_memory"
                break
            elif choice == "3":
                mode = "both"
                break
            else:
                print("Invalid choice. Please enter 1, 2, or 3.")

    # Determine subset of questions to run (CLI argument or interactive prompt)
    selected_questions = []
    if args.indices:
        # Parse indices like "1,2,5-8"
        try:
            parts = args.indices.split(",")
            indices = []
            for part in parts:
                if "-" in part:
                    start, end = part.split("-")
                    indices.extend(range(int(start), int(end) + 1))
                else:
                    indices.append(int(part))
            
            for idx in indices:
                if 1 <= idx <= len(questions):
                    selected_questions.append(questions[idx - 1])
                else:
                    print(f"Warning: Index {idx} is out of bounds (1 to {len(questions)}). Skipping.")
        except Exception as e:
            print(f"Error parsing indices: {e}")
            sys.exit(1)
    else:
        print("\nSelect questions to execute:")
        print(f"  1. Run all {len(questions)} questions")
        print("  2. Run a specific range (e.g. 1-5)")
        print("  3. Run specific numbers (e.g. 1,3,15)")
        print("  4. Filter questions by search term")
        
        while True:
            choice = input("Enter choice (1/2/3/4): ").strip()
            if choice == "1":
                selected_questions = questions
                break
            elif choice == "2":
                rng = input(f"Enter range (1-{len(questions)}): ").strip()
                try:
                    start, end = rng.split("-")
                    selected_questions = questions[int(start)-1:int(end)]
                    break
                except:
                    print("Invalid range format. Use e.g. '1-5'.")
            elif choice == "3":
                nums = input("Enter comma-separated numbers (e.g. 1,3,15): ").strip()
                try:
                    indices = [int(n.strip()) for n in nums.split(",")]
                    for idx in indices:
                        if 1 <= idx <= len(questions):
                            selected_questions.append(questions[idx - 1])
                    break
                except:
                    print("Invalid format. Use comma separated integers.")
            elif choice == "4":
                term = input("Enter search term: ").strip().lower()
                selected_questions = [q for q in questions if term in q["text"].lower()]
                print(f"Matched {len(selected_questions)} questions.")
                if selected_questions:
                    break
                else:
                    print("No matches. Select again.")
            else:
                print("Invalid choice. Please enter 1, 2, 3, or 4.")
                
    if not selected_questions:
        print("No questions selected. Exiting.")
        sys.exit(0)

    # Run the tests!
    run_tests(selected_questions, mode, args.url)

if __name__ == "__main__":
    main()
