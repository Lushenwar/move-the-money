from fastapi import FastAPI

import db

db.apply_schema()  # idempotent (CREATE TABLE IF NOT EXISTS), runs once at startup

app = FastAPI(title="Move the Money")
