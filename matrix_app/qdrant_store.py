from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

import config

_client = None

VECTOR_SIZE = 1024  # intfloat/multilingual-e5-large output dim


def get_client():
    global _client
    if _client is None:
        _client = QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT, timeout=60.0)
    return _client


def ensure_collection(name):
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def ensure_indexes(name, fields):
    """fields: dict of payload_field -> PayloadSchemaType"""
    client = get_client()
    for field, schema in fields.items():
        try:
            client.create_payload_index(name, field_name=field, field_schema=schema)
        except Exception:
            pass  # index already exists


def upsert(name, points):
    get_client().upsert(collection_name=name, points=points)
