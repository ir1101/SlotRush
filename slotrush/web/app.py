"""SlotRush web front end: Flask routes.

No ORM and no login system. "Log in as" just remembers, in Flask's signed
session cookie, which role and which student or faculty member you chose.
Every page then runs its SQL as that role (see data.py), and every
registration goes through the same PL/pgSQL functions as the demos:
register(), drop_course() and swap_course().
"""
import csv
import json
import secrets
from functools import wraps
from pathlib import Path

import psycopg
from flask import (Flask, abort, redirect, render_template, request, send_from_directory,
                   session, url_for)
from psycopg_pool import PoolTimeout

from ..config import RESULTS_DIR, SEMESTER
from . import data

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
PERIODS = range(1, 9)

# What each status code returned by the PL/pgSQL functions means, in plain words.
STATUS_TEXT = {
    "OK": "Done.",
    "FULL": "No seat left. register() put you on the waitlist; swap_course() changes nothing.",
    "CLASH": "One of its (day, period) meetings overlaps a class you already have.",
    "CREDIT_LIMIT": "This would take you over the maximum credits for the semester.",
    "PREREQ": "You have not completed every prerequisite of this course.",
    "DUPLICATE": "You already have this course (this or another offering of it) this semester.",
    "NOT_REGISTERED": "You are not registered in that offering.",
}

# Evidence page: syllabus module -> files in results/ with a one-line caption.
EVIDENCE = [
    ("01", "Architecture", [
        ("phase0_connection_check.txt", "Connection check: versions, fsync, synchronous_commit, max_connections"),
    ]),
    ("02", "Relational model and ER", [
        ("data_profile.png", "Credits per student and seat fill across the 4,500 offerings"),
        ("check_data.txt", "Eight integrity checks over every generated registration"),
        ("null_behaviour.txt", "NULL in comparisons, NOT IN, COUNT, UNIQUE and GROUP BY"),
    ]),
    ("03", "Normalisation", [
        ("normalisation_lossless_check.txt", "FDs, closures, 1NF to BCNF, 4NF, 5NF, every lossless-join test"),
        ("flat_registration_export.csv", "The flat, denormalised registration table"),
        ("nf4_faculty_preference.csv", "4NF example: two independent multivalued dependencies"),
        ("nf5_eligibility.csv", "5NF example: a join dependency"),
    ]),
    ("04", "Indexing and query processing", [
        ("bench_chart.png", "Five queries under no index, B-tree and hash indexes"),
        ("bench_summary.csv", "Median times and the access path PostgreSQL chose"),
        ("plans/Q3_course_time_range__btree.txt", "EXPLAIN (ANALYZE, BUFFERS): the range query with a B-tree"),
        ("plans/Q3_course_time_range__hash.txt", "The same query with a hash index: back to a sequential scan"),
    ]),
    ("05", "Transactions and recovery", [
        ("demo_crash.png", "docker kill mid-run: every acknowledged commit survives"),
        ("demo_crash_async.png", "With synchronous_commit = off, acknowledged commits are lost"),
        ("demo_crash_recovery_log.txt", "PostgreSQL's own crash-recovery log lines"),
        ("commit_log.csv", "Commits the bots logged after COMMIT returned"),
    ]),
    ("06", "Concurrency control", [
        ("demo_lost_update.png", "Naive read-then-write at READ COMMITTED: 80 students in 30 seats"),
        ("demo_locking.png", "register() with SELECT ... FOR UPDATE: exactly 30"),
        ("demo_isolation_comparison.png", "Lost update vs locking vs SERIALIZABLE"),
        ("demo_deadlock.png", "Opposite moves deadlock; ordered locking does not"),
        ("demo_locking_snapshot.csv", "Who waited on whom (pg_locks + pg_stat_activity)"),
        ("demo_deadlock_server_log.txt", "PostgreSQL's deadlock report"),
    ]),
    ("07", "NoSQL", [
        ("nosql_reviews.png", "MongoDB reviews: common tags and rating by course type"),
        ("nosql_index_explain.txt", "COLLSCAN before the index, IXSCAN after"),
        ("nosql_aggregations.txt", "Four aggregation pipelines and their output"),
    ]),
    ("08", "Testing", [
        ("pytest_report.txt", "Every test and its result"),
    ]),
]


DEPARTMENTS = {
    "Engineering schools": [("BCSE", "Computer science"),
                            ("BITE", "Information technology"),
                            ("BECE", "Electronics"),
                            ("BEEE", "Electrical"),
                            ("BMEE", "Mechanical"),
                            ("BCLE", "Civil")],
    "Sciences and humanities": [("BMAT", "Mathematics"), ("BPHY", "Physics"),
                                ("BCHY", "Chemistry"), ("BHUM", "Humanities")],
}
CREDITS_FILE = Path(__file__).parent / "static" / "img" / "credits.json"


def read_result(name: str) -> dict | None:
    """A demo's saved numbers (results/demo_<name>.json), or None if it has not run."""
    path = RESULTS_DIR / f"demo_{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def picture_credits() -> list[dict]:
    """Credits for the found photographs, recorded when they were downloaded."""
    if not CREDITS_FILE.exists():
        return []
    return json.loads(CREDITS_FILE.read_text(encoding="utf-8"))


def index_speedup() -> int | None:
    """How many times faster the student-timetable query ran with a B-tree index."""
    path = RESULTS_DIR / "bench_summary.csv"
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as f:
        medians = {(r["query"], r["setup"]): float(r["median_ms"]) for r in csv.DictReader(f)}
    none, btree = medians.get(("Q1_student_timetable", "none")), medians.get(("Q1_student_timetable", "btree"))
    return round(none / btree) if none and btree else None


def tests_passed() -> int | None:
    path = RESULTS_DIR / "pytest_report.txt"
    if not path.exists():
        return None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if " passed" in line:
            return int(line.strip(" =").split(" passed")[0].split()[-1])
    return None


def create_app(dbname: str | None = None) -> Flask:
    """Build the app. dbname lets the tests point it at the test database."""
    app = Flask(__name__)
    # A new random key on every start signs the session cookie, so "log in as"
    # choices simply reset when the server restarts. Nothing secret is stored.
    app.secret_key = secrets.token_hex(16)
    app.config["TEMPLATES_AUTO_RELOAD"] = True      # edited templates show up on refresh
    data.open_pool(dbname)

    # ------------------------------------------------------------------ helpers

    def who() -> dict:
        """The identity chosen on the log-in page (empty dict if none)."""
        return session.get("who", {})

    def require(role: str):
        """Decorator: send the visitor to the log-in page unless they are this role."""
        def decorator(view):
            @wraps(view)
            def wrapper(*args, **kwargs):
                if who().get("role") != role:
                    return redirect(url_for("login", need=role))
                return view(*args, **kwargs)
            return wrapper
        return decorator

    def as_me():
        """A transaction running as the logged-in identity."""
        me = who()
        return data.as_role(me["role"], reg_no=me.get("reg_no"), faculty_id=me.get("faculty_id"))

    def remember_action(call: str, status: str, verb: str) -> None:
        """Keep the last function call so the next page can show it (POST-redirect-GET)."""
        text = STATUS_TEXT.get(status, "")
        if status == "OK":
            text = {"register": "Registered. seats_left went down by one.",
                    "drop": "Dropped. The seat is free again.",
                    "swap": "Swapped in one transaction: dropped the old offering, took the new one."}[verb]
        session["last_action"] = {"call": call, "status": status, "text": text,
                                  "role": data.ROLES[who()["role"]]}

    def back(default: str):
        target = request.form.get("next", "")
        return redirect(target if target.startswith("/") else url_for(default))

    @app.context_processor
    def page_globals():
        # Available in every template.
        return {"me": who(), "semester": SEMESTER, "credits": picture_credits(),
                "last_action": session.pop("last_action", None)}

    @app.errorhandler(psycopg.OperationalError)
    @app.errorhandler(PoolTimeout)
    def database_down(error):
        detail = (str(error).strip().splitlines() or ["no detail"])[0]
        return render_template("error.html", title="Database not reachable", detail=detail,
                               hint="Start it with: python -m slotrush up"), 503

    # ------------------------------------------------------------------ public pages

    @app.get("/")
    def home():
        with data.as_role("admin") as db:
            stats = db.one("""
                SELECT count(*)                      AS offerings,
                       sum(capacity)                 AS seats,
                       sum(seats_taken)              AS taken,
                       count(*) FILTER (WHERE seats_left = 0) AS full_offerings,
                       count(*) - count(venue)       AS no_venue
                FROM v_admin_seat_fill
                WHERE semester = %s""", (SEMESTER,))
            stats["students"] = db.value("SELECT count(*) FROM student WHERE programme <> 'BOT'")
            # Registrations per department (the first four letters of the course code),
            # for the receipt that adds up to the total.
            per_dept = {r["dept"]: r["n"] for r in db.all("""
                SELECT left(o.course_code, 4) AS dept, count(*) AS n
                FROM registration r JOIN offering o ON o.offering_id = r.offering_id
                WHERE o.semester = %s
                GROUP BY 1""", (SEMESTER,))}
        receipt = [(group, [(name, code, per_dept.get(code, 0)) for code, name in rows])
                   for group, rows in DEPARTMENTS.items()]
        races = {"none": read_result("lost_update"), "lock": read_result("locking"),
                 "serial": read_result("serializable")}
        return render_template("home.html", stats=stats, receipt=receipt,
                               receipt_total=sum(per_dept.values()), races=races,
                               crash=read_result("crash"), crash_async=read_result("crash_async"),
                               speedup=index_speedup(), tests=tests_passed())

    @app.get("/login")
    def login():
        with data.as_role("admin") as db:
            faculty = db.all("""
                SELECT f.faculty_id, f.first_name || ' ' || f.last_name AS name, f.school,
                       count(o.offering_id) AS classes
                FROM faculty f
                JOIN offering o ON o.faculty_id = f.faculty_id AND o.semester = %s
                GROUP BY f.faculty_id ORDER BY classes DESC, f.faculty_id LIMIT 12""", (SEMESTER,))
            examples = db.all("""
                SELECT reg_no, first_name || ' ' || last_name AS name
                FROM student WHERE programme <> 'BOT' ORDER BY reg_no LIMIT 4""")
        return render_template("login.html", faculty=faculty, examples=examples,
                               need=request.args.get("need"), error=request.args.get("error"))

    @app.post("/login")
    def do_login():
        role = request.form.get("role")
        if role == "student":
            reg_no = request.form.get("reg_no", "").strip().upper()
            if request.form.get("random"):
                with data.as_role("admin") as db:
                    reg_no = db.value("SELECT reg_no FROM registration ORDER BY random() LIMIT 1")
            # Look the student up AS that student: row-level security returns the row
            # only if app.reg_no matches, so a made-up reg_no simply finds nothing.
            with data.as_role("student", reg_no=reg_no) as db:
                row = db.one("SELECT reg_no, first_name || ' ' || last_name AS name FROM student")
            if not row:
                return redirect(url_for("login", error=f"No student with reg_no {reg_no or '(empty)'}"))
            session["who"] = {"role": "student", "reg_no": row["reg_no"], "name": row["name"]}
            return redirect(url_for("student"))
        if role == "faculty":
            raw = request.form.get("faculty_id", "").strip()
            with data.as_role("admin") as db:
                row = db.one("SELECT faculty_id, first_name || ' ' || last_name AS name "
                             "FROM faculty WHERE faculty_id = %s",
                             (int(raw),)) if raw.isdigit() else None
            if not row:
                return redirect(url_for("login", error=f"No faculty member with id {raw or '(empty)'}"))
            session["who"] = {"role": "faculty", "faculty_id": row["faculty_id"], "name": row["name"]}
            return redirect(url_for("faculty"))
        if role == "admin":
            session["who"] = {"role": "admin", "name": "Admin"}
            return redirect(url_for("admin"))
        abort(400)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("home"))

    # ------------------------------------------------------------------ student

    @app.get("/student")
    @require("student")
    def student():
        with as_me() as db:
            credits = db.one("SELECT total_credits, courses, min_credits, max_credits "
                             "FROM v_student_credits")
            meetings = db.all("SELECT day, period, slot_id, course_code, title, course_type, venue "
                              "FROM v_student_timetable WHERE semester = %s", (SEMESTER,))
            classes = db.all("""
                SELECT r.offering_id, o.course_code, c.title, c.course_type, c.credits,
                       o.slot_id, o.venue, f.first_name || ' ' || f.last_name AS faculty,
                       r.registered_at
                FROM registration r
                JOIN offering o ON o.offering_id = r.offering_id
                JOIN course c   ON c.course_code = o.course_code
                JOIN faculty f  ON f.faculty_id = o.faculty_id
                WHERE o.semester = %s
                ORDER BY o.slot_id""", (SEMESTER,))
            # Other offerings of each of my courses that still have a seat: swap targets.
            swaps = db.all("""
                SELECT o.course_code, o.offering_id, o.slot_id, o.seats_left
                FROM offering o
                WHERE o.semester = %s AND o.seats_left > 0
                  AND o.course_code IN (SELECT o2.course_code FROM registration r
                                        JOIN offering o2 ON o2.offering_id = r.offering_id)
                  AND o.offering_id NOT IN (SELECT offering_id FROM registration)
                ORDER BY o.course_code, o.slot_id""", (SEMESTER,))
        grid = {(m["day"], m["period"]): m for m in meetings}
        swap_targets = {}
        for s in swaps:
            swap_targets.setdefault(s["course_code"], []).append(s)
        return render_template("student.html", credits=credits, classes=classes, grid=grid,
                               days=DAYS, periods=PERIODS, swap_targets=swap_targets)

    @app.get("/student/catalogue")
    @require("student")
    def catalogue():
        q = request.args.get("q", "").strip()
        slot = request.args.get("slot", "").strip().upper()
        open_only = request.args.get("open") == "1"
        with as_me() as db:
            slots = [r["slot_id"] for r in db.all(
                "SELECT DISTINCT slot_id FROM slot_timing ORDER BY slot_id")]
            rows = db.all("""
                SELECT o.offering_id, o.course_code, c.title, c.course_type, c.credits,
                       o.slot_id, o.venue, o.capacity, o.seats_left,
                       f.first_name || ' ' || f.last_name AS faculty,
                       -- Already have this course? (RLS: registration shows only my rows)
                       EXISTS (SELECT 1 FROM registration r
                               JOIN offering mine ON mine.offering_id = r.offering_id
                               WHERE mine.course_code = o.course_code
                                 AND mine.semester = o.semester)            AS taken,
                       -- Would it clash with my timetable? A preview only:
                       -- register() checks again, under a lock, when you click.
                       EXISTS (SELECT 1 FROM registration r
                               JOIN offering mine     ON mine.offering_id = r.offering_id
                               JOIN slot_timing have  ON have.slot_id = mine.slot_id
                               JOIN slot_timing want  ON want.day = have.day
                                                     AND want.period = have.period
                               WHERE want.slot_id = o.slot_id
                                 AND mine.semester = o.semester)            AS clash
                FROM offering o
                JOIN course c  ON c.course_code = o.course_code
                JOIN faculty f ON f.faculty_id = o.faculty_id
                WHERE o.semester = %(semester)s
                  AND (%(q)s = '' OR o.course_code ILIKE %(like)s OR c.title ILIKE %(like)s)
                  AND (%(slot)s = '' OR o.slot_id = %(slot)s)
                  AND (NOT %(open)s OR o.seats_left > 0)
                ORDER BY o.course_code, o.slot_id
                LIMIT 60""", {"semester": SEMESTER, "q": q, "like": f"%{q}%",
                              "slot": slot, "open": open_only})
        return render_template("catalogue.html", rows=rows, q=q, slot=slot, slots=slots,
                               open_only=open_only)

    def call_function(sql: str, args: tuple, verb: str, default_page: str):
        """Run register()/drop_course()/swap_course() as the student and remember the result."""
        me = who()
        shown = sql.replace("%s", "{}").format(*[repr(a) for a in args])
        try:
            with as_me() as db:
                status = db.value(sql, args)
        except psycopg.errors.RaiseException as exc:          # e.g. unknown offering
            status = "ERROR"
            session["last_action"] = {"call": shown, "status": status,
                                      "text": exc.diag.message_primary,
                                      "role": data.ROLES[me["role"]]}
            return back(default_page)
        remember_action(shown, status, verb)
        return back(default_page)

    def form_int(name: str) -> int:
        value = request.form.get(name, "")
        if not value.isdigit():
            abort(400)
        return int(value)

    @app.post("/student/register")
    @require("student")
    def do_register():
        return call_function("SELECT register(%s, %s)",
                             (who()["reg_no"], form_int("offering_id")), "register", "catalogue")

    @app.post("/student/drop")
    @require("student")
    def do_drop():
        return call_function("SELECT drop_course(%s, %s)",
                             (who()["reg_no"], form_int("offering_id")), "drop", "student")

    @app.post("/student/swap")
    @require("student")
    def do_swap():
        return call_function("SELECT swap_course(%s, %s, %s)",
                             (who()["reg_no"], form_int("from_offering"), form_int("to_offering")),
                             "swap", "student")

    # ------------------------------------------------------------------ faculty

    @app.get("/faculty")
    @require("faculty")
    def faculty():
        me = who()
        with as_me() as db:
            offerings = db.all("""
                SELECT o.offering_id, o.course_code, c.title, c.course_type, o.slot_id, o.venue,
                       o.capacity, o.seats_left
                FROM offering o JOIN course c ON c.course_code = o.course_code
                WHERE o.faculty_id = %s AND o.semester = %s
                ORDER BY o.slot_id""", (me["faculty_id"], SEMESTER))
            # The view joins registration, so row-level security limits it to my classes.
            students = db.all("""
                SELECT offering_id, reg_no, first_name, last_name, registered_at
                FROM v_faculty_class_list
                WHERE semester = %s
                ORDER BY offering_id, last_name, first_name""", (SEMESTER,))
        by_offering = {}
        for s in students:
            by_offering.setdefault(s["offering_id"], []).append(s)
        return render_template("faculty.html", offerings=offerings, by_offering=by_offering)

    # ------------------------------------------------------------------ admin

    @app.get("/admin")
    @require("admin")
    def admin():
        q = request.args.get("q", "").strip()
        slot = request.args.get("slot", "").strip().upper()
        full_only = request.args.get("full") == "1"
        with as_me() as db:
            summary = db.all("""
                SELECT s.slot_kind, count(*) AS offerings, sum(v.capacity) AS seats,
                       sum(v.seats_taken) AS taken,
                       count(*) FILTER (WHERE v.seats_left = 0) AS full_offerings,
                       sum(v.waitlisted) AS waitlisted
                FROM v_admin_seat_fill v JOIN slot s ON s.slot_id = v.slot_id
                WHERE v.semester = %s
                GROUP BY s.slot_kind ORDER BY s.slot_kind""", (SEMESTER,))
            rows = db.all("""
                SELECT v.offering_id, v.course_code, c.title, v.slot_id, v.venue, v.capacity,
                       v.seats_taken, v.seats_left, v.fill_pct, v.waitlisted
                FROM v_admin_seat_fill v JOIN course c ON c.course_code = v.course_code
                WHERE v.semester = %(semester)s
                  AND (%(q)s = '' OR v.course_code ILIKE %(like)s OR c.title ILIKE %(like)s)
                  AND (%(slot)s = '' OR v.slot_id = %(slot)s)
                  AND (NOT %(full)s OR v.seats_left = 0)
                ORDER BY v.fill_pct DESC, v.waitlisted DESC, v.offering_id
                LIMIT 100""", {"semester": SEMESTER, "q": q, "like": f"%{q}%",
                               "slot": slot, "full": full_only})
            slots = [r["slot_id"] for r in db.all("SELECT slot_id FROM slot ORDER BY slot_id")]
        return render_template("admin.html", summary=summary, rows=rows, q=q, slot=slot,
                               slots=slots, full_only=full_only)

    # ------------------------------------------------------------------ evidence

    @app.get("/evidence")
    def evidence():
        sections = []
        for number, module, files in EVIDENCE:
            present = [(name, caption, name.endswith(".png"))
                       for name, caption in files if (RESULTS_DIR / name).exists()]
            sections.append((number, module, present))
        report = RESULTS_DIR / "pytest_report.txt"
        test_line = ""
        if report.exists():
            lines = [ln for ln in report.read_text(encoding="utf-8").splitlines() if " passed" in ln]
            test_line = lines[-1].strip(" =") if lines else ""
        return render_template("evidence.html", sections=sections, test_line=test_line)

    @app.get("/results/<path:name>")
    def result_file(name: str):
        # send_from_directory refuses paths that climb out of results/ (e.g. ../.env).
        mimetype = "text/plain" if Path(name).suffix in {".txt", ".csv", ".json"} else None
        return send_from_directory(RESULTS_DIR, name, mimetype=mimetype)

    return app


def run(host: str = "127.0.0.1", port: int = 5000) -> int:
    """The 'web' command. The development server is fine for a single-user demo."""
    app = create_app()
    print(f"SlotRush web front end on http://{host}:{port}  (Ctrl+C to stop)")
    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    finally:
        data.close_pool()
    return 0
