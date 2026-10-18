"""Roles, GRANTs and row-level security.

The test connection logs in as the superuser, which BYPASSES row-level security.
So each test first runs SET LOCAL ROLE to become an ordinary role. LOCAL means
the change ends with the test's transaction, which is rolled back anyway.
"""
import psycopg
import pytest

from .fixtures import S1, S2

errors = psycopg.errors


@pytest.fixture
def registered(db):
    """S1 in offering 101 (faculty 1001) and S2 in 105 (faculty 1002), made as superuser."""
    db.execute("SELECT register(%s, 101)", (S1,))
    db.execute("SELECT register(%s, 105)", (S2,))
    return db


def become(db, role, **settings):
    db.execute(f"SET LOCAL ROLE {role}")          # role names are fixed strings, not user input
    for name, value in settings.items():
        # set_config(name, value, is_local = true) is the function form of SET LOCAL.
        db.execute("SELECT set_config(%s, %s, true)", (f"app.{name}", value))


def test_superuser_bypasses_rls(registered):
    # This is why RLS must be tested as a normal role.
    assert registered.execute("SELECT count(*) FROM registration").fetchone()[0] == 2


def test_student_sees_only_own_registrations(registered):
    become(registered, "student_role", reg_no=S1)
    rows = registered.execute("SELECT reg_no, offering_id FROM registration").fetchall()
    assert rows == [(S1, 101)]


def test_student_sees_only_own_rows_through_the_view(registered):
    become(registered, "student_role", reg_no=S1)
    reg_nos = registered.execute("SELECT DISTINCT reg_no FROM v_student_timetable").fetchall()
    assert reg_nos == [(S1,)]


def test_student_without_app_reg_no_sees_nothing(registered):
    become(registered, "student_role")
    assert registered.execute("SELECT count(*) FROM registration").fetchone()[0] == 0


def test_student_sees_only_own_student_row(registered):
    become(registered, "student_role", reg_no=S1)
    assert registered.execute("SELECT reg_no FROM student").fetchall() == [(S1,)]
    assert registered.execute("SELECT reg_no, total_credits FROM v_student_credits").fetchall() == [(S1, 3)]


def test_student_cannot_read_phone_numbers(registered):
    become(registered, "student_role", reg_no=S1)
    with pytest.raises(errors.InsufficientPrivilege):
        registered.execute("SELECT * FROM student_phone")


def test_student_can_register_themselves(registered):
    become(registered, "student_role", reg_no=S1)
    assert registered.execute("SELECT register(%s, 106)", (S1,)).fetchone()[0] == "OK"


def test_student_cannot_register_someone_else(registered):
    become(registered, "student_role", reg_no=S1)
    with pytest.raises(errors.InsufficientPrivilege, match="cannot act for"):
        registered.execute("SELECT register(%s, 106)", (S2,))


def test_student_cannot_change_seats_directly(registered):
    become(registered, "student_role", reg_no=S1)
    with pytest.raises(errors.InsufficientPrivilege):
        registered.execute("UPDATE offering SET seats_left = 99 WHERE offering_id = 101")


def test_student_cannot_call_internal_check_function(registered):
    become(registered, "student_role", reg_no=S1)
    with pytest.raises(errors.InsufficientPrivilege):
        registered.execute("SELECT check_add(%s, 101)", (S1,))


def test_faculty_sees_only_own_class_list(registered):
    become(registered, "faculty_role", faculty_id="1001")
    rows = registered.execute("SELECT offering_id, reg_no FROM v_faculty_class_list").fetchall()
    assert rows == [(101, S1)]


def test_faculty_cannot_read_student_email(registered):
    become(registered, "faculty_role", faculty_id="1001")
    with pytest.raises(errors.InsufficientPrivilege):
        registered.execute("SELECT email FROM student")


def test_faculty_cannot_register_students(registered):
    become(registered, "faculty_role", faculty_id="1001")
    with pytest.raises(errors.InsufficientPrivilege):
        registered.execute("SELECT register(%s, 106)", (S1,))


def test_admin_sees_everything(registered):
    become(registered, "admin_role")
    assert registered.execute("SELECT count(*) FROM registration").fetchone()[0] == 2
    assert registered.execute("SELECT count(*) FROM v_admin_seat_fill").fetchone()[0] == 7


def test_admin_can_allot_a_venue_but_not_change_seats(registered):
    become(registered, "admin_role")
    registered.execute("UPDATE offering SET venue = 'TT101' WHERE offering_id = 102")
    with pytest.raises(errors.InsufficientPrivilege):
        registered.execute("UPDATE offering SET seats_left = 0 WHERE offering_id = 102")
