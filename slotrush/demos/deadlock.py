"""Demo 4, 'deadlock': student A moves from offering P to Q while student B
moves from Q to P.

Run 1, naive: each move is drop_course(old) then register(new) in ONE
transaction. A barrier makes both finish their drop first, so A holds P's row
lock and B holds Q's. Then A asks for Q and B asks for P: a cycle. After
deadlock_timeout (1 s) PostgreSQL's deadlock detector aborts one of them with
SQLSTATE 40P01; the other then goes through.

Run 2, swap_course(): both lock the LOWER offering id first, so the second
swapper simply waits for the first and both succeed.
"""
import threading
import time
from datetime import datetime, timezone

import psycopg
from matplotlib.patches import Patch

from .. import charts, containers
from ..db import pg_connect
from . import common

HOLD_SECONDS = 0.5      # in run 2, each swap keeps its transaction open this long


def setup() -> tuple[int, int, str, str]:
    """Fresh offerings P and Q (same course, different slots) with A in P and B in Q."""
    with pg_connect() as conn:
        common.reset(conn)
        p = common.make_offering(conn, "T01", capacity=5)
        q = common.make_offering(conn, "T02", capacity=5)
        a, b = common.make_bots(conn, 2)
        conn.execute("SELECT register(%s, %s)", (a, p))
        conn.execute("SELECT register(%s, %s)", (b, q))
    return p, q, a, b


def naive_run(p, q, a, b):
    barrier = threading.Barrier(2)
    start = time.perf_counter()
    outcome = {}

    def move(name, reg_no, from_id, to_id):
        t = {"begin": time.perf_counter() - start}
        with pg_connect(autocommit=True, application_name=f"deadlock-{name}") as conn:
            conn.execute("BEGIN")
            conn.execute("SELECT drop_course(%s, %s)", (reg_no, from_id))   # now holds from_id
            t["dropped"] = time.perf_counter() - start
            barrier.wait()                    # both hold one offering before either goes on
            t["asked"] = time.perf_counter() - start
            try:
                status = conn.execute("SELECT register(%s, %s)", (reg_no, to_id)).fetchone()[0]
                conn.execute("COMMIT")
                t["end"] = time.perf_counter() - start
                outcome[name] = (f"committed ({status})", t, None)
            except psycopg.errors.DeadlockDetected as exc:                 # SQLSTATE 40P01
                t["end"] = time.perf_counter() - start
                conn.execute("ROLLBACK")
                outcome[name] = ("deadlock victim, rolled back", t, exc)

    threads = [threading.Thread(target=move, args=("A", a, p, q)),
               threading.Thread(target=move, args=("B", b, q, p))]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    return outcome


def swap_run(p, q, a, b):
    barrier = threading.Barrier(2)
    start = time.perf_counter()
    outcome = {}

    def swap(name, reg_no, from_id, to_id):
        t = {"begin": time.perf_counter() - start}
        with pg_connect(autocommit=True, application_name=f"swap-{name}") as conn:
            conn.execute("BEGIN")
            barrier.wait()
            t["asked"] = time.perf_counter() - start
            status = conn.execute("SELECT swap_course(%s, %s, %s)",
                                  (reg_no, from_id, to_id)).fetchone()[0]
            t["dropped"] = time.perf_counter() - start     # got its locks, swap done
            time.sleep(HOLD_SECONDS)
            conn.execute("COMMIT")
            t["end"] = time.perf_counter() - start
            outcome[name] = (f"committed ({status})", t, None)

    threads = [threading.Thread(target=swap, args=("A", a, p, q)),
               threading.Thread(target=swap, args=("B", b, q, p))]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    return outcome


def where_is(reg_no, p, q) -> str:
    with pg_connect() as conn:
        rows = conn.execute("SELECT offering_id FROM registration WHERE reg_no = %s",
                            (reg_no,)).fetchall()
    names = {p: "P", q: "Q"}
    return ", ".join(names.get(r[0], str(r[0])) for r in rows) or "nowhere"


def run() -> int:
    log_since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ---- Run 1: naive drop + register
    p, q, a, b = setup()
    print(f"Run 1 (naive): A moves P({p}) -> Q({q}) while B moves Q({q}) -> P({p}),")
    print("each as drop_course() then register() in one transaction.")
    naive = naive_run(p, q, a, b)
    victims = [n for n, (result, _, exc) in naive.items() if exc is not None]
    for name in "AB":
        result, t, _ = naive[name]
        print(f"  {name}: {result} after {t['end'] - t['asked']:.2f} s waiting")
    print(f"  Afterwards A is in {where_is(a, p, q)}, B is in {where_is(b, p, q)}.")
    print("  The victim's ROLLBACK also undid its drop_course(), so it is back where it")
    print("  started; it would have to retry the move.")
    for name in victims:
        exc = naive[name][2]
        print(f"\nPostgreSQL's message to {name} (SQLSTATE {exc.sqlstate}):")
        print(f"  ERROR:  {exc.diag.message_primary}")
        for line in (exc.diag.message_detail or "").splitlines():
            print(f"  DETAIL: {line}")
        if exc.diag.message_hint:
            print(f"  HINT:   {exc.diag.message_hint}")

    # ---- Run 2: swap_course with ordered locking
    p, q, a, b = setup()
    print(f"\nRun 2 (swap_course): the same two moves, P({p}) <-> Q({q}).")
    swaps = swap_run(p, q, a, b)
    for name in "AB":
        result, t, _ = swaps[name]
        print(f"  {name}: {result}, waited {t['dropped'] - t['asked']:.2f} s for its locks")
    print(f"  Afterwards A is in {where_is(a, p, q)}, B is in {where_is(b, p, q)}.")
    print("  Both lock the lower offering id first, so one waits behind the other: no cycle.")

    # ---- Evidence: the server log and a timeline chart
    log = [line for line in containers.postgres_log_since(log_since)
           if "deadlock" in line.lower() or "still waiting" in line
           or "acquired" in line or "DETAIL" in line or "Process" in line]
    path = common.write_text("demo_deadlock_server_log.txt", "\n".join(log) + "\n")
    print(f"\nServer log lines saved to {path} ({len(log)} lines)")

    timeline_chart(naive, swaps)
    both_swapped = all(s[0].startswith("committed (OK") for s in swaps.values())
    return 0 if len(victims) == 1 and both_swapped else 1


def timeline_chart(naive, swaps) -> None:
    fig, axes = charts.figure(nrows=2, width=10, height=4.6)
    runs = [("Run 1: drop_course + register (deadlock)", naive, "dropped", "asked"),
            ("Run 2: swap_course, lower id locked first", swaps, "asked", "dropped")]
    for ax, (title, outcome, work_end, wait_end) in zip(axes, runs):
        for row, name in enumerate("BA"):
            result, t, _ = outcome[name]
            if outcome is naive:
                spans = [(t["begin"], t["dropped"], charts.BLUE),       # drop: holds a lock
                         (t["asked"], t["end"], charts.ORANGE)]         # waiting in register()
            else:
                spans = [(t["asked"], t["dropped"], charts.ORANGE),     # inside swap_course
                         (t["dropped"], t["end"], charts.BLUE)]         # holding locks
            for x0, x1, colour in spans:
                ax.broken_barh([(x0, max(x1 - x0, 0.01))], (row - 0.2, 0.4), color=colour)
            ax.annotate(result, xy=(t["end"], row), xytext=(6, 0), textcoords="offset points",
                        va="center", color=charts.INK)
        ax.set_yticks([0, 1], ["student B", "student A"])
        ax.set_title(title)
        ax.set_xlim(0, max(o[1]["end"] for o in outcome.values()) * 1.6)
        ax.grid(axis="y", visible=False)
    axes[1].set_xlabel("seconds")
    fig.legend(handles=[Patch(color=charts.BLUE, label="working, holding row locks"),
                        Patch(color=charts.ORANGE, label="blocked, waiting for a row lock")],
               loc="outside upper right", ncols=2)
    print(f"Chart: {charts.save(fig, 'demo_deadlock.png')}")
