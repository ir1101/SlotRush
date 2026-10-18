"""register(), drop_course() and swap_course(): every rule and every status code."""
import psycopg
import pytest

from .fixtures import S1, S2


def call(db, func, *args):
    """Run SELECT func(args) and return the status text."""
    placeholders = ", ".join(["%s"] * len(args))
    return db.execute(f"SELECT {func}({placeholders})", args).fetchone()[0]


def seats_left(db, offering_id):
    return db.execute("SELECT seats_left FROM offering WHERE offering_id = %s",
                      (offering_id,)).fetchone()[0]


def is_registered(db, reg_no, offering_id):
    return db.execute("SELECT EXISTS (SELECT 1 FROM registration "
                      "WHERE reg_no = %s AND offering_id = %s)",
                      (reg_no, offering_id)).fetchone()[0]


def set_credit_limits(db, min_credits, max_credits):
    db.execute("UPDATE settings SET min_credits = %s, max_credits = %s",
               (min_credits, max_credits))


# --------------------------------------------------------------------------- register

def test_register_ok_takes_a_seat(db):
    assert call(db, "register", S1, 101) == "OK"
    assert seats_left(db, 101) == 1
    assert is_registered(db, S1, 101)


def test_register_same_offering_twice_is_duplicate(db):
    call(db, "register", S1, 101)
    assert call(db, "register", S1, 101) == "DUPLICATE"
    assert seats_left(db, 101) == 1          # no second seat taken


def test_register_other_offering_of_same_course_is_duplicate(db):
    call(db, "register", S1, 101)            # BCSE101L in T01
    assert call(db, "register", S1, 102) == "DUPLICATE"   # BCSE101L in T03


def test_register_clashing_slot_is_clash(db):
    call(db, "register", S1, 101)            # T01 uses Monday period 1
    assert call(db, "register", S1, 104) == "CLASH"       # L01 uses Monday periods 1-2
    assert seats_left(db, 104) == 5


def test_register_without_prerequisite_is_prereq(db):
    assert call(db, "register", S1, 103) == "PREREQ"      # S1 has not completed BCSE101L


def test_register_with_prerequisite_completed_is_ok(db):
    assert call(db, "register", S2, 103) == "OK"          # S2 completed BCSE101L


def test_register_over_max_credits_is_credit_limit(db):
    set_credit_limits(db, 1, 5)
    assert call(db, "register", S1, 101) == "OK"           # 3 credits
    assert call(db, "register", S1, 105) == "CREDIT_LIMIT" # 3 + 4 = 7 > 5


def test_register_exactly_at_max_credits_is_ok(db):
    set_credit_limits(db, 1, 7)
    call(db, "register", S1, 101)                          # 3 credits
    assert call(db, "register", S1, 105) == "OK"           # 3 + 4 = 7, allowed


def test_register_when_full_is_full_and_waitlists(db):
    assert call(db, "register", S1, 105) == "OK"           # capacity 1
    assert call(db, "register", S2, 105) == "FULL"
    assert seats_left(db, 105) == 0
    assert not is_registered(db, S2, 105)
    waitlisted = db.execute("SELECT reg_no FROM waitlist WHERE offering_id = 105").fetchall()
    assert waitlisted == [(S2,)]


def test_register_full_twice_waitlists_once(db):
    call(db, "register", S1, 105)
    call(db, "register", S2, 105)
    assert call(db, "register", S2, 105) == "FULL"
    count = db.execute("SELECT count(*) FROM waitlist WHERE offering_id = 105").fetchone()[0]
    assert count == 1


def test_register_rule_order_clash_before_full(db):
    # 104 would also be FULL, but the clash rule is checked first (rule 3 before rule 6).
    db.execute("UPDATE offering SET seats_left = 0 WHERE offering_id = 104")
    call(db, "register", S1, 101)
    assert call(db, "register", S1, 104) == "CLASH"


def test_register_unknown_student_raises(db):
    with pytest.raises(psycopg.errors.RaiseException, match="unknown student"):
        with db.transaction():
            call(db, "register", "99XXX9999", 101)


def test_register_unknown_offering_raises(db):
    with pytest.raises(psycopg.errors.RaiseException, match="unknown offering"):
        with db.transaction():
            call(db, "register", S1, 999)


# --------------------------------------------------------------------------- drop_course

def test_drop_course_gives_the_seat_back(db):
    call(db, "register", S1, 101)
    assert call(db, "drop_course", S1, 101) == "OK"
    assert seats_left(db, 101) == 2
    assert not is_registered(db, S1, 101)


def test_drop_course_not_registered(db):
    assert call(db, "drop_course", S1, 101) == "NOT_REGISTERED"
    assert seats_left(db, 101) == 2


# --------------------------------------------------------------------------- swap_course

def test_swap_ok_moves_the_registration(db):
    call(db, "register", S1, 105)                          # BMAT101L in T05
    assert call(db, "swap_course", S1, 105, 107) == "OK"   # BMAT101L in T06
    assert not is_registered(db, S1, 105) and is_registered(db, S1, 107)
    assert seats_left(db, 105) == 1 and seats_left(db, 107) == 4


def assert_unchanged_after_failed_swap(db, reg_no, from_id, to_id, seats_from, seats_to):
    assert is_registered(db, reg_no, from_id)
    assert not is_registered(db, reg_no, to_id)
    assert seats_left(db, from_id) == seats_from
    assert seats_left(db, to_id) == seats_to


def test_swap_prereq_failure_changes_nothing(db):
    call(db, "register", S1, 101)
    assert call(db, "swap_course", S1, 101, 103) == "PREREQ"
    assert_unchanged_after_failed_swap(db, S1, 101, 103, 1, 5)


def test_swap_to_full_offering_is_full_and_not_waitlisted(db):
    call(db, "register", S2, 105)                          # S2 fills 105
    call(db, "register", S1, 107)
    assert call(db, "swap_course", S1, 107, 105) == "FULL"
    assert_unchanged_after_failed_swap(db, S1, 107, 105, 4, 0)
    assert db.execute("SELECT count(*) FROM waitlist").fetchone()[0] == 0


def test_swap_clash_changes_nothing(db):
    call(db, "register", S1, 101)                          # T01
    call(db, "register", S1, 106)                          # T09
    # Moving 106 -> 104 (L01) clashes with 101, which S1 keeps.
    assert call(db, "swap_course", S1, 106, 104) == "CLASH"
    assert_unchanged_after_failed_swap(db, S1, 106, 104, 4, 5)


def test_swap_credit_limit_changes_nothing(db):
    set_credit_limits(db, 1, 6)
    call(db, "register", S1, 101)                          # 3 credits
    call(db, "register", S1, 106)                          # 3 credits -> 6
    assert call(db, "swap_course", S1, 106, 105) == "CREDIT_LIMIT"   # 3 + 4 = 7 > 6
    assert_unchanged_after_failed_swap(db, S1, 106, 105, 4, 1)


def test_swap_duplicate_changes_nothing(db):
    call(db, "register", S1, 101)                          # BCSE101L
    call(db, "register", S1, 105)                          # BMAT101L
    # Moving 105 -> 102 would give S1 a second BCSE101L.
    assert call(db, "swap_course", S1, 105, 102) == "DUPLICATE"
    assert_unchanged_after_failed_swap(db, S1, 105, 102, 0, 2)


def test_swap_not_registered(db):
    assert call(db, "swap_course", S1, 105, 107) == "NOT_REGISTERED"


def test_swap_same_offering_raises(db):
    call(db, "register", S1, 105)
    with pytest.raises(psycopg.errors.RaiseException, match="same offering"):
        with db.transaction():
            call(db, "swap_course", S1, 105, 105)
