CREATE TABLE IF NOT EXISTS accounts (
    id             BIGSERIAL PRIMARY KEY,
    balance_cents  BIGINT NOT NULL CHECK (balance_cents >= 0),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS transfers (
    id               BIGSERIAL PRIMARY KEY,
    idempotency_key  TEXT NOT NULL UNIQUE,
    from_account_id  BIGINT NOT NULL REFERENCES accounts(id),
    to_account_id    BIGINT NOT NULL REFERENCES accounts(id),
    amount_cents     BIGINT NOT NULL CHECK (amount_cents > 0),
    -- clock_timestamp(), not now(): now() is when the transaction started, which can be
    -- before it waited on an account lock. This records when the row was actually written.
    created_at       TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (from_account_id <> to_account_id)
);
