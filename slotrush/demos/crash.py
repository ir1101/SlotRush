"""Demo 5, 'crash': kill PostgreSQL in the middle of 1,000 registrations and
show that every acknowledged commit survives (durability, through the WAL).

  1. Bot threads call register(); each appends a line to results/commit_log.csv
     ONLY AFTER its COMMIT has returned (the server acknowledged it).
  2. Part-way through, "docker kill" sends SIGKILL to the server: no clean
     shutdown, no checkpoint.
  3. The container is started again; PostgreSQL replays the WAL (crash
     recovery) before pg_isready reports it ready.
  4. Check (a): every logged commit is in the registration table.
     Check (b): for every offering, seats_left + registrations = capacity.

What this does and does not prove: docker kill kills the database PROCESSES,
not the machine, so data already handed to the operating system survives even
without fsync. The demo therefore proves WAL crash recovery and that COMMIT
waited for the WAL write (synchronous_commit = on). It cannot show what fsync
protects against: a power cut or a crash of the whole machine (or VM).
With --async-commit the bots use synchronous_commit = off, so a COMMIT can
return before its WAL record leaves PostgreSQL's memory, and check (a) may FAIL.
"""
import csv
import threading
import time
from datetime import datetime, timezone

import psycopg

from .. import charts, containers
from ..config import RESULTS_DIR
from ..db import pg_connect
from . import common

REGISTRATIONS = 1_000
THREADS = 8
OFFERINGS = 20
CAPACITY = 60                  # 20 x 60 = 1,200 seats for 1,000 registrations
KILL_AFTER = 300               # kill once this many commits are logged
THINK_SECONDS = 0.01           # small pause per registration so the kill lands mid-run


def output_names(async_commit: bool) -> tuple:
    """(commit log, recovery log, chart) file names; the async run gets its own set."""
    suffix = "_async" if async_commit else ""
    return (RESULTS_DIR / f"commit_log{suffix}.csv",
            f"demo_crash{suffix}_recovery_log.txt",
            f"demo_crash{suffix}.png")


def run(async_commit: bool = False) -> int:
    log_file, recovery_name, chart_name = output_names(async_commit)
    containers.require_docker()
    with pg_connect() as conn:
        common.reset(conn)
        theory_slots = [f"T{n:02d}" for n in range(1, 17)]
        offerings = [common.make_offering(conn, theory_slots[i % 16], CAPACITY)
                     for i in range(OFFERINGS)]
        bots = common.make_bots(conn, REGISTRATIONS)
    # Bot i registers for one offering; thread k takes every THREADS-th job.
    jobs = [(bots[i], offerings[i % OFFERINGS]) for i in range(REGISTRATIONS)]

    log_lock = threading.Lock()
    log_file.parent.mkdir(exist_ok=True)
    log = log_file.open("w", newline="", encoding="utf-8")
    writer = csv.writer(log)
    writer.writerow(["reg_no", "offering_id", "status", "acknowledged_at_s"])
    logged = [0]
    in_flight_failures = [0]
    start = time.perf_counter()

    def worker(k):
        try:
            conn = pg_connect(autocommit=True, application_name=f"crash-{k:02d}")
            if async_commit:
                conn.execute("SET synchronous_commit = off")
        except psycopg.OperationalError:
            return
        for reg_no, offering_id in jobs[k::THREADS]:
            try:
                conn.execute("BEGIN")
                status = conn.execute("SELECT register(%s, %s)",
                                      (reg_no, offering_id)).fetchone()[0]
                conn.execute("COMMIT")
            except psycopg.OperationalError:
                # The server died while this request was in flight. We do not know
                # whether its COMMIT reached the WAL, so it is NOT logged.
                with log_lock:
                    in_flight_failures[0] += 1
                return
            with log_lock:                     # COMMIT returned: now (and only now) log it
                writer.writerow([reg_no, offering_id, status,
                                 f"{time.perf_counter() - start:.3f}"])
                log.flush()
                logged[0] += 1
            time.sleep(THINK_SECONDS)
        conn.close()

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(THREADS)]
    for t in threads:
        t.start()

    while logged[0] < KILL_AFTER and any(t.is_alive() for t in threads):
        time.sleep(0.005)
    kill_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    kill_at = time.perf_counter() - start
    print(f"{logged[0]} commits acknowledged; killing {containers.PG_CONTAINER} (SIGKILL) ...")
    containers.kill_postgres()
    for t in threads:
        t.join()
    log.close()
    print(f"Server killed at {kill_at:.2f} s. Acknowledged and logged: {logged[0]}. "
          f"Requests cut off in flight: {in_flight_failures[0]}.")

    print("Starting it again and waiting for pg_isready ...")
    waited = containers.start_postgres_and_wait()
    print(f"Ready after {waited:.1f} s (crash recovery replayed the WAL first).")

    return verify(offerings, kill_utc, kill_at, async_commit,
                  log_file, recovery_name, chart_name)


def verify(offerings, kill_utc, kill_at, async_commit,
           log_file, recovery_name, chart_name) -> int:
    with log_file.open(newline="", encoding="utf-8") as f:
        logged = {(row["reg_no"], int(row["offering_id"])) for row in csv.DictReader(f)}
    with pg_connect() as conn:
        in_table = set(conn.execute(
            "SELECT reg_no, offering_id FROM registration WHERE offering_id = ANY(%s)",
            (offerings,)).fetchall())
        bad_offerings = conn.execute("""
            SELECT count(*) FROM offering o
            WHERE o.seats_left + (SELECT count(*) FROM registration r
                                  WHERE r.offering_id = o.offering_id) <> o.capacity
        """).fetchone()[0]
        total_offerings = conn.execute("SELECT count(*) FROM offering").fetchone()[0]

    missing = logged - in_table            # acknowledged but lost: must be zero
    unlogged = in_table - logged           # committed, but the acknowledgement was lost
    check_a = not missing
    check_b = bad_offerings == 0
    common.save_run("crash-async" if async_commit else "crash", logged=len(logged),
                    found=len(in_table), missing=len(missing), unlogged=len(unlogged),
                    check_a=check_a, check_b=check_b, seconds=round(kill_at, 3))

    lines = [
        f"Crash demo ({'synchronous_commit = off' if async_commit else 'default settings'})",
        f"  Logged (acknowledged) commits:            {len(logged)}",
        f"  Demo registrations found after restart:   {len(in_table)}",
        f"  Logged but missing from the table:        {len(missing)}",
        f"  In the table but not in the log:          {len(unlogged)}",
        "",
        f"[{'PASS' if check_a else 'FAIL'}] (a) every logged commit exists in registration",
        f"[{'PASS' if check_b else 'FAIL'}] (b) seats_left + registrations = capacity for all "
        f"{total_offerings:,} offerings ({bad_offerings} out of line)",
        "",
        "Rows in the table but not in the log are expected. Those transactions committed",
        "on the server (their WAL record was written), but the server died before the",
        "acknowledgement reached the bot, so the bot never logged them.",
    ]
    if async_commit and missing:
        lines.append("With synchronous_commit = off, COMMIT returned before the WAL was written, so")
        lines.append("some acknowledged commits were lost when the process died: check (a) FAILS.")
    text = "\n".join(lines)
    print(text)

    # Evidence from the server itself: the crash recovery messages.
    recovery = [line for line in containers.postgres_log_since(kill_utc)
                if any(k in line for k in ("interrupted", "not properly shut down",
                                           "automatic recovery", "redo", "ready to accept",
                                           "checkpoint complete"))]
    path = common.write_text(recovery_name, text + "\n\nServer log after restart:\n"
                             + "\n".join(recovery) + "\n")
    print("\nServer recovery log:\n  " + "\n  ".join(recovery[:6]))
    print(f"Saved to {path} and results/{log_file.name}")

    chart(len(logged), len(in_table), len(missing), len(unlogged), kill_at, log_file, chart_name)
    # The async variant is EXPECTED to fail check (a); it still counts as a successful demo.
    return 0 if (check_a and check_b) or async_commit else 1


def chart(logged, found, missing, unlogged, kill_at, log_file, chart_name) -> None:
    with log_file.open(newline="", encoding="utf-8") as f:
        times = sorted(float(row["acknowledged_at_s"]) for row in csv.DictReader(f))
    fig, (left, right) = charts.figure(ncols=2, width=11, height=4)
    left.plot(times, range(1, len(times) + 1), color=charts.PRIMARY)
    left.axvline(kill_at, color=charts.CRITICAL, linewidth=1.5)
    # Commits already in flight still finish while docker kill is being carried out.
    left.annotate("docker kill issued", xy=(kill_at, 0.05), xycoords=("data", "axes fraction"),
                  xytext=(5, 0), textcoords="offset points", color=charts.INK)
    left.set_title("Acknowledged commits before the crash")
    left.set_xlabel("seconds")
    left.set_ylabel("commits logged")
    left.set_xlim(0, kill_at * 1.3)

    labels = ["logged\n(acknowledged)", "found after\nrestart", "logged but\nmissing",
              "in table,\nnot logged"]
    values = [logged, found, missing, unlogged]
    colours = [charts.PRIMARY, charts.PRIMARY, charts.CRITICAL if missing else charts.GOOD, charts.TERTIARY]
    bars = right.bar(labels, values, width=0.5, color=colours)
    charts.label_bars(right, bars)
    right.set_title("After WAL recovery: nothing acknowledged was lost"
                    if not missing else "After recovery: acknowledged commits were LOST")
    right.set_ylabel("registrations")
    right.set_ylim(0, max(values) * 1.15)
    right.tick_params(axis="x", labelsize=8.5)
    print(f"Chart: {charts.save(fig, chart_name)}")
