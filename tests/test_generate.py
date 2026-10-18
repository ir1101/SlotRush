"""The data generator obeys the same rules as register(), and is reproducible.

Uses a small scale so it runs in seconds. The timetable comes from the test
database, the single source of truth for slots.
"""
from collections import Counter

import pytest

from slotrush.db import pg_connect
from slotrush.generate import MAX_CREDITS, Scale, generate
from slotrush.load import read_timetable

SMALL = Scale(students=2_000, offerings=900, faculty=150)


@pytest.fixture(scope="module")
def timetable(test_db):
    with pg_connect(test_db) as conn:
        return read_timetable(conn)


@pytest.fixture(scope="module")
def data(timetable):
    return generate(*timetable, SMALL)


def test_sizes(data):
    assert len(data.students) == 2_000
    assert len(data.offerings) == 900
    assert len(data.faculty) == 150
    assert len(data.courses) == 600
    assert len(data.registrations) > 10_000


def test_same_seed_gives_identical_data(timetable, data):
    again = generate(*timetable, SMALL)
    assert again.registrations == data.registrations
    assert again.students == data.students


def test_no_offering_over_capacity(data):
    taken = Counter(r[0] for r in data.registrations)
    assert all(taken[o[0]] <= o[6] for o in data.offerings)


def test_no_duplicate_course_per_student(data):
    course_of = {o[0]: o[1] for o in data.offerings}
    pairs = Counter((r[1], course_of[r[0]]) for r in data.registrations)
    assert max(pairs.values()) == 1


def test_no_slot_clash(timetable, data):
    cells, _ = timetable
    slot_of = {o[0]: o[3] for o in data.offerings}
    used = {}
    for offering_id, reg_no, _ in data.registrations:
        for cell in cells[slot_of[offering_id]]:
            assert (reg_no, cell) not in used, f"{reg_no} clashes at {cell}"
            used[(reg_no, cell)] = offering_id


def test_credits_within_maximum(data):
    credits_of = {c[0]: c[2] for c in data.courses}
    course_of = {o[0]: o[1] for o in data.offerings}
    total = Counter()
    for offering_id, reg_no, _ in data.registrations:
        total[reg_no] += credits_of[course_of[offering_id]]
    assert max(total.values()) <= MAX_CREDITS


def test_prerequisites_completed(data):
    passed = {(row[0], row[1]) for row in data.completed}
    needs = {}
    for course, prereq in data.prerequisites:
        needs.setdefault(course, []).append(prereq)
    course_of = {o[0]: o[1] for o in data.offerings}
    for offering_id, reg_no, _ in data.registrations:
        for prereq in needs.get(course_of[offering_id], []):
            assert (reg_no, prereq) in passed


def test_faculty_never_in_two_overlapping_slots(timetable, data):
    cells, _ = timetable
    busy = set()
    for _, _, faculty_id, slot_id, *_ in data.offerings:
        for cell in cells[slot_id]:
            assert (faculty_id, cell) not in busy
            busy.add((faculty_id, cell))


def test_lab_courses_only_in_lab_slots(timetable, data):
    _, kind = timetable
    ctype = {c[0]: c[3] for c in data.courses}
    for _, code, _, slot_id, *_ in data.offerings:
        assert (ctype[code] == "LAB") == (kind[slot_id] == "LAB")


def test_emails_unique(data):
    emails = [s[5] for s in data.students]
    assert len(emails) == len(set(emails))
