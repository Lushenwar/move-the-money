import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import service
from conftest import balance, new_account


def test_concurrent_transfers_never_overdraw():
    # Rule 1: 50 transfers of 1000 compete for 10000. Exactly 10 can fit.
    a, b = new_account(10000), new_account(0)
    threads = 50
    barrier = threading.Barrier(threads, timeout=10)

    def attempt(_):
        barrier.wait()  # release all threads at the same instant
        try:
            # each call checks out its own pooled connection (pool max_size=20)
            service.do_transfer(str(uuid4()), a, b, 1000)
            return "ok"
        except service.InsufficientFunds:
            return "insufficient"
        # any other exception (deadlock, CHECK violation) propagates and fails the test

    with ThreadPoolExecutor(max_workers=threads) as pool:
        results = list(pool.map(attempt, range(threads)))

    # Assert invariants, not just "no exception". Balance >= 0 alone would pass even
    # against broken code (the CHECK constraint guarantees it); the success count and
    # the total are what catch a lost update.
    assert results.count("ok") == 10
    assert results.count("insufficient") == 40
    assert balance(a) == 0
    assert balance(a) + balance(b) == 10000


def test_opposite_direction_transfers_no_deadlock_and_conserve_money():
    # 20 threads send A->B while 20 send B->A, all at once. With locks taken in id order
    # this can't deadlock; a deadlock (psycopg.errors.DeadlockDetected) fails the test.
    # 20 x 700 = 14000 > 10000, so some transfers may hit insufficient funds.
    a, b = new_account(10000), new_account(10000)
    threads, amount = 40, 700
    barrier = threading.Barrier(threads, timeout=10)

    def attempt(i):
        src, dst = (a, b) if i % 2 == 0 else (b, a)
        barrier.wait()
        try:
            service.do_transfer(str(uuid4()), src, dst, amount)
            return (src, "ok")
        except service.InsufficientFunds:
            return (src, "insufficient")

    with ThreadPoolExecutor(max_workers=threads) as pool:
        results = list(pool.map(attempt, range(threads)))

    a_sent = results.count((a, "ok"))
    b_sent = results.count((b, "ok"))
    assert balance(a) + balance(b) == 20000
    assert balance(a) == 10000 - a_sent * amount + b_sent * amount
    assert balance(b) == 10000 - b_sent * amount + a_sent * amount
