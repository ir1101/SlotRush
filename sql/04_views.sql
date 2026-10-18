-- =============================================================================
-- 04_views.sql : external views (one per user group)
--
-- WITH (security_invoker = true): the view runs with the rights of the user
-- who QUERIES it, not the view owner. That keeps row-level security working
-- through the view, but it also means each role needs SELECT on every table
-- the view reads (granted in 05_security.sql).
-- =============================================================================


-- Student: my timetable, one row per class meeting.
CREATE VIEW v_student_timetable WITH (security_invoker = true) AS
SELECT r.reg_no,
       o.semester,
       t.day,
       t.period,
       o.slot_id,
       c.course_code,
       c.title,
       c.course_type,
       f.first_name || ' ' || f.last_name AS faculty_name,
       o.venue
FROM registration r
JOIN offering    o ON o.offering_id = r.offering_id
JOIN course      c ON c.course_code = o.course_code
JOIN faculty     f ON f.faculty_id  = o.faculty_id
JOIN slot_timing t ON t.slot_id     = o.slot_id;


-- Student: total registered credits this semester. This is the DERIVED
-- attribute: it is computed here every time and never stored.
-- LEFT JOINs keep students with no registrations; COALESCE turns their NULL
-- sum into 0 (SUM over no rows is NULL, not 0).
CREATE VIEW v_student_credits WITH (security_invoker = true) AS
SELECT s.reg_no,
       st.current_semester           AS semester,
       COALESCE(SUM(c.credits), 0)   AS total_credits,
       COUNT(c.course_code)          AS courses,
       st.min_credits,
       st.max_credits
FROM student s
CROSS JOIN settings st
LEFT JOIN registration r ON r.reg_no = s.reg_no
LEFT JOIN offering     o ON o.offering_id = r.offering_id
                        AND o.semester = st.current_semester
LEFT JOIN course       c ON c.course_code = o.course_code
GROUP BY s.reg_no, st.current_semester, st.min_credits, st.max_credits;


-- Faculty: the students in each of my classes.
CREATE VIEW v_faculty_class_list WITH (security_invoker = true) AS
SELECT o.faculty_id,
       o.offering_id,
       o.semester,
       o.course_code,
       c.title,
       o.slot_id,
       o.venue,
       s.reg_no,
       s.first_name,
       s.last_name,
       r.registered_at
FROM offering     o
JOIN course       c ON c.course_code = o.course_code
JOIN registration r ON r.offering_id = o.offering_id
JOIN student      s ON s.reg_no      = r.reg_no;


-- Admin: how full every offering is.
CREATE VIEW v_admin_seat_fill WITH (security_invoker = true) AS
SELECT o.offering_id,
       o.semester,
       o.course_code,
       o.slot_id,
       o.faculty_id,
       o.venue,
       o.capacity,
       o.seats_left,
       o.capacity - o.seats_left                                  AS seats_taken,
       round(100.0 * (o.capacity - o.seats_left) / o.capacity, 1) AS fill_pct,
       (SELECT count(*) FROM waitlist w WHERE w.offering_id = o.offering_id) AS waitlisted
FROM offering o;
