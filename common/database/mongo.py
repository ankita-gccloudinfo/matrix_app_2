import os
import motor.motor_asyncio

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
# Overridable via project_config (see common/project_config.py) so separate
# projects (e.g. river_cannel) can point at their own database instead of
# sharing police_intel_db with the others.
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "police_intel_db")
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client[MONGO_DB_NAME]
sessions_collection = db.past_sessions
users_collection = db.users
query_log_collection = db.query_log

def get_sessions_collection():
    return sessions_collection

def get_users_collection():
    return users_collection

def get_query_log_collection():
    return query_log_collection

def get_groups_collection():
    return db.groups

def get_tts_config_collection():
    return db.tts_config
