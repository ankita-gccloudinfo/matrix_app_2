import os
from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST = os.environ["MYSQL_HOST"]
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ["MYSQL_USER"]
MYSQL_PASSWORD = os.environ["MYSQL_PASSWORD"]
MYSQL_DB = os.environ["MYSQL_DB"]

QDRANT_HOST = os.environ.get("QDRANT_HOST", "10.242.24.35")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "YourStrongPassword")


# Separate local Qdrant instance for ollamaagent2.py's topic_vector_v10 /
# topic_titles_v1 collections — QDRANT_HOST/PORT above stay pointed at the
# remote box that only content_index lives on.
QDRANT_TOPIC_HOST = os.environ.get("QDRANT_TOPIC_HOST", "localhost")
QDRANT_TOPIC_PORT = int(os.environ.get("QDRANT_TOPIC_PORT", "6333"))

# Yet another, separate local Qdrant instance — used only as the execution-log
# store for ollamaagent2.py's sql_history/qdrant_history entries (replaces the
# old MongoDB collections of the same names). Deliberately independent of
# QDRANT_TOPIC_HOST/PORT above so pointing that one at a remote box (as it
# currently is) doesn't also move the log store off localhost.
QDRANT_LOG_HOST = os.environ.get("QDRANT_LOG_HOST", "localhost")
QDRANT_LOG_PORT = int(os.environ.get("QDRANT_LOG_PORT", "6333"))

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "jinaai/jina-embeddings-v3")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "256"))
EMBED_BATCH_SIZE = int(os.environ.get("EMBED_BATCH_SIZE", "0"))  # 0 = auto (128)

# vLLM-hosted embeddings server (OpenAI-compatible /v1/embeddings route) —
# replaces the old locally-loaded SentenceTransformer.
EMBED_API_URL = os.environ.get("EMBED_API_URL", "http://10.242.24.35:2225/v1/embeddings")

CHECKPOINT_DIR = os.environ.get("CHECKPOINT_DIR", "checkpoints")
