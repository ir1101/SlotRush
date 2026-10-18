"""Demo 3, 'serializable': the naive read-think-write path again, now at
SERIALIZABLE. PostgreSQL detects that two transactions read the same
seats_left and both try to write it, and aborts the later writer with
SQLSTATE 40001 ("could not serialize access"). The bot rolls back, waits a
small random time and retries, up to MAX_RETRIES times.

Then one chart compares all three runs: lost-update, locking, serializable.
"""
import random
import time
from collections import Counter

import psycopg

from .. import charts
from ..config import SEED
from ..db import pg_connect
from . import common

BOTS = 80
CAPACITY = 30
MAX_RETRIES = 100                 # high enough that nobody gives up while seats remain
BACKOFF_SECONDS = (0.005, 0.05)   # random pause before each retry


def run() -> int:
    with pg_connect() as conn:
        common.reset(conn)
        offering_id = common.make_offering(conn, "T01", CAPACITY)
        bots = common.make_bots(conn, BOTS)

    def work(i, conn):
        rng = random.Random(SEED + i)         # each bot has its own seeded backoff
        retries = 0
        while True:
            try:
                status, _ = common.naive_register(conn, bots[i], offering_id, "SERIALIZABLE")
                return status, retries
            except psycopg.errors.SerializationFailure:       # SQLSTATE 40001
                conn.execute("ROLLBACK")
                if retries == MAX_RETRIES:
                    return "GAVE_UP", retries
                retries += 1
                time.sleep(rng.uniform(*BACKOFF_SECONDS))

    results, seconds = common.run_bots(BOTS, work, "serializable")
    ok_results = [r for r in results if isinstance(r, tuple)]
    statuses = Counter(r[0] for r in ok_results)
    retries = [r[1] for r in ok_results]
    errors = [r for r in results if isinstance(r, Exception)]
    capacity, seats_left, admitted = common.offering_state(offering_id)

    print(f"Naive path at SERIALIZABLE: {BOTS} bots, {capacity} seats, retry on SQLSTATE 40001.")
    print(f"  Students admitted:      {admitted}  (capacity {capacity})")
    print(f"  Turned away (FULL):     {statuses['FULL']}")
    print(f"  Gave up after {MAX_RETRIES} retries: {statuses['GAVE_UP']}")
    print(f"  seats_left at the end:  {seats_left}")
    print(f"  Serialization failures: {sum(retries)} in total, at most {max(retries)} for one bot")
    print(f"  Total time:             {seconds:.2f} s")
    if errors:
        print(f"  Other errors: {len(errors)} (first: {errors[0]})")
    print("The same buggy code is now correct: SERIALIZABLE turns each lost update into an")
    print("error the application must retry. Correct, but every retry repeats the whole")
    print("transaction, including its 50 ms think time.")
    print("Why it can still beat the locking demo on time: there, all 80 bots hold the row")
    print("lock through their 50 ms think time, one after another (pessimistic). Here nobody")
    print("holds a lock while thinking, and once seats_left reads 0 a bot leaves at once")
    print("(optimistic). The price is the wasted work in the retry count.")

    common.save_run("serializable", capacity=capacity, bots=BOTS, admitted=admitted,
                    seats_left=seats_left, seconds=round(seconds, 3), retries=sum(retries),
                    max_retries_one_bot=max(retries), gave_up=statuses["GAVE_UP"])
    comparison_chart()
    return 0 if admitted == capacity else 1


def comparison_chart() -> None:
    """One chart comparing the three runs on admitted vs capacity, time and retries."""
    names = ["lost-update", "locking", "serializable"]
    runs = [common.load_run(n) for n in names]
    missing = [n for n, r in zip(names, runs) if r is None]
    if missing:
        print(f"Comparison chart skipped: run {', '.join(missing)} first.")
        return
    labels = ["naive,\nREAD COMMITTED", "register()\nFOR UPDATE", "naive,\nSERIALIZABLE"]
    colours = charts.SERIES[:3]            # one fixed colour per run, the same in every panel

    fig, axes = charts.figure(ncols=3, width=13, height=4.2)
    capacity = runs[0]["capacity"]
    panels = [
        (f"Students admitted (line = capacity {capacity})", "students",
         [r["admitted"] for r in runs], "{:g}"),
        ("Total time", "seconds", [r["seconds"] for r in runs], "{:.2f}"),
        ("Retries after SQLSTATE 40001", "retries", [r["retries"] for r in runs], "{:g}"),
    ]
    for ax, (title, ylabel, values, fmt) in zip(axes, panels):
        bars = ax.bar(labels, values, width=0.5, color=colours)
        charts.label_bars(ax, bars, fmt)
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.set_ylim(0, max(max(values), 1) * 1.18)
        ax.tick_params(axis="x", labelsize=8.5)
    axes[0].axhline(capacity, color=charts.INK_2, linewidth=1)
    print(f"Chart: {charts.save(fig, 'demo_isolation_comparison.png')}")
