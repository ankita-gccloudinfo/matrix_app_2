from contextlib import contextmanager

import mysql.connector

import config


@contextmanager
def get_connection():
    conn = mysql.connector.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DB,
        connection_timeout=10,
    )
    try:
        yield conn
    finally:
        conn.close()


def fetch_batches(table, columns, id_column="id", after_id=0, batch_size=None, where=None, limit=None):
    """Keyset-paginated fetch ordered by id_column, resumable from after_id.

    Uses WHERE id > last_id instead of OFFSET so it stays fast on multi-million-row tables.
    `limit`, if set, caps the total number of rows yielded across all batches (for quick test runs).
    """
    batch_size = batch_size or config.BATCH_SIZE
    col_list = ", ".join(f"`{c}`" for c in columns)
    where_clause = f"AND {where}" if where else ""
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        last_id = after_id
        yielded = 0
        while True:
            fetch_size = batch_size if limit is None else min(batch_size, limit - yielded)
            if fetch_size <= 0:
                break
            query = (
                f"SELECT {col_list} FROM `{table}` "
                f"WHERE `{id_column}` > %s {where_clause} "
                f"ORDER BY `{id_column}` ASC LIMIT %s"
            )
            cursor.execute(query, (last_id, fetch_size))
            rows = cursor.fetchall()
            if not rows:
                break
            yield rows
            last_id = rows[-1][id_column]
            yielded += len(rows)
        cursor.close()
