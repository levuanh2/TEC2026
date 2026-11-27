"""RAG V1.5 M7 E5.2 retrieval-starvation benchmark (NOT part of the suite: run it explicitly).

    E5_2_BENCH_OUT=<file.json> pytest -q tests/bench_e5_2_retrieval.py

It builds a SYNTHETIC QA corpus in one rolled-back transaction on the local stack. N_STALE versions are approved in an
earlier pin generation and match the query better, and N_CLEAN versions are approved after the owner re-pinned.
It then compares, as the member (role authenticated, RLS):

* E5.1 : H-a retrieval top_k, then gate 1 (the answer sees what survives);
* A    : E5.2 admission-aware retrieval top_k (then gate 1, which admits everything it returns);
* B    : bounded refill over H-a retrieval: k = 8, 16, 32, 50 (the RPC cap), gate 1 after each round, stop at top_k.

It measures client-observed latency per request (median and p95 of ROUNDS) and the database round trips. Local,
single machine, synthetic text: numbers are relative, not a production estimate. TEST FIXTURE data only.
"""

from __future__ import annotations

import json
import os
import statistics
import time

from tests.test_rag_knowledge_m2_approval import m2  # noqa: F401
from tests.test_rag_knowledge_m7_e5_1_pin_admission import approve_now, real_pin
from tests.test_rag_knowledge_m7_e5_2_pin_generation import baseline_rpc, repin_same
from tests.test_rag_knowledge_m7_e5_answer_time import AWD_TEXT, STATE_PIN
from tests.test_rag_knowledge_storage import pytestmark, tx  # noqa: F401

__all__ = ["pytestmark", "tx", "m2"]

N_STALE = int(os.environ.get("E5_2_BENCH_STALE", "40"))
N_CLEAN = int(os.environ.get("E5_2_BENCH_CLEAN", "10"))
ROUNDS = int(os.environ.get("E5_2_BENCH_ROUNDS", "25"))
TOP_K = 8
QUERY = "tưới ngập khô xen kẽ mê-tan"
BASE = "select chunk_id from pg_temp.match_e5_1_baseline(%s, %s, %s)"
NEW = "select chunk_id from public.match_knowledge_chunks_lexical(%s, %s, %s)"


def timed(fn):
    started = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - started) * 1000


def test_bench_retrieval_starvation(tx, m2):
    real_pin(tx)
    stale, clean = set(), set()
    for i in range(N_STALE):
        _, c = approve_now(tx, m2, tx.source(), f"tưới ngập khô xen kẽ mê-tan tưới ngập khô xen kẽ lúa ruộng {i}",
                           doc_version="v1", document_id=f"bench-stale-{i}")
        stale.add(c)
    repin_same(tx)
    for i in range(N_CLEAN):
        _, c = approve_now(tx, m2, tx.source(), f"{AWD_TEXT} Ghi chú {i}.", doc_version="v1",
                           document_id=f"bench-clean-{i}")
        clean.add(c)
    baseline_rpc(tx)

    def rpc(sql, k):
        status, rows = tx.as_user(tx.member, sql, (tx.season_a, QUERY, k))
        assert status == "ok", rows
        return [r[0] for r in rows]

    def gate1(ids):
        if not ids:
            return []
        status, rows = tx.as_user(tx.member, STATE_PIN, (tx.season_a, ids, False))
        assert status == "ok", rows
        return [r[0]["chunk_id"] for r in rows if r[0]["integrity_status"] == "current"]

    def e51():
        ids = rpc(BASE, TOP_K)
        return gate1(ids), 2

    def option_a():
        ids = rpc(NEW, TOP_K)
        return gate1(ids), 2

    def option_b():
        trips, admitted = 0, []
        for k in (8, 16, 32, 50):
            ids = rpc(BASE, k)
            admitted = gate1(ids)
            trips += 2
            if len(admitted) >= TOP_K or len(ids) < k:
                break
        return admitted[:TOP_K], trips

    results = {}
    for name, fn in (("E5.1 (retrieve, then gate 1)", e51), ("A: admission-aware retrieval", option_a),
                     ("B: bounded refill (8/16/32/50)", option_b)):
        fn()                                                            # warm-up
        times, out = [], None
        for _ in range(ROUNDS):
            out, ms = timed(fn)
            times.append(ms)
        admitted, trips = out
        results[name] = {"admitted_clean": len(set(admitted) & clean), "admitted_stale": len(set(admitted) & stale),
                         "round_trips": trips, "median_ms": round(statistics.median(times), 2),
                         "p95_ms": round(sorted(times)[max(0, int(len(times) * 0.95) - 1)], 2)}
    # the RPC alone (no gate 1), to isolate the cost of the generation predicate
    for name, sql in (("rpc only: H-a", BASE), ("rpc only: E5.2", NEW)):
        times = [timed(lambda: rpc(sql, TOP_K))[1] for _ in range(ROUNDS)]
        results[name] = {"median_ms": round(statistics.median(times), 2)}
    report = {"n_stale": N_STALE, "n_clean": N_CLEAN, "rounds": ROUNDS, "top_k": TOP_K, "results": results}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if os.environ.get("E5_2_BENCH_OUT"):
        with open(os.environ["E5_2_BENCH_OUT"], "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    assert results["A: admission-aware retrieval"]["admitted_stale"] == 0
    assert results["A: admission-aware retrieval"]["admitted_clean"] == min(TOP_K, N_CLEAN)
    assert results["E5.1 (retrieve, then gate 1)"]["admitted_clean"] == 0 if N_STALE >= TOP_K else True
