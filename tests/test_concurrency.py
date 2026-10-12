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
