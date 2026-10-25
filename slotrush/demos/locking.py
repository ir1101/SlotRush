"""Demo 2, 'locking': the same 80-bot race, but through register(), which takes
the offering row with SELECT ... FOR UPDATE. Exactly 30 get in.

Each bot holds its transaction open for the same 50 ms "think time" as the
naive path (after register() returns), so the queue of waiting sessions lasts
long enough to see. A monitor thread samples pg_locks joined with
pg_stat_activity every 20 ms and records who is waiting on whom.
"""
import csv
import threading
import time
from collections import Counter

from .. import charts
from ..config import RESULTS_DIR
from ..db import pg_connect
from . import common

BOTS = 80
CAPACITY = 30
SAMPLE_EVERY = 0.02          # seconds between monitor samples

# Every lock request that is NOT granted, the session that made it, and (through
# pg_blocking_pids) every session it is waiting for.
MONITOR_SQL = """
    SELECT waiting.pid                      AS waiting_pid,
           waiting_act.application_name     AS waiting_bot,
           waiting.locktype,
           waiting.mode,
           blocker.pid                      AS blocking_pid,
           blocker_act.application_name     AS blocking_bot,
           blocker_act.state                AS blocking_state
    FROM pg_locks waiting
    JOIN pg_stat_activity waiting_act ON waiting_act.pid = waiting.pid
    CROSS JOIN LATERAL unnest(pg_blocking_pids(waiting.pid)) AS blocker(pid)
    JOIN pg_stat_activity blocker_act ON blocker_act.pid = blocker.pid
    WHERE NOT waiting.granted
      AND waiting_act.application_name LIKE 'locking-%%'
    ORDER BY waiting_bot, blocking_bot
"""


def monitor(stop: threading.Event, samples: list) -> None:
    """Sample the lock table until told to stop. samples gets (seconds, rows)."""
    with pg_connect(autocommit=True, application_name="lock-monitor") as conn:
        start = time.perf_counter()
        while not stop.is_set():
            rows = conn.execute(MONITOR_SQL).fetchall()
            samples.append((time.perf_counter() - start, rows))
            time.sleep(SAMPLE_EVERY)


def run() -> int:
    with pg_connect() as conn:
        common.reset(conn)
        offering_id = common.make_offering(conn, "T01", CAPACITY)
        bots = common.make_bots(conn, BOTS)

    def work(i, conn):
        conn.execute("BEGIN")
        status = conn.execute("SELECT register(%s, %s)", (bots[i], offering_id)).fetchone()[0]
        time.sleep(0.05)              # think time, now while HOLDING the row lock
        conn.execute("COMMIT")
        return status

    stop, samples = threading.Event(), []
    watcher = threading.Thread(target=monitor, args=(stop, samples))
    watcher.start()
    results, seconds = common.run_bots(BOTS, work, "locking")
    stop.set()
    watcher.join()

    statuses = Counter(r if isinstance(r, str) else "ERROR" for r in results)
    capacity, seats_left, admitted = common.offering_state(offering_id)
    with pg_connect() as conn:
        waitlisted = conn.execute("SELECT count(*) FROM waitlist WHERE offering_id = %s",
                                  (offering_id,)).fetchone()[0]

    # The busiest sample is the snapshot we keep.
    busiest_t, busiest = max(samples, key=lambda s: len(s[1]), default=(0, []))
    waiting_sessions = len({row[0] for row in busiest})
    snapshot = RESULTS_DIR / "demo_locking_snapshot.csv"
    with snapshot.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sampled_at_s", "waiting_pid", "waiting_bot", "locktype", "mode",
                         "blocking_pid", "blocking_bot", "blocking_state"])
        for row in busiest:
            writer.writerow([f"{busiest_t:.3f}", *row])
    # pg_blocking_pids lists the lock HOLDER and also every session queued ahead
    # of the waiter, so one waiter can have many rows. Count each waiter once.
    waits = {(row[1], row[2], row[3]) for row in busiest}      # (waiting bot, locktype, mode)
    locktypes = Counter((locktype, mode) for _, locktype, mode in sorted(waits))
    waiting_pids = {row[0] for row in busiest}
    holders = sorted({row[5] for row in busiest if row[4] not in waiting_pids})

    print(f"Row locking with register(): {BOTS} bots, {capacity} seats.")
    print(f"  OK (admitted):          {statuses['OK']}   (registrations in table: {admitted})")
    print(f"  FULL (waitlisted):      {statuses['FULL']}   (waitlist rows: {waitlisted})")
    if statuses["ERROR"]:
        print(f"  Errors:                 {statuses['ERROR']}")
    print(f"  seats_left at the end:  {seats_left}")
    print(f"  Total time:             {seconds:.2f} s  (the bots now queue one after another)")
    print(f"  Busiest monitor sample: {waiting_sessions} sessions waiting at t = {busiest_t:.2f} s")
    print(f"      lock holder (not waiting itself): {', '.join(holders) or 'none'}")
    for (locktype, mode), n in locktypes.most_common():
        print(f"      {n:>3} session(s) waiting on a {locktype} lock ({mode})")
    print("  The 'transactionid' waiter is first in line: it waits for the holder's")
    print("  transaction to end. The 'tuple' waiters are the rest of the queue behind it.")
    print(f"  Snapshot saved to results/{snapshot.name}")

    common.save_run("locking", capacity=capacity, bots=BOTS, admitted=admitted,
                    seats_left=seats_left, seconds=round(seconds, 3), retries=0,
                    max_waiting=waiting_sessions)

    fig, (left, right) = charts.figure(ncols=2, width=11, height=4)
    times = [t for t, _ in samples]
    waiting = [len({row[0] for row in rows}) for _, rows in samples]
    left.plot(times, waiting, color=charts.PRIMARY)
    left.set_title("Sessions waiting for a lock (pg_locks)")
    left.set_xlabel("seconds since the monitor started")
    left.set_ylabel("waiting sessions")
    bars = right.bar(["capacity", "OK\n(admitted)", "FULL\n(waitlisted)"],
                     [capacity, statuses["OK"], statuses["FULL"]], width=0.5,
                     color=[charts.SECONDARY, charts.PRIMARY, charts.TERTIARY])
    charts.label_bars(right, bars)
    right.set_title("register() with FOR UPDATE: exactly capacity")
    right.set_ylabel("students / seats")
    right.set_ylim(0, max(statuses["FULL"], capacity) * 1.15)
    print(f"Chart: {charts.save(fig, 'demo_locking.png')}")
    return 0 if admitted == capacity else 1
