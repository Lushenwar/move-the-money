"""Empty both tables for a clean demo. Usage: python reset_db.py --yes"""
import os
import sys

import psycopg
from psycopg.conninfo import conninfo_to_dict

url = os.environ["DATABASE_URL"]
info = conninfo_to_dict(url)
target = f"database '{info.get('dbname')}' on {info.get('host', 'localhost')}"  # never the password

if "--yes" not in sys.argv:
    sys.exit(f"This deletes ALL accounts and transfers in {target}.\nRe-run with --yes to confirm.")

with psycopg.connect(url) as conn:
    # One statement for both tables (transfers references accounts).
    # TRUNCATE, not DELETE: it takes an exclusive lock, so it waits for in-flight transfers
    # instead of deleting a row between a replay's INSERT and its SELECT.
    # RESTART IDENTITY: demo accounts start at id 1.
    conn.execute("TRUNCATE transfers, accounts RESTART IDENTITY")

print(f"Reset {target}. The next account gets id 1.")
