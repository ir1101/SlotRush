"""Pieces shared by the demos: resetting demo data, bot students, and running
bots in parallel threads that all start at the same moment.

Demo data is kept apart from the real data:
  - demo offerings are in semester 'DEMO'
  - bot students have reg_no 99BOT0001, 99BOT0002, ...
  - they use one demo course (DEMO101L) taught by one demo faculty member
Every demo calls reset() first, which deletes ALL demo rows, so any demo can
be rerun any number of times and leftovers from one demo never break another.
"""
import csv
import json
import threading
import time

from ..config import DEMO_SEMESTER, RESULTS_DIR
from ..db import pg_connect

DEMO_COURSE = "DEMO101L"
DEMO_FACULTY = 999001
BOT_PREFIX = "99BOT"           # fits the reg_no CHECK: 2 digits, 3 letters, 4 digits


def clear(conn) -> None:
    """Delete every demo row. Registrations and waitlist entries of demo
    offerings and bots go too, through ON DELETE CASCADE."""
    conn.execute("DELETE FROM offering WHERE semester = %s", (DEMO_SEMESTER,))
    conn.execute("DELETE FROM student WHERE reg_no LIKE %s", (BOT_PREFIX + "%",))
    conn.execute("DELETE FROM course WHERE course_code = %s", (DEMO_COURSE,))
    conn.execute("DELETE FROM faculty WHERE faculty_id = %s", (DEMO_FACULTY,))


def reset(conn) -> None:
    """Delete every demo row, then create a fresh demo course and faculty member."""
    clear(conn)
    conn.execute("INSERT INTO faculty VALUES (%s, 'Demo', 'Faculty', 'DEMO', 'demo@slotrush.example')",
                 (DEMO_FACULTY,))
    conn.execute("INSERT INTO course VALUES (%s, 'Concurrency Demo', 3, 'THEORY')", (DEMO_COURSE,))
    conn.execute("INSERT INTO theory_course (course_code, lecture_hours) VALUES (%s, 3)",
                 (DEMO_COURSE,))


def make_offering(conn, slot_id: str, capacity: int, seats_left: int | None = None) -> int:
    """Create a demo offering and return its id (new ids come from the identity column)."""
    seats = capacity if seats_left is None else seats_left
    return conn.execute(
        "INSERT INTO offering (course_code, faculty_id, slot_id, semester, venue, capacity, seats_left) "
        "VALUES (%s, %s, %s, %s, NULL, %s, %s) RETURNING offering_id",
        (DEMO_COURSE, DEMO_FACULTY, slot_id, DEMO_SEMESTER, capacity, seats),
    ).fetchone()[0]


def make_bots(conn, count: int) -> list[str]:
    """Insert count bot students and return their reg_nos."""
    reg_nos = [f"{BOT_PREFIX}{i:04d}" for i in range(1, count + 1)]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO student (reg_no, first_name, last_name, programme, admit_year, email) "
            "VALUES (%s, 'Bot', %s, 'BOT', 2026, %s)",
            [(r, r[-4:], f"{r.lower()}@bots.slotrush.example") for r in reg_nos],
        )
    return reg_nos


def run_bots(count: int, work, name: str) -> tuple[list, float]:
    """Run work(i, conn) in count threads, each with its own connection.

    Every thread connects first and then waits at a threading.Barrier, so all
    of them start their work at the same instant. Returns (results, seconds),
    where seconds is measured from the barrier release until the last thread ends.
    A result is whatever work() returned, or the exception it raised.
    """
    started = []
    barrier = threading.Barrier(count, action=lambda: started.append(time.perf_counter()))
    results = [None] * count

    def thread_main(i):
        # application_name shows up in pg_stat_activity, e.g. "locking-07".
        with pg_connect(autocommit=True, application_name=f"{name}-{i:02d}") as conn:
            barrier.wait()
            try:
                results[i] = work(i, conn)
            except Exception as exc:     # keep going; the demo reports it
                results[i] = exc

    threads = [threading.Thread(target=thread_main, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, time.perf_counter() - started[0]


def offering_state(offering_id: int) -> tuple[int, int, int]:
    """(capacity, seats_left, registrations actually in the table)."""
    with pg_connect() as conn:
        capacity, seats_left = conn.execute(
            "SELECT capacity, seats_left FROM offering WHERE offering_id = %s",
            (offering_id,)).fetchone()
        registered = conn.execute("SELECT count(*) FROM registration WHERE offering_id = %s",
                                  (offering_id,)).fetchone()[0]
    return capacity, seats_left, registered


def naive_register(conn, reg_no: str, offering_id: int, isolation: str) -> tuple[str, int]:
    """DELIBERATELY WRONG registration: read seats_left into Python, think for
    50 ms, then write back the old value minus one. Nothing locks the row between
    the read and the write. Returns (status, seats_left value that was read).

    The caller handles errors; on an error the transaction must be rolled back.
    """
    conn.execute(f"BEGIN ISOLATION LEVEL {isolation}")      # isolation is a fixed string
    seats = conn.execute("SELECT seats_left FROM offering WHERE offering_id = %s",
                         (offering_id,)).fetchone()[0]
    if seats <= 0:
        conn.execute("COMMIT")
        return "FULL", seats
    time.sleep(0.05)                                         # "thinking": the race window
    conn.execute("UPDATE offering SET seats_left = %s WHERE offering_id = %s",
                 (seats - 1, offering_id))
    conn.execute("INSERT INTO registration (offering_id, reg_no) VALUES (%s, %s)",
                 (offering_id, reg_no))
    conn.execute("COMMIT")
    return "OK", seats


def save_run(name: str, **numbers) -> None:
    """Save a demo's headline numbers to results/demo_<name>.json for the comparison chart."""
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"demo_{name.replace('-', '_')}.json"
    path.write_text(json.dumps({"run": name, **numbers}, indent=2), encoding="utf-8")


def load_run(name: str) -> dict | None:
    path = RESULTS_DIR / f"demo_{name.replace('-', '_')}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write_text(name: str, text: str) -> str:
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / name).write_text(text, encoding="utf-8")
    return f"results/{name}"


def write_csv(name: str, header: list[str], rows) -> str:
    """Save the numbers behind a chart, so the web page can draw the same chart."""
    RESULTS_DIR.mkdir(exist_ok=True)
    with (RESULTS_DIR / name).open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([header, *rows])
    return f"results/{name}"
