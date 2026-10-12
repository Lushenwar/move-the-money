from typing import Annotated

from fastapi import FastAPI, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import db
import service

db.apply_schema()  # idempotent (CREATE TABLE IF NOT EXISTS), runs once at startup

app = FastAPI(title="Move the Money")

BIGINT_MAX = 2**63 - 1  # Postgres BIGINT; larger values would be a DB error (500)


class AccountIn(BaseModel):
    # strict: rejects 10.5, "1000" and true instead of coercing them
    initial_balance_cents: int = Field(strict=True, ge=0, le=BIGINT_MAX)


AccountId = Annotated[int, Path(ge=1, le=BIGINT_MAX)]


@app.exception_handler(service.AccountNotFound)
def account_not_found(request, exc):
    return JSONResponse(status_code=404, content={"error": "account_not_found"})


@app.post("/accounts", status_code=201)
def create_account(body: AccountIn):
    return service.create_account(body.initial_balance_cents)


@app.get("/accounts/{account_id}")
def get_account(account_id: AccountId):
    return service.get_account(account_id)
