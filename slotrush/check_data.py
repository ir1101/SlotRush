"""The 'check-data' command: prove the loaded data obeys every rule.

Each check is one SQL query that counts violations; 0 means PASS. Offerings in
the DEMO semester are reported separately: the lost-update demo breaks the
seat count there on purpose.
Results go to results/check_data.txt and results/data_profile.png.
"""
from . import charts
from .config import DEMO_SEMESTER, RESULTS_DIR
from .db import pg_connect

REPORT_FILE = RESULTS_DIR / "check_data.txt"

# (description, query returning the number of violations). %(demo)s = 'DEMO'.
CHECKS = [
    ("No student has two offerings of the same course in a semester", """
        SELECT count(*) FROM (
            SELECT r.reg_no, o.course_code, o.semester
            FROM registration r JOIN offering o ON o.offering_id = r.offering_id
            WHERE o.semester <> %(demo)s
            GROUP BY r.reg_no, o.course_code, o.semester
            HAVING count(*) > 1) AS duplicates"""),

    ("No student has two slots sharing a (day, period)", """
        SELECT count(*) FROM (
            SELECT DISTINCT r1.reg_no, r1.offering_id, r2.offering_id
            FROM registration r1
            JOIN offering o1     ON o1.offering_id = r1.offering_id
            JOIN registration r2 ON r2.reg_no = r1.reg_no AND r2.offering_id > r1.offering_id
            JOIN offering o2     ON o2.offering_id = r2.offering_id AND o2.semester = o1.semester
            JOIN slot_timing t1  ON t1.slot_id = o1.slot_id
            JOIN slot_timing t2  ON t2.slot_id = o2.slot_id
                                AND t2.day = t1.day AND t2.period = t1.period
            WHERE o1.semester <> %(demo)s) AS clashes"""),

    ("No student above the maximum credits", """
        SELECT count(*) FROM v_student_credits WHERE total_credits > max_credits"""),

    ("Every registration has its prerequisites completed", """
        SELECT count(*)
        FROM registration r
        JOIN offering o     ON o.offering_id = r.offering_id
        JOIN prerequisite p ON p.course_code = o.course_code
        WHERE o.semester <> %(demo)s
          AND NOT EXISTS (SELECT 1 FROM completed_course c
                          WHERE c.reg_no = r.reg_no AND c.course_code = p.prereq_code)"""),

    ("seats_left = capacity - registrations for every offering", """
        SELECT count(*) FROM offering o
        WHERE o.semester <> %(demo)s
          AND o.seats_left <> o.capacity - (SELECT count(*) FROM registration r
                                            WHERE r.offering_id = o.offering_id)"""),

    ("No offering has more registrations than capacity", """
        SELECT count(*) FROM offering o
        WHERE o.semester <> %(demo)s
          AND (SELECT count(*) FROM registration r WHERE r.offering_id = o.offering_id) > o.capacity"""),

    ("No faculty member teaches two overlapping slots", """
        SELECT count(*) FROM (
            SELECT DISTINCT o1.offering_id, o2.offering_id
            FROM offering o1
            JOIN offering o2    ON o2.faculty_id = o1.faculty_id AND o2.semester = o1.semester
                               AND o2.offering_id > o1.offering_id
            JOIN slot_timing t1 ON t1.slot_id = o1.slot_id
            JOIN slot_timing t2 ON t2.slot_id = o2.slot_id
                               AND t2.day = t1.day AND t2.period = t1.period
            WHERE o1.semester <> %(demo)s) AS faculty_clashes"""),

    ("Every course has a row in its subtype table (total specialisation)", """
        SELECT count(*) FROM course c
        WHERE NOT EXISTS (SELECT 1 FROM theory_course  t WHERE t.course_code = c.course_code)
          AND NOT EXISTS (SELECT 1 FROM lab_course     l WHERE l.course_code = c.course_code)
          AND NOT EXISTS (SELECT 1 FROM project_course p WHERE p.course_code = c.course_code)"""),
]

DEMO_CHECK = """
    SELECT count(*) FROM offering o
    WHERE o.semester = %(demo)s
      AND o.seats_left <> o.capacity - (SELECT count(*) FROM registration r
                                        WHERE r.offering_id = o.offering_id)"""

TABLE_COUNTS = ["student", "student_phone", "faculty", "course", "theory_course", "lab_course",
                "project_course", "prerequisite", "completed_course", "slot", "slot_timing",
                "offering", "registration", "waitlist"]


def profile(conn, report: list[str]) -> None:
    """Headline numbers and a two-panel chart of credits and seat fill."""
    report.append("Row counts")
    for table in TABLE_COUNTS:
        n = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]   # fixed names only
        report.append(f"  {table:<18} {n:>9,}")

    seats, taken = conn.execute(
        "SELECT sum(capacity), sum(capacity - seats_left) FROM offering WHERE semester <> %s",
        (DEMO_SEMESTER,)).fetchone()
    full = conn.execute("SELECT count(*) FROM offering WHERE seats_left = 0 AND semester <> %s",
                        (DEMO_SEMESTER,)).fetchone()[0]
    null_venues = conn.execute("SELECT count(*) - count(venue) FROM offering").fetchone()[0]
    credits = [r[0] for r in conn.execute(
        "SELECT total_credits FROM v_student_credits v "
        "JOIN student s ON s.reg_no = v.reg_no WHERE s.programme <> 'BOT'").fetchall()]
    min_c, max_c = conn.execute("SELECT min_credits, max_credits FROM settings").fetchone()
    below = sum(1 for c in credits if c < min_c)
    fills = [float(r[0]) for r in conn.execute(
        "SELECT fill_pct FROM v_admin_seat_fill WHERE semester <> %s", (DEMO_SEMESTER,)).fetchall()]

    report.append("")
    report.append(f"Seats {seats:,}, taken {taken:,} ({100 * taken / seats:.1f}% full); "
                  f"{full:,} offerings full; {null_venues} venues not yet allotted (NULL)")
    if credits:
        report.append(f"Credits per student: mean {sum(credits) / len(credits):.1f}, "
                      f"min {min(credits)}, max {max(credits)}; "
                      f"{below:,} students below the minimum of {min_c}")

    fig, (left, right) = charts.figure(ncols=2, width=11, height=4)
    # Bin edges at x.5 so each bar is centred on a whole number of credits.
    counts, _, _ = left.hist(credits, bins=[x - 0.5 for x in range(0, max_c + 3)],
                             color=charts.BLUE, rwidth=0.8)
    left.set_ylim(0, max(counts) * 1.18)            # headroom for the labels
    left.set_xlim(min(credits) - 2, max_c + 3)
    left.set_xticks(range(min(credits) - 1, max_c + 3, 3))   # whole-credit ticks
    for x, text in ((min_c - 0.5, f"min {min_c}"), (max_c + 0.5, f"max {max_c}")):
        left.axvline(x, color=charts.INK_2, linewidth=1)
        left.annotate(text, xy=(x, 1), xycoords=("data", "axes fraction"), xytext=(4, -4),
                      textcoords="offset points", va="top", color=charts.INK_2)
    left.set_title("Registered credits per student")
    left.set_xlabel("credits this semester")
    left.set_ylabel("students")
    right.hist(fills, bins=range(0, 105, 5), color=charts.BLUE, rwidth=0.8)
    right.set_title("How full each offering is")
    right.set_xlabel("seats taken (%)")
    right.set_ylabel("offerings")
    report.append(f"Chart: {charts.save(fig, 'data_profile.png')}")


def run() -> int:
    report = ["SlotRush data check", ""]
    failures = 0
    with pg_connect() as conn:
        for description, query in CHECKS:
            violations = conn.execute(query, {"demo": DEMO_SEMESTER}).fetchone()[0]
            verdict = "PASS" if violations == 0 else "FAIL"
            failures += violations != 0
            report.append(f"[{verdict}] {description}  (violations: {violations})")

        demo_off = conn.execute(DEMO_CHECK, {"demo": DEMO_SEMESTER}).fetchone()[0]
        report.append("")
        report.append(f"DEMO semester: {demo_off} offering(s) with seat counts out of line "
                      "(expected after the lost-update demo; real data is unaffected).")
        report.append("")
        profile(conn, report)

    report.append("")
    report.append("Result: " + ("all checks PASS" if failures == 0 else f"{failures} check(s) FAIL"))
    text = "\n".join(report)
    print(text)
    REPORT_FILE.write_text(text + "\n", encoding="utf-8")
    print(f"Saved to results/{REPORT_FILE.name}")
    return 0 if failures == 0 else 1
