"""Demo 1, 'lost-update': 80 bots race for 30 seats through the naive path
at READ COMMITTED, and far more than 30 get in.

Why: every bot reads seats_left = 30 at almost the same moment, sleeps 50 ms,
and writes back 29. At READ COMMITTED an UPDATE waits for the row lock of an
earlier writer, but then simply applies its own (stale) value on top: the
earlier decrement is lost. Nothing ever sees 0, so nobody is turned away.
"""
import time

from .. import charts
from ..db import pg_connect
from . import common

BOTS = 80
CAPACITY = 30


def run() -> int:
    with pg_connect() as conn:
        common.reset(conn)
        offering_id = common.make_offering(conn, "T01", CAPACITY)
        bots = common.make_bots(conn, BOTS)

    commit_times = [None] * BOTS

    def work(i, conn):
        status, seats_read = common.naive_register(conn, bots[i], offering_id, "READ COMMITTED")
        commit_times[i] = time.perf_counter()
        return status, seats_read

    results, seconds = common.run_bots(BOTS, work, "lostupdate")
    errors = [r for r in results if isinstance(r, Exception)]
    capacity, seats_left, admitted = common.offering_state(offering_id)

    print(f"Lost update at READ COMMITTED: {BOTS} bots, {capacity} seats, naive read-think-write.")
    print(f"  Students admitted:      {admitted}  (capacity {capacity}: "
          f"{admitted - capacity} too many)")
    print(f"  seats_left at the end:  {seats_left}  (should be {max(capacity - admitted, 0)}; "
          f"{admitted - (capacity - seats_left)} decrements were lost)")
    print(f"  Total time:             {seconds:.2f} s")
    if errors:
        print(f"  Errors: {len(errors)} (first: {errors[0]})")
    print("Each bot read seats_left before any other bot had written, then wrote back its own")
    print("stale value minus one. The later write silently overwrote the earlier one.")

    common.save_run("lost-update", capacity=capacity, bots=BOTS, admitted=admitted,
                    seats_left=seats_left, seconds=round(seconds, 3), retries=0)

    # Chart: (a) admitted vs capacity, (b) the value each admitted bot read, in commit order.
    ok = sorted((commit_times[i], r[1]) for i, r in enumerate(results)
                if isinstance(r, tuple) and r[0] == "OK")
    fig, (left, right) = charts.figure(ncols=2, width=11, height=4)
    bars = left.bar(["capacity", "admitted", "seats_left\nat the end"],
                    [capacity, admitted, seats_left], width=0.5,
                    color=[charts.BLUE, charts.CRITICAL, charts.BLUE])
    charts.label_bars(left, bars)
    left.set_title("Naive path at READ COMMITTED: over-booked")
    left.set_ylabel("students / seats")
    left.set_ylim(0, max(admitted, capacity) * 1.15)

    order = range(1, len(ok) + 1)
    right.plot(order, [seats for _, seats in ok], color=charts.BLUE, marker="o", markersize=4,
               label="seats_left each bot read")
    right.plot(order, [max(capacity - n + 1, 0) for n in order], color=charts.ORANGE,
               label="what it should have read")
    right.set_title("Every bot read a stale seats_left")
    right.set_xlabel("admitted bots, in commit order")
    right.set_ylabel("seats_left")
    right.legend(loc="center right")
    print(f"Chart: {charts.save(fig, 'demo_lost_update.png')}")
    return 0 if admitted > capacity else 1
