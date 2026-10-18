"""A tiny hand-made dataset for the rule and security tests.

Timetable reminder (see sql/02_reference_data.sql):
  T01 = Mon/Wed/Fri period 1      T03 = Mon/Wed/Fri period 3
  T04 = Mon/Wed/Fri period 4      T05, T06 = periods 5 and 6 on Mon/Wed/Fri
  T09 = Tue/Thu period 1
  L01 = Monday periods 1-2, so it CLASHES with T01 (and T02)

Offerings (all in FALL2026):
  101  BCSE101L theory 3 cr  slot T01  capacity 2  venue SJT101
  102  BCSE101L theory 3 cr  slot T03  capacity 2  (second offering of the same course)
  103  BCSE102L theory 4 cr  slot T04  capacity 5  (needs BCSE101L completed)
  104  BCSE101P lab    1 cr  slot L01  capacity 5  (clashes with 101)
  105  BMAT101L theory 4 cr  slot T05  capacity 1  (fills up after one student)
  106  BCSE491J project 3 cr slot T09  capacity 5
  107  BMAT101L theory 4 cr  slot T06  capacity 5  (other offering of 105's course)
  Faculty 1001 teaches 101-104, faculty 1002 teaches 105-107.

Students 21BCE0001 .. 21BCE0005. Only 21BCE0002 has completed BCSE101L.
"""

STUDENTS = ["21BCE0001", "21BCE0002", "21BCE0003", "21BCE0004", "21BCE0005"]
S1, S2, S3, S4, S5 = STUDENTS


def insert_fixture(conn) -> None:
    """Insert the dataset using the given connection (the caller decides commit/rollback)."""
    conn.execute("""
        INSERT INTO faculty (faculty_id, first_name, last_name, school, email) VALUES
            (1001, 'Ada',  'Lovelace', 'SCOPE', 'ada@vit.example'),
            (1002, 'Alan', 'Turing',   'SAS',   'alan@vit.example')
    """)
    conn.execute("""
        INSERT INTO course (course_code, title, credits, course_type) VALUES
            ('BCSE101L', 'Programming in C',          3, 'THEORY'),
            ('BCSE102L', 'Data Structures',           4, 'THEORY'),
            ('BCSE101P', 'Programming in C Lab',      1, 'LAB'),
            ('BCSE491J', 'Capstone Project',          3, 'PROJECT'),
            ('BMAT101L', 'Calculus',                  4, 'THEORY')
    """)
    conn.execute("""
        INSERT INTO theory_course (course_code, lecture_hours, tutorial_hours) VALUES
            ('BCSE101L', 3, 0), ('BCSE102L', 3, 1), ('BMAT101L', 3, 1)
    """)
    conn.execute("INSERT INTO lab_course (course_code, lab_hours, lab_room_type) "
                 "VALUES ('BCSE101P', 2, 'Computer')")
    conn.execute("INSERT INTO project_course (course_code, max_team_size, deliverable) "
                 "VALUES ('BCSE491J', 3, 'Report and demo')")
    conn.execute("INSERT INTO prerequisite (course_code, prereq_code) VALUES ('BCSE102L', 'BCSE101L')")

    conn.execute("""
        INSERT INTO offering (offering_id, course_code, faculty_id, slot_id, semester,
                              venue, capacity, seats_left) VALUES
            (101, 'BCSE101L', 1001, 'T01', 'FALL2026', 'SJT101', 2, 2),
            (102, 'BCSE101L', 1001, 'T03', 'FALL2026', NULL,     2, 2),
            (103, 'BCSE102L', 1001, 'T04', 'FALL2026', NULL,     5, 5),
            (104, 'BCSE101P', 1001, 'L01', 'FALL2026', 'SJTL01', 5, 5),
            (105, 'BMAT101L', 1002, 'T05', 'FALL2026', NULL,     1, 1),
            (106, 'BCSE491J', 1002, 'T09', 'FALL2026', NULL,     5, 5),
            (107, 'BMAT101L', 1002, 'T06', 'FALL2026', NULL,     5, 5)
    """)

    for i, reg_no in enumerate(STUDENTS, start=1):
        conn.execute(
            "INSERT INTO student (reg_no, first_name, last_name, programme, admit_year, email) "
            "VALUES (%s, %s, %s, 'BCE', 2021, %s)",
            (reg_no, f"Student{i}", f"Test{i}", f"{reg_no.lower()}@vitstudent.example"),
        )
        conn.execute("INSERT INTO student_phone (reg_no, phone) VALUES (%s, %s)",
                     (reg_no, f"+9198765432{i:02d}"))

    conn.execute("INSERT INTO completed_course (reg_no, course_code, semester, grade) "
                 "VALUES (%s, 'BCSE101L', 'FALL2025', 'A')", (S2,))


def clear_fixture(conn) -> None:
    """Remove all rows except the reference data (slots and settings)."""
    conn.execute("""
        TRUNCATE registration, waitlist, offering, completed_course, prerequisite,
                 theory_course, lab_course, project_course, course,
                 student_phone, student, faculty
    """)
    conn.execute("UPDATE settings SET min_credits = 16, max_credits = 27")
