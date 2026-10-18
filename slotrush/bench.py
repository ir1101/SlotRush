"""The 'bench' command: five queries under three index setups.

  none   only the indexes that primary keys and UNIQUE constraints create
  btree  plus B-tree (B+ tree) secondary indexes
  hash   plus hash indexes instead

For every query and setup it saves EXPLAIN (ANALYZE, BUFFERS) to
results/plans/, then times one warm-up run and RUNS measured runs. The time
is PostgreSQL's own "Execution Time" (from EXPLAIN ANALYZE with per-node
timing off), so network delay between Python and the container is excluded.
Results: results/bench_timings.csv, results/bench_summary.csv,
results/bench_chart.png. At the end the normal B-tree indexes are restored.
"""
import csv
import json
import statistics

from matplotlib.ticker import FuncFormatter
from psycopg import sql

from . import charts
from .config import RESULTS_DIR, SEMESTER
from .db import pg_connect
from .demos import common

RUNS = 7
PLANS_DIR = RESULTS_DIR / "plans"

# Secondary indexes: (name, table, column, used for equality?)
INDEXES = [
    ("ix_registration_reg_no", "registration", "reg_no", True),
    ("ix_registration_registered_at", "registration", "registered_at", False),
    ("ix_offering_slot_id", "offering", "slot_id", True),
    ("ix_offering_faculty_id", "offering", "faculty_id", True),
    ("ix_offering_course_code", "offering", "course_code", True),
]
SETUPS = ["none", "btree", "hash"]

QUERIES = {
    "Q1_student_timetable": {
        "title": "One student's timetable",
        "predicate": "registration.reg_no = :reg_no",
        "coverage": "NOT covered by a constraint index: the registration PK is "
                    "(offering_id, reg_no), sorted by offering_id first.",
        "sql": """
            SELECT t.day, t.period, o.slot_id, c.course_code, c.title, o.venue
            FROM registration r
            JOIN offering o    ON o.offering_id = r.offering_id
            JOIN course c      ON c.course_code = o.course_code
            JOIN slot_timing t ON t.slot_id = o.slot_id
            WHERE r.reg_no = %(reg_no)s
            ORDER BY t.day, t.period""",
    },
    "Q2_seats_in_slot": {
        "title": "Seats left in one slot",
        "predicate": "offering.slot_id = :slot_id AND semester = :semester AND seats_left > 0",
        "coverage": "NOT covered: the only multi-column constraint index on offering is "
                    "UNIQUE (venue, semester, slot_id), which starts with venue.",
        "sql": """
            SELECT o.offering_id, o.course_code, o.faculty_id, o.capacity, o.seats_left
            FROM offering o
            WHERE o.slot_id = %(slot_id)s AND o.semester = %(semester)s AND o.seats_left > 0
            ORDER BY o.seats_left DESC""",
    },
    "Q3_course_time_range": {
        "title": "Registrations for a course in a time range",
        "predicate": "offering.course_code = :course AND registration.registered_at "
                     "BETWEEN :from AND :to (a RANGE predicate)",
        "coverage": "Predicates NOT covered. The join on offering_id IS served by the "
                    "registration PK (offering_id, reg_no) in every setup. A hash index "
                    "cannot answer BETWEEN.",
        "sql": """
            SELECT r.reg_no, r.registered_at, o.offering_id, o.slot_id
            FROM registration r
            JOIN offering o ON o.offering_id = r.offering_id
            WHERE o.course_code = %(course_code)s
              AND r.registered_at BETWEEN %(t_from)s AND %(t_to)s
            ORDER BY r.registered_at""",
    },
    "Q4_below_min_credits": {
        "title": "Students below the minimum credits",
        "predicate": "none: every student and every registration must be read",
        "coverage": "No selective predicate, so no index can help: expect a full scan "
                    "and hash joins in every setup.",
        "sql": """
            SELECT s.reg_no, s.first_name, s.last_name, COALESCE(SUM(c.credits), 0) AS credits
            FROM student s
            LEFT JOIN registration r ON r.reg_no = s.reg_no
            LEFT JOIN offering o     ON o.offering_id = r.offering_id
                                    AND o.semester = %(semester)s
            LEFT JOIN course c       ON c.course_code = o.course_code
            GROUP BY s.reg_no, s.first_name, s.last_name
            HAVING COALESCE(SUM(c.credits), 0) < %(min_credits)s""",
    },
    "Q5_faculty_class_list": {
        "title": "A faculty member's class list (5-way join)",
        "predicate": "faculty.faculty_id = :faculty_id (passed on to offering.faculty_id)",
        "coverage": "faculty.faculty_id is the faculty PK, but offering.faculty_id is NOT "
                    "covered. Registration rows are then found through the registration PK.",
        "sql": """
            SELECT f.last_name AS faculty, o.offering_id, c.course_code, o.slot_id,
                   s.reg_no, s.first_name, s.last_name
            FROM faculty f
            JOIN offering o     ON o.faculty_id = f.faculty_id
            JOIN course c       ON c.course_code = o.course_code
            JOIN registration r ON r.offering_id = o.offering_id
            JOIN student s      ON s.reg_no = r.reg_no
            WHERE f.faculty_id = %(faculty_id)s AND o.semester = %(semester)s
            ORDER BY o.offering_id, s.last_name""",
    },
}


def pick_parameters(conn) -> dict:
    """Deterministic parameter values taken from the loaded data."""
    reg_no = conn.execute("SELECT reg_no FROM registration GROUP BY reg_no "
                          "ORDER BY count(*) DESC, reg_no LIMIT 1").fetchone()[0]
    course = conn.execute("SELECT o.course_code FROM registration r "
                          "JOIN offering o ON o.offering_id = r.offering_id "
                          "GROUP BY o.course_code ORDER BY count(*) DESC, o.course_code "
                          "LIMIT 1").fetchone()[0]
    faculty = conn.execute("SELECT o.faculty_id FROM registration r "
                           "JOIN offering o ON o.offering_id = r.offering_id "
                           "GROUP BY o.faculty_id ORDER BY count(*) DESC, o.faculty_id "
                           "LIMIT 1").fetchone()[0]
    min_credits = conn.execute("SELECT min_credits FROM settings").fetchone()[0]
    return {
        "reg_no": reg_no,
        "slot_id": "T05",
        "semester": SEMESTER,
        "course_code": course,
        # A 30-minute window 12 hours after opening (India time): about 1% of all
        # registrations. (The first hour is the rush and holds about 15% of them,
        # too many for an index to beat a sequential scan.)
        "t_from": "2026-07-06 21:00:00+05:30",
        "t_to": "2026-07-06 21:30:00+05:30",
        "min_credits": min_credits,
        "faculty_id": faculty,
    }


def apply_setup(conn, setup: str) -> None:
    """Drop every ix_ index, then build the ones this setup needs."""
    for name, *_ in INDEXES:
        conn.execute(sql.SQL("DROP INDEX IF EXISTS {}").format(sql.Identifier(name)))
    if setup != "none":
        for name, table, column, _ in INDEXES:
            # In the hash setup the range column also gets a hash index, only to
            # show that the planner cannot use it for BETWEEN.
            conn.execute(sql.SQL("CREATE INDEX {} ON {} USING {} ({})").format(
                sql.Identifier(name), sql.Identifier(table),
                sql.SQL(setup), sql.Identifier(column)))
    conn.execute("ANALYZE registration")
    conn.execute("ANALYZE offering")


def access_paths(plan: dict) -> list[str]:
    """Walk a JSON plan and list how each table was read, e.g.
    'Index Scan on registration using ix_registration_reg_no'."""
    found = []
    if "Relation Name" in plan:
        text = f"{plan['Node Type']} on {plan['Relation Name']}"
        if "Index Name" in plan:
            text += f" using {plan['Index Name']}"
        found.append(text)
    elif "Index Name" in plan:
        # A Bitmap Index Scan names only the index; its parent Bitmap Heap Scan names the table.
        found.append(f"{plan['Node Type']} using {plan['Index Name']}")
    for child in plan.get("Plans", []):
        found.extend(access_paths(child))
    return found


def constraint_indexes(conn) -> list[str]:
    rows = conn.execute("""
        SELECT tablename, indexdef FROM pg_indexes
        WHERE schemaname = 'slotrush' AND indexname NOT LIKE 'ix\\_%%'
          AND tablename IN ('registration', 'offering', 'student', 'course', 'faculty', 'slot_timing')
        ORDER BY tablename, indexname""").fetchall()
    return [f"  {table:<13} {definition.split(' USING ')[1]}" for table, definition in rows]


def run() -> int:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    with pg_connect(autocommit=True) as conn:
        common.clear(conn)                       # no demo rows in the measurements
        params = pick_parameters(conn)
        # JIT compilation adds ~50-100 ms to big queries and would hide the index
        # effect, so it is switched off for this session only.
        conn.execute("SET jit = off")

        print("Indexes that exist in EVERY setup (from primary keys and UNIQUE constraints):")
        print("\n".join(constraint_indexes(conn)))
        print(f"\nParameters: {json.dumps(params, default=str)}")
        print(f"Timing: 1 warm-up + median of {RUNS} runs, PostgreSQL Execution Time, jit off.\n")
        for key, q in QUERIES.items():
            print(f"{key}: {q['title']}\n    predicate: {q['predicate']}\n    {q['coverage']}")

        timings, summary = [], []
        for setup in SETUPS:
            apply_setup(conn, setup)
            print(f"\n--- setup: {setup} ---")
            for key, q in QUERIES.items():
                # 1. The plan with real row counts and buffer use, saved for the report.
                text_plan = conn.execute("EXPLAIN (ANALYZE, BUFFERS) " + q["sql"], params).fetchall()
                plan_path = PLANS_DIR / f"{key}__{setup}.txt"
                plan_path.write_text(
                    f"-- {key} ({q['title']}), setup: {setup}\n-- parameters: {params}\n"
                    + q["sql"].strip() + "\n\n" + "\n".join(r[0] for r in text_plan) + "\n",
                    encoding="utf-8")

                # 2. Timing: warm-up, then RUNS measured executions.
                ms = []
                for run_no in range(RUNS + 1):
                    result = conn.execute("EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) " + q["sql"],
                                          params).fetchone()[0][0]
                    if run_no == 0:
                        paths = access_paths(result["Plan"])
                        continue                 # the warm-up run is not counted
                    ms.append(result["Execution Time"])
                    timings.append([key, setup, run_no, f"{result['Execution Time']:.3f}"])
                median = statistics.median(ms)
                summary.append([key, setup, f"{median:.3f}", "; ".join(paths)])
                print(f"  {key:<24} {median:>9.3f} ms   {'; '.join(sorted(set(paths)))}")

        apply_setup(conn, "btree")               # back to the normal schema

    with (RESULTS_DIR / "bench_timings.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["query", "setup", "run", "execution_ms"], *timings])
    with (RESULTS_DIR / "bench_summary.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["query", "setup", "median_ms", "access_paths"], *summary])
    print("\nSaved results/bench_timings.csv, results/bench_summary.csv and "
          f"{len(QUERIES) * len(SETUPS)} plans in results/plans/")
    chart(summary)
    print("B-tree secondary indexes restored.")
    return 0


def chart(summary) -> None:
    medians = {(row[0], row[1]): float(row[2]) for row in summary}
    keys = list(QUERIES)
    fig, ax = charts.figure(width=11, height=4.8)
    width = 0.26
    for i, setup in enumerate(SETUPS):
        xs = [k + (i - 1) * width for k in range(len(keys))]
        ax.bar(xs, [medians[(key, setup)] for key in keys], width=width * 0.92,
               color=charts.SERIES[i], label={"none": "no secondary index",
                                              "btree": "B-tree", "hash": "hash"}[setup])
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))   # 0.1, 1, 10 not 10^-1
    short = {"Q1": "student timetable", "Q2": "seats in a slot", "Q3": "course + time range",
             "Q4": "below min credits", "Q5": "faculty class list"}
    ax.set_xticks(range(len(keys)), [f"{k[:2]}\n{short[k[:2]]}" for k in keys])
    ax.set_ylabel("median execution time (ms, log scale)")
    ax.set_title(f"Five queries, three index setups (median of {RUNS} runs)")
    ax.legend(loc="upper left", ncols=3)
    print(f"Chart: {charts.save(fig, 'bench_chart.png')}")
