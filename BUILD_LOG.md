# Build log

<!--
HOW TO USE THIS SKELETON
- Fill in each section in your own words. Delete all of these hidden comment blocks when you're done.
- Target: about one page (~400–600 words total). Rough word budgets are next to each heading.
- Use real numbers and commit hashes. Say who caught each thing:
  "Claude self-corrected", "the reviewer agent flagged", "a second AI session I used for review suggested", "I noticed".
- Source material: NOTES.md (live log, reviewer findings) and `git log`.
-->

**Time:** <!-- start → finish, total (e.g. 13:28 → 15:30, about 2h) -->

## What I set out to do

My goal was to build a simple banking system that was able to open an account with some money, transfer money, show an accounts balance and list past transfers
I treated the four rules as the real assignment and let the database enforce them (row locks, constraints and one transaction per transfer) instead of checking them in python
I also held my tests to one standard: I only trusted a test after seeing it fail against actual broken code

## How I used AI
Claude Code wrote most of the code. I reviewed every step, and read the money-handling code (transfers and idempotency) before it was committed.
Before starting, I wrote a guideline (CLAUDE.md) that gave the agent the rules and the safe patterns up front.
I created a separate read-only reviewer agent (money-reviewer.md) that checked the code at three checkpoints, and I used a separate Claude chat as a second opinion.
My rule: if an AI claimed something, it only counted once a test proved it.
Because the safe patterns were written down up front, the core transfer logic was right almost immediately, and the mistakes showed up elsewhere.

## Where it was confidently wrong

### 1. a smoke check that proved nothing
To make sure the rule-1 concurrency test could actually fail, I swapped in broken versions of the transfer code. the obvious one (just removing `FOR UPDATE`) still passed 3/3 — the conditional `UPDATE` and the `CHECK` constraint were still protecting the balance, so the test never saw a problem. a second AI chat predicted this, and Claude Code ran both versions. the only version that actually broke was reading the balance into Python and writing back a computed number: 18–19 transfers went through instead of 10, so money got created out of nothing. that's why the test checks the exact success count and the total money, not just "nobody went negative". (8c08029)

### 2. idempotency key claimed in the wrong place
the original plan claimed the key last, after the debit. it never double-charged anyone, but if you retried a transfer that had emptied the account, you got "insufficient funds" (422) for a payment that actually went through. a separate AI review caught it. I wrote the test first and it failed with 422 before the fix. fix was: lock → claim key → move money. then a smoke check showed why the order matters so much: with `ON CONFLICT DO NOTHING` after the debit, money moved twice (400 == 700). (29d4756, 4ece30b)

### 3. the deadlock test almost proved nothing too
removing `ORDER BY id` from the lock didn't cause a deadlock at all, because Postgres was already reading the rows in id order. locking sender-then-receiver did: `DeadlockDetected` 3/3, and runs took 7–28 seconds. postgres kills one of the transactions so no money's lost, but transfers would just randomly fail under load. (074ebfa)

## What I rejected, and why
- **ordering history by `created_at`** (from a second AI chat): wrote a test where a transfer starts first but moves money last. it failed with that ordering, since `now()` is when the transaction *started*. kept `ORDER BY id`. (a614082)
- **"cold connection pool makes the concurrency test weak"** (reviewer agent): ran it 80 times against broken code, it caught the bug 80/80. so I didn't change anything.
- **the reviewer's fix for a test leaving behind a 1-cent row that never moved money**: it was right about the bug but wrong about the fix (`rollback()` would've broken the test), so I fixed it a different way. (6414219)

## Where AI genuinely helped
- boilerplate (FastAPI app, connection pool, test fixtures) took minutes instead of an hour
- it ran all the smoke checks and the 80 repeated runs fast — doing that by hand would've eaten the whole time budget
- the reviewer found two real test gaps: a duplicate waiting on a key that then rolls back, and the 1-cent leftover row
- Claude noticed `pip freeze >` in PowerShell had saved `requirements.txt` as UTF-16, which would've broken installs for anyone else

## What I shipped that I'm not comfortable with
- crediting an account past the BIGINT max gives a 500 instead of a clean error. there's a test proving it rolls back though, so no money's lost
- tests and the demo share one database, and tests leave data behind
- the concurrency tests call the service directly, not through HTTP
- history isn't paginated, and there's a Starlette deprecation warning I didn't fix

## What I'd do with a fifth hour
- Double-entry ledger + a reconciliation check that balances actually match the ledger
- Separate test database
- Load test through the real HTTP server

## What I'd do differently
Write the failing test *before* each money change from the very start. I only really did that consistently from the idempotency part onward, and that's where it caught the most.