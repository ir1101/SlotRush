"""Constraints, the specialisation, the weak entity, NULL behaviour and the views."""
import psycopg
import pytest

from .fixtures import S1, S2, S3

errors = psycopg.errors


def fails_with(db, error, sql, params=None):
    """Assert that sql raises error. The savepoint keeps the test transaction usable."""
    with pytest.raises(error):
        with db.transaction():
            db.execute(sql, params)


# --------------------------------------------------------------------------- CHECK and keys

def test_seats_left_cannot_go_below_zero(db):
    fails_with(db, errors.CheckViolation,
               "UPDATE offering SET seats_left = -1 WHERE offering_id = 101")


def test_seats_left_cannot_exceed_capacity(db):
    fails_with(db, errors.CheckViolation,
               "UPDATE offering SET seats_left = capacity + 1 WHERE offering_id = 101")


def test_reg_no_format_is_checked(db):
    fails_with(db, errors.CheckViolation,
               "INSERT INTO student VALUES ('bad', 'A', 'B', 'BCE', 2024, 'x@y.z')")


def test_settings_has_only_one_row(db):
    fails_with(db, errors.UniqueViolation,
               "INSERT INTO settings (min_credits, max_credits, current_semester) "
               "VALUES (10, 20, 'X')")


def test_min_credits_cannot_exceed_max(db):
    fails_with(db, errors.CheckViolation, "UPDATE settings SET min_credits = 30")


def test_student_phone_is_multivalued_but_not_repeated(db):
    db.execute("INSERT INTO student_phone VALUES (%s, '+919000000001')", (S1,))
    assert db.execute("SELECT count(*) FROM student_phone WHERE reg_no = %s",
                      (S1,)).fetchone()[0] == 2
    fails_with(db, errors.UniqueViolation,
               "INSERT INTO student_phone VALUES (%s, '+919000000001')", (S1,))


def test_registration_needs_existing_student(db):
    fails_with(db, errors.ForeignKeyViolation,
               "INSERT INTO registration (offering_id, reg_no) VALUES (101, '99ZZZ9999')")


# --------------------------------------------------------------------------- specialisation

def test_disjoint_lab_course_cannot_get_theory_row(db):
    # The theory_course row defaults to course_type 'THEORY', but BCSE101P is a LAB
    # course, so the composite foreign key (course_code, 'THEORY') finds no parent.
    fails_with(db, errors.ForeignKeyViolation,
               "INSERT INTO theory_course (course_code, lecture_hours) VALUES ('BCSE101P', 3)")


def test_disjoint_subtype_column_is_pinned(db):
    fails_with(db, errors.CheckViolation,
               "INSERT INTO theory_course (course_code, course_type, lecture_hours) "
               "VALUES ('BCSE101P', 'LAB', 3)")


def test_course_type_cannot_change_while_subtype_row_exists(db):
    fails_with(db, errors.ForeignKeyViolation,
               "UPDATE course SET course_type = 'PROJECT' WHERE course_code = 'BCSE101L'")


def test_total_course_without_subtype_row_fails_at_commit(db):
    db.execute("INSERT INTO course VALUES ('BCSE999L', 'Orphan', 3, 'THEORY')")
    # The trigger is deferred to COMMIT. SET CONSTRAINTS ... IMMEDIATE runs it now.
    fails_with(db, errors.IntegrityConstraintViolation, "SET CONSTRAINTS ALL IMMEDIATE")


def test_total_course_with_subtype_row_passes(db):
    db.execute("INSERT INTO course VALUES ('BCSE998L', 'Fine', 3, 'THEORY')")
    db.execute("INSERT INTO theory_course (course_code, lecture_hours) VALUES ('BCSE998L', 3)")
    db.execute("SET CONSTRAINTS ALL IMMEDIATE")          # no error


def test_total_deleting_subtype_row_fails_at_commit(db):
    db.execute("DELETE FROM project_course WHERE course_code = 'BCSE491J'")
    fails_with(db, errors.IntegrityConstraintViolation, "SET CONSTRAINTS ALL IMMEDIATE")


def test_lab_course_cannot_use_theory_slot(db):
    fails_with(db, errors.CheckViolation,
               "INSERT INTO offering (course_code, faculty_id, slot_id, semester, capacity, seats_left) "
               "VALUES ('BCSE101P', 1001, 'T02', 'FALL2026', 10, 10)")


def test_theory_course_cannot_use_lab_slot(db):
    fails_with(db, errors.CheckViolation,
               "INSERT INTO offering (course_code, faculty_id, slot_id, semester, capacity, seats_left) "
               "VALUES ('BCSE101L', 1001, 'L02', 'FALL2026', 10, 10)")


# --------------------------------------------------------------------------- recursive relationship

def test_course_cannot_be_its_own_prerequisite(db):
    fails_with(db, errors.CheckViolation,
               "INSERT INTO prerequisite VALUES ('BCSE101L', 'BCSE101L')")


# --------------------------------------------------------------------------- weak entity

def test_reference_timetable_shape(db):
    rows = db.execute("SELECT slot_kind, count(DISTINCT s.slot_id), count(*) "
                      "FROM slot s JOIN slot_timing t USING (slot_id) "
                      "GROUP BY slot_kind ORDER BY slot_kind").fetchall()
    # 20 lab slots x 2 periods, 16 theory slots covering 40 cells
    assert rows == [("LAB", 20, 40), ("THEORY", 16, 40)]


def test_slot_timing_dies_with_its_slot(db):
    db.execute("INSERT INTO slot VALUES ('X99', 'THEORY')")
    db.execute("INSERT INTO slot_timing VALUES ('X99', 1, 1), ('X99', 2, 1)")
    db.execute("DELETE FROM slot WHERE slot_id = 'X99'")
    assert db.execute("SELECT count(*) FROM slot_timing WHERE slot_id = 'X99'").fetchone()[0] == 0


def test_slot_timing_partial_key_is_unique_per_slot(db):
    fails_with(db, errors.UniqueViolation, "INSERT INTO slot_timing VALUES ('T01', 1, 1)")


# --------------------------------------------------------------------------- NULL venue

def test_null_venues_never_conflict_in_unique(db):
    # 102 already has venue NULL in T03; a second NULL-venue class in T03 is fine.
    db.execute("INSERT INTO offering (course_code, faculty_id, slot_id, semester, venue, capacity, seats_left) "
               "VALUES ('BMAT101L', 1002, 'T03', 'FALL2026', NULL, 10, 10)")


def test_same_real_venue_in_same_slot_conflicts(db):
    fails_with(db, errors.UniqueViolation,
               "INSERT INTO offering (course_code, faculty_id, slot_id, semester, venue, capacity, seats_left) "
               "VALUES ('BMAT101L', 1002, 'T01', 'FALL2026', 'SJT101', 10, 10)")


def test_count_star_counts_nulls_count_column_does_not(db):
    star, venues = db.execute("SELECT count(*), count(venue) FROM offering").fetchone()
    assert (star, venues) == (7, 2)


def test_equals_null_is_never_true(db):
    assert db.execute("SELECT count(*) FROM offering WHERE venue = NULL").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM offering WHERE venue IS NULL").fetchone()[0] == 5


def test_not_in_with_a_null_returns_nothing(db):
    # 'MB999' is in neither list, yet NOT IN returns no row, because the NULL in
    # the list makes "venue <> NULL" unknown, and unknown is not true.
    not_in = db.execute("SELECT count(*) FROM (VALUES ('MB999')) AS v(room) "
                        "WHERE room NOT IN (SELECT venue FROM offering)").fetchone()[0]
    not_exists = db.execute("SELECT count(*) FROM (VALUES ('MB999')) AS v(room) "
                            "WHERE NOT EXISTS (SELECT 1 FROM offering o WHERE o.venue = v.room)"
                            ).fetchone()[0]
    assert (not_in, not_exists) == (0, 1)


# --------------------------------------------------------------------------- views

def test_views_are_security_invoker(db):
    rows = db.execute("""
        SELECT c.relname, c.reloptions
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'slotrush' AND c.relkind = 'v' ORDER BY c.relname
    """).fetchall()
    assert [r[0] for r in rows] == ["v_admin_seat_fill", "v_faculty_class_list",
                                    "v_student_credits", "v_student_timetable"]
    assert all(r[1] == ["security_invoker=true"] for r in rows)


def test_student_credits_is_derived_from_registrations(db):
    db.execute("SELECT register(%s, 101)", (S1,))   # 3 credits
    db.execute("SELECT register(%s, 105)", (S1,))   # 4 credits
    row = db.execute("SELECT total_credits, courses FROM v_student_credits WHERE reg_no = %s",
                     (S1,)).fetchone()
    assert row == (7, 2)


def test_student_with_no_registrations_has_zero_credits(db):
    row = db.execute("SELECT total_credits, courses FROM v_student_credits WHERE reg_no = %s",
                     (S3,)).fetchone()
    assert row == (0, 0)                             # COALESCE turned NULL into 0


def test_timetable_has_one_row_per_meeting(db):
    db.execute("SELECT register(%s, 101)", (S1,))   # T01: 3 meetings
    db.execute("SELECT register(%s, 106)", (S1,))   # T09: 2 meetings
    rows = db.execute("SELECT day, period, slot_id FROM v_student_timetable "
                      "WHERE reg_no = %s ORDER BY day, period", (S1,)).fetchall()
    assert rows == [(1, 1, "T01"), (2, 1, "T09"), (3, 1, "T01"), (4, 1, "T09"), (5, 1, "T01")]


def test_admin_seat_fill_counts_taken_and_waitlisted(db):
    db.execute("SELECT register(%s, 105)", (S1,))
    db.execute("SELECT register(%s, 105)", (S2,))   # FULL -> waitlisted
    row = db.execute("SELECT capacity, seats_taken, fill_pct, waitlisted "
                     "FROM v_admin_seat_fill WHERE offering_id = 105").fetchone()
    assert row == (1, 1, 100.0, 1)


def test_faculty_class_list(db):
    db.execute("SELECT register(%s, 101)", (S1,))
    db.execute("SELECT register(%s, 105)", (S2,))
    rows = db.execute("SELECT faculty_id, offering_id, reg_no FROM v_faculty_class_list "
                      "ORDER BY offering_id").fetchall()
    assert rows == [(1001, 101, S1), (1002, 105, S2)]
