-- =============================================================================
-- 03_functions.sql : business rules in PL/pgSQL
--
--   register(reg_no, offering_id)              -> OK | FULL | CLASH | CREDIT_LIMIT | PREREQ | DUPLICATE
--   drop_course(reg_no, offering_id)           -> OK | NOT_REGISTERED
--   swap_course(reg_no, from_offering, to_off) -> OK | FULL | CLASH | CREDIT_LIMIT | PREREQ
--                                                 | DUPLICATE | NOT_REGISTERED
--
-- Transactions: a function cannot COMMIT. It runs inside the CALLER's
-- transaction, and every row lock it takes is held until the caller commits
-- or rolls back. In autocommit mode each "SELECT register(...)" is one
-- transaction on its own.
--
-- Lock order: always the student row first, then offering rows in ascending
-- offering_id. Two transactions that follow the same order cannot deadlock.
-- =============================================================================


-- A student session sets app.reg_no (see 05_security.sql). If it is set, the
-- session may only act for that student. This is not authentication: any
-- session can SET app.reg_no, so it is only safe behind a trusted app layer.
CREATE FUNCTION assert_self(p_reg_no varchar) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_session_reg_no text := NULLIF(current_setting('app.reg_no', true), '');
BEGIN
    IF v_session_reg_no IS NOT NULL AND v_session_reg_no <> p_reg_no THEN
        RAISE EXCEPTION 'session for % cannot act for %', v_session_reg_no, p_reg_no
              USING ERRCODE = 'insufficient_privilege';
    END IF;
END $$;


-- Rules 2 to 5, shared by register() and swap_course() so there is only one
-- copy. The caller must already hold the locks. Returns 'OK' or the reason.
CREATE FUNCTION check_add(p_reg_no varchar, p_offering_id integer) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    v_offer        offering%ROWTYPE;
    v_credits      smallint;
    v_max_credits  smallint;
    v_current      integer;
BEGIN
    SELECT * INTO v_offer FROM offering WHERE offering_id = p_offering_id;
    SELECT credits INTO v_credits FROM course WHERE course_code = v_offer.course_code;

    -- Rule 2: the student already has this course this semester
    -- (the same offering, or another offering of the same course).
    IF EXISTS (
        SELECT 1
        FROM registration r
        JOIN offering o ON o.offering_id = r.offering_id
        WHERE r.reg_no = p_reg_no
          AND o.semester = v_offer.semester
          AND o.course_code = v_offer.course_code
    ) THEN
        RETURN 'DUPLICATE';
    END IF;

    -- Rule 3: slot clash. Some (day, period) of the new slot is already used
    -- by a slot the student is registered in this semester.
    IF EXISTS (
        SELECT 1
        FROM registration r
        JOIN offering    o     ON o.offering_id = r.offering_id
        JOIN slot_timing taken ON taken.slot_id = o.slot_id
        JOIN slot_timing wanted
             ON wanted.day = taken.day AND wanted.period = taken.period
        WHERE r.reg_no = p_reg_no
          AND o.semester = v_offer.semester
          AND wanted.slot_id = v_offer.slot_id
    ) THEN
        RETURN 'CLASH';
    END IF;

    -- Rule 4: every prerequisite of the course must be in CompletedCourse.
    IF EXISTS (
        SELECT 1
        FROM prerequisite p
        WHERE p.course_code = v_offer.course_code
          AND NOT EXISTS (
              SELECT 1 FROM completed_course c
              WHERE c.reg_no = p_reg_no AND c.course_code = p.prereq_code
          )
    ) THEN
        RETURN 'PREREQ';
    END IF;

    -- Rule 5: current credits this semester plus this course must not exceed the maximum.
    SELECT max_credits INTO v_max_credits FROM settings;
    SELECT COALESCE(SUM(c.credits), 0) INTO v_current
    FROM registration r
    JOIN offering o ON o.offering_id = r.offering_id
    JOIN course   c ON c.course_code = o.course_code
    WHERE r.reg_no = p_reg_no
      AND o.semester = v_offer.semester;

    IF v_current + v_credits > v_max_credits THEN
        RETURN 'CREDIT_LIMIT';
    END IF;

    RETURN 'OK';
END $$;


-- SECURITY DEFINER: runs with the owner's rights, so student_role only needs
-- EXECUTE, not UPDATE on offering. search_path is pinned so a caller cannot
-- slip in look-alike tables.
CREATE FUNCTION register(p_reg_no varchar, p_offering_id integer) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = slotrush, pg_temp AS $$
DECLARE
    v_seats_left  smallint;
    v_status      text;
BEGIN
    PERFORM assert_self(p_reg_no);

    -- Rule 1: lock the student row, then the offering row.
    -- Locking the student serialises one student's own concurrent requests,
    -- so the clash and credit checks below cannot race each other.
    PERFORM 1 FROM student WHERE reg_no = p_reg_no FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown student %', p_reg_no;
    END IF;

    SELECT seats_left INTO v_seats_left
    FROM offering WHERE offering_id = p_offering_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown offering %', p_offering_id;
    END IF;

    -- Rules 2 to 5
    v_status := check_add(p_reg_no, p_offering_id);
    IF v_status <> 'OK' THEN
        RETURN v_status;
    END IF;

    -- Rule 6: no seat left -> join the waitlist (once) and report FULL.
    IF v_seats_left = 0 THEN
        INSERT INTO waitlist (offering_id, reg_no)
        VALUES (p_offering_id, p_reg_no)
        ON CONFLICT DO NOTHING;
        RETURN 'FULL';
    END IF;

    -- Seat available: take it. We hold the row lock, so nobody else can
    -- change seats_left between our read and this write.
    UPDATE offering SET seats_left = seats_left - 1 WHERE offering_id = p_offering_id;
    INSERT INTO registration (offering_id, reg_no) VALUES (p_offering_id, p_reg_no);
    RETURN 'OK';
END $$;


CREATE FUNCTION drop_course(p_reg_no varchar, p_offering_id integer) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = slotrush, pg_temp AS $$
BEGIN
    PERFORM assert_self(p_reg_no);

    -- Same lock order as register(): student, then offering.
    PERFORM 1 FROM student WHERE reg_no = p_reg_no FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown student %', p_reg_no;
    END IF;
    PERFORM 1 FROM offering WHERE offering_id = p_offering_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown offering %', p_offering_id;
    END IF;

    DELETE FROM registration WHERE offering_id = p_offering_id AND reg_no = p_reg_no;
    IF NOT FOUND THEN
        RETURN 'NOT_REGISTERED';
    END IF;

    UPDATE offering SET seats_left = seats_left + 1 WHERE offering_id = p_offering_id;
    RETURN 'OK';
END $$;


CREATE FUNCTION swap_course(p_reg_no varchar, p_from integer, p_to integer) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = slotrush, pg_temp AS $$
DECLARE
    v_status      text;
    v_seats_left  smallint;
BEGIN
    PERFORM assert_self(p_reg_no);
    IF p_from = p_to THEN
        RAISE EXCEPTION 'swap_course: from and to are the same offering (%)', p_from;
    END IF;

    -- Lock the student first ...
    PERFORM 1 FROM student WHERE reg_no = p_reg_no FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown student %', p_reg_no;
    END IF;

    -- ... then both offerings in ascending id order, as two separate statements.
    -- Every swap in the system takes the lower id first, so two opposite swaps
    -- (P->Q and Q->P) queue up on the same row instead of deadlocking.
    PERFORM 1 FROM offering WHERE offering_id = LEAST(p_from, p_to) FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown offering %', LEAST(p_from, p_to);
    END IF;
    PERFORM 1 FROM offering WHERE offering_id = GREATEST(p_from, p_to) FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown offering %', GREATEST(p_from, p_to);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM registration
                   WHERE offering_id = p_from AND reg_no = p_reg_no) THEN
        RETURN 'NOT_REGISTERED';
    END IF;

    -- All or nothing. A BEGIN ... EXCEPTION block is a subtransaction
    -- (a savepoint): if anything inside fails, every change made inside it
    -- is undone, but the locks taken above are kept.
    BEGIN
        -- Drop first, so the checks below do not count the old offering.
        DELETE FROM registration WHERE offering_id = p_from AND reg_no = p_reg_no;
        UPDATE offering SET seats_left = seats_left + 1 WHERE offering_id = p_from;

        v_status := check_add(p_reg_no, p_to);
        IF v_status = 'OK' THEN
            SELECT seats_left INTO v_seats_left FROM offering WHERE offering_id = p_to;
            IF v_seats_left = 0 THEN
                v_status := 'FULL';         -- a failed swap does not join the waitlist
            END IF;
        END IF;

        IF v_status <> 'OK' THEN
            -- Our own SQLSTATE, caught just below. Raising it rolls back the drop.
            RAISE EXCEPTION 'swap failed: %', v_status USING ERRCODE = 'SR001';
        END IF;

        UPDATE offering SET seats_left = seats_left - 1 WHERE offering_id = p_to;
        INSERT INTO registration (offering_id, reg_no) VALUES (p_to, p_reg_no);
    EXCEPTION
        WHEN SQLSTATE 'SR001' THEN
            -- Back at the savepoint: the old registration is untouched.
            -- Local variables keep their values, so v_status is still the reason.
            RETURN v_status;
    END;

    RETURN 'OK';
END $$;
