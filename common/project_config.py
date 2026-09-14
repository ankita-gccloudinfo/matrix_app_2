"""Loads per-project config (Qdrant host/collection, MySQL, LLM backend,
LiveAvatar, etc.) written by the admin_config service (port 8122, see
django/admin_config/) and injects it into os.environ, so it's picked up
transparently by every existing os.getenv(...)-based config in each app
(ollamaagent2.py, services/pdf_rag.py, config.py, ...) — no other code needs
to know project_config exists.

Call apply_project_config(PROJECT_ID) as the very first thing in each app's
server.py, before importing ollamaagent2 or services.pdf_rag — those modules
read their config at import time, so the override must land in os.environ
before that import happens.

Uses a plain synchronous pymongo client (not the async Motor client
common/database/mongo.py uses) since this runs once at process startup,
before the app's own event loop exists.
"""
import os

import pymongo

ADMIN_MONGO_URI = os.getenv("ADMIN_MONGO_URI", os.getenv("MONGO_URI", "mongodb://localhost:27017"))
ADMIN_DB_NAME = "project_admin"
PROJECT_CONFIG_COLLECTION = "project_config"


def apply_project_config(project_id: str) -> None:
    """Strictly requires the project to have a saved configuration in the
    admin_config database. If no configuration is found or the DB cannot
    be reached, the application will exit."""
    import sys
    try:
        client = pymongo.MongoClient(ADMIN_MONGO_URI, serverSelectionTimeoutMS=1500)
        doc = client[ADMIN_DB_NAME][PROJECT_CONFIG_COLLECTION].find_one({"_id": project_id})
        client.close()
    except Exception as e:
        print(f"❌ Could not reach admin config DB for project '{project_id}': {e}")
        print("The application requires admin_config DB to be accessible.")
        sys.exit(1)

    if not doc:
        print(f"❌ No project_config saved for '{project_id}'.")
        print("The application requires configuration via admin_config to run.")
        print("Please add the project in the admin_config dashboard (http://localhost:8122) first.")
        sys.exit(1)

    env_overrides = doc.get("env", {})
    applied = []
    for key, value in env_overrides.items():
        if value in (None, ""):
            continue
        os.environ[str(key)] = str(value)
        applied.append(key)

    if applied:
        print(f"✅ project_config: applied {len(applied)} override(s) for '{project_id}': {', '.join(applied)}")
