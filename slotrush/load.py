"""The 'load' command: rebuild the schema, generate the data and bulk load it.

Rows are generated in Python (slotrush/generate.py) and streamed into
PostgreSQL with COPY, which is far faster than 250,000 separate INSERTs or
register() calls. The generator already obeys every register() rule;
'check-data' (run at the end) proves it.
"""
import time

from . import check_data, setup_db
from .db import pg_connect
from .generate import Scale, generate

# table -> columns, in an order that satisfies the foreign keys
TABLES = [
    ("student", ["reg_no", "first_name", "last_name", "programme", "admit_year", "email"], "students"),
    ("student_phone", ["reg_no", "phone"], "phones"),
    ("faculty", ["faculty_id", "first_name", "last_name", "school", "email"], "faculty"),
    ("course", ["course_code", "title", "credits", "course_type"], "courses"),
    ("theory_course", ["course_code", "lecture_hours", "tutorial_hours"], "theory"),
    ("lab_course", ["course_code", "lab_hours", "lab_room_type"], "labs"),
    ("project_course", ["course_code", "max_team_size", "deliverable"], "projects"),
    ("prerequisite", ["course_code", "prereq_code"], "prerequisites"),
    ("completed_course", ["reg_no", "course_code", "semester", "grade"], "completed"),
    ("offering", ["offering_id", "course_code", "faculty_id", "slot_id", "semester",
                  "venue", "capacity", "seats_left"], "offerings"),
    ("registration", ["offering_id", "reg_no", "registered_at"], "registrations"),
]


def read_timetable(conn):
    """slot_id -> frozenset of (day, period), and slot_id -> kind, from the database."""
    cells, kinds = {}, {}
    rows = conn.execute("SELECT s.slot_id, s.slot_kind, t.day, t.period "
                        "FROM slot s JOIN slot_timing t ON t.slot_id = s.slot_id "
                        "ORDER BY s.slot_id, t.day, t.period").fetchall()
    for slot_id, kind, day, period in rows:
        cells.setdefault(slot_id, set()).add((day, period))
        kinds[slot_id] = kind
    return {s: frozenset(c) for s, c in cells.items()}, kinds


def copy_rows(conn, table: str, columns: list[str], rows: list[tuple]) -> None:
    """Stream rows into a table with COPY ... FROM STDIN."""
    with conn.cursor() as cur:
        with cur.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)


def run(scale: Scale = Scale()) -> int:
    started = time.perf_counter()
    setup_db.run()                                    # fresh, empty schema

    with pg_connect() as conn:
        slot_cells, slot_kind = read_timetable(conn)
    print("Generating data (fixed seed, about half a minute) ...")
    data = generate(slot_cells, slot_kind, scale)

    # One transaction: either every table is loaded or none is. The deferred
    # totality trigger on course runs at the COMMIT at the end of this block.
    with pg_connect() as conn:
        for table, columns, attr in TABLES:
            rows = getattr(data, attr)
            copy_rows(conn, table, columns, rows)
            print(f"  COPY {table:<17} {len(rows):>9,} rows")

        # seats_left = capacity minus registrations (offerings were loaded full).
        conn.execute("""
            UPDATE offering o
            SET seats_left = o.capacity - r.taken
            FROM (SELECT offering_id, count(*) AS taken
                  FROM registration GROUP BY offering_id) AS r
            WHERE r.offering_id = o.offering_id
        """)
        # The identity column did not count the ids we supplied ourselves, so move it
        # past the highest one; new demo offerings then get fresh ids.
        conn.execute("SELECT setval(pg_get_serial_sequence('offering', 'offering_id'), "
                     "(SELECT max(offering_id) FROM offering))")

    # ANALYZE gathers the statistics the query planner uses; VACUUM also marks
    # pages all-visible so index-only scans work. VACUUM cannot run inside a
    # transaction, hence autocommit.
    with pg_connect(autocommit=True) as conn:
        conn.execute("VACUUM (ANALYZE)")
    print(f"Loaded and analysed in {time.perf_counter() - started:.0f} s.\n")

    return check_data.run()
