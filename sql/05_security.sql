-- =============================================================================
-- 05_security.sql : roles, GRANTs and row-level security (RLS)
--
-- Three group roles (NOLOGIN). A session becomes one of them with SET ROLE and
-- says who it is with a custom setting:
--     student session:  SET ROLE student_role;  SET app.reg_no = '23BCE0042';
--     faculty session:  SET ROLE faculty_role;  SET app.faculty_id = '1001';
--     admin session:    SET ROLE admin_role;
--
-- Superusers and table owners BYPASS row-level security, so the tests use
-- SET ROLE to become a normal role before checking it.
-- =============================================================================

-- Roles belong to the whole server, not one database, so create them only once.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'student_role') THEN
        CREATE ROLE student_role NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'faculty_role') THEN
        CREATE ROLE faculty_role NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'admin_role') THEN
        CREATE ROLE admin_role NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA slotrush TO student_role, faculty_role, admin_role;


-- -----------------------------------------------------------------------------
-- Functions are executable by everyone (PUBLIC) by default. Take that away,
-- then give it back only where it belongs.
-- -----------------------------------------------------------------------------
REVOKE ALL ON FUNCTION assert_self(varchar)                    FROM PUBLIC;
REVOKE ALL ON FUNCTION check_add(varchar, integer)             FROM PUBLIC;
REVOKE ALL ON FUNCTION register(varchar, integer)              FROM PUBLIC;
REVOKE ALL ON FUNCTION drop_course(varchar, integer)           FROM PUBLIC;
REVOKE ALL ON FUNCTION swap_course(varchar, integer, integer)  FROM PUBLIC;

GRANT EXECUTE ON FUNCTION register(varchar, integer),
                          drop_course(varchar, integer),
                          swap_course(varchar, integer, integer)
      TO student_role, admin_role;


-- -----------------------------------------------------------------------------
-- student_role: own timetable and own credits.
-- Because the views are security_invoker, the role also needs SELECT on the
-- tables underneath. RLS below stops it seeing other students' rows.
-- -----------------------------------------------------------------------------
GRANT SELECT ON v_student_timetable, v_student_credits TO student_role;
GRANT SELECT ON registration, student, offering, course, faculty, slot_timing, settings
      TO student_role;
-- No access to student_phone, waitlist or completed_course.


-- -----------------------------------------------------------------------------
-- faculty_role: own class lists. Only the name columns of student.
-- -----------------------------------------------------------------------------
GRANT SELECT ON v_faculty_class_list TO faculty_role;
GRANT SELECT ON registration, offering, course TO faculty_role;
GRANT SELECT (reg_no, first_name, last_name) ON student TO faculty_role;


-- -----------------------------------------------------------------------------
-- admin_role: reads everything, may allot venues and change the credit limits.
-- -----------------------------------------------------------------------------
GRANT SELECT ON ALL TABLES IN SCHEMA slotrush TO admin_role;   -- includes the views
GRANT UPDATE (venue) ON offering TO admin_role;
GRANT UPDATE (min_credits, max_credits) ON settings TO admin_role;


-- -----------------------------------------------------------------------------
-- Row-level security on registration.
-- With RLS enabled, a role sees no rows at all unless some policy lets it.
-- current_setting('app.reg_no', true) returns NULL when the setting does not
-- exist (the "true" means "missing is OK"), and reg_no = NULL is never true,
-- so a student session that forgot to set app.reg_no sees nothing.
-- -----------------------------------------------------------------------------
ALTER TABLE registration ENABLE ROW LEVEL SECURITY;

CREATE POLICY registration_own_rows ON registration
    FOR SELECT TO student_role
    USING (reg_no = current_setting('app.reg_no', true));

CREATE POLICY registration_own_classes ON registration
    FOR SELECT TO faculty_role
    USING (offering_id IN (
        SELECT offering_id FROM offering
        WHERE faculty_id = NULLIF(current_setting('app.faculty_id', true), '')::integer
    ));

CREATE POLICY registration_admin_all ON registration
    FOR SELECT TO admin_role
    USING (true);


-- -----------------------------------------------------------------------------
-- Row-level security on student, needed because security_invoker views make
-- student_role hold SELECT on the student table itself.
-- -----------------------------------------------------------------------------
ALTER TABLE student ENABLE ROW LEVEL SECURITY;

CREATE POLICY student_self ON student
    FOR SELECT TO student_role
    USING (reg_no = current_setting('app.reg_no', true));

-- Faculty may read every student's name (the column GRANT hides the rest).
CREATE POLICY student_names_for_faculty ON student
    FOR SELECT TO faculty_role
    USING (true);

CREATE POLICY student_admin_all ON student
    FOR SELECT TO admin_role
    USING (true);
