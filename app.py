from typing import Annotated

from fastapi import FastAPI, Path, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

import db
import service

db.apply_schema()  # idempotent (CREATE TABLE IF NOT EXISTS), runs once at startup

app = FastAPI(title="Move the Money")

BIGINT_MAX = 2**63 - 1  # Postgres BIGINT; larger values would be a DB error (500)


class AccountIn(BaseModel):
    # strict: rejects 10.5, "1000" and true instead of coercing them
    initial_balance_cents: int = Field(strict=True, ge=0, le=BIGINT_MAX)


class TransferIn(BaseModel):
    idempotency_key: str = Field(strict=True, min_length=1, max_length=255)
    from_account_id: int = Field(strict=True, ge=1, le=BIGINT_MAX)
    to_account_id: int = Field(strict=True, ge=1, le=BIGINT_MAX)
    amount_cents: int = Field(strict=True, ge=1, le=BIGINT_MAX)

    @model_validator(mode="after")
    def different_accounts(self):
        if self.from_account_id == self.to_account_id:
            raise ValueError("from_account_id and to_account_id must differ")
        return self


AccountId = Annotated[int, Path(ge=1, le=BIGINT_MAX)]


@app.exception_handler(service.AccountNotFound)
def account_not_found(request, exc):
    return JSONResponse(status_code=404, content={"error": "account_not_found"})


@app.exception_handler(service.InsufficientFunds)
def insufficient_funds(request, exc):
    return JSONResponse(status_code=422, content={"error": "insufficient_funds"})


@app.exception_handler(service.IdempotencyConflict)
def idempotency_conflict(request, exc):
    return JSONResponse(status_code=409, content={"error": "idempotency_key_conflict"})


@app.post("/accounts", status_code=201)
def create_account(body: AccountIn):
    return service.create_account(body.initial_balance_cents)


@app.get("/accounts/{account_id}")
def get_account(account_id: AccountId):
    return service.get_account(account_id)


@app.post("/transfers", status_code=201)
def create_transfer(body: TransferIn, response: Response):
    transfer, created = service.do_transfer(
        body.idempotency_key, body.from_account_id, body.to_account_id, body.amount_cents
    )
    if not created:
        response.status_code = 200  # replay of an already-applied key
    return transfer


@app.get("/accounts/{account_id}/transfers")
def get_history(account_id: AccountId):
    return service.get_history(account_id)  # ponytail: unbounded list, paginate if histories grow
