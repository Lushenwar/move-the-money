import os
from pathlib import Path

from psycopg_pool import ConnectionPool

# max_size 20 so concurrency tests get many connections running at once.
pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=20, open=True)


def apply_schema():
    sql = (Path(__file__).parent / "schema.sql").read_text()
    with pool.connection() as conn:
        conn.execute(sql)
