-- =============================================================================
-- 01_schema.sql : tables and constraints for SlotRush
--
-- Run by "python -m slotrush setup", which first drops and recreates the
-- schema "slotrush" and sets search_path, so names below are unqualified.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Settings: a single-row table. The boolean primary key with CHECK (id) means
-- the only possible key value is TRUE, so a second row can never be inserted.
-- -----------------------------------------------------------------------------
CREATE TABLE settings (
    id                boolean PRIMARY KEY DEFAULT true CHECK (id),
    min_credits       smallint NOT NULL CHECK (min_credits > 0),
    max_credits       smallint NOT NULL,
    current_semester  varchar(8) NOT NULL,
    CHECK (min_credits <= max_credits)
);


-- -----------------------------------------------------------------------------
-- Student. "name" is a COMPOSITE attribute stored as first_name + last_name.
-- -----------------------------------------------------------------------------
CREATE TABLE student (
    reg_no      varchar(9)  PRIMARY KEY
                CHECK (reg_no ~ '^[0-9]{2}[A-Z]{3}[0-9]{4}$'),   -- e.g. 23BCE0042
    first_name  varchar(40) NOT NULL,
    last_name   varchar(40) NOT NULL,
    programme   varchar(3)  NOT NULL,                             -- e.g. BCE, BIT
    admit_year  smallint    NOT NULL CHECK (admit_year BETWEEN 2000 AND 2100),
    email       varchar(80) NOT NULL UNIQUE
);

-- MULTIVALUED attribute: a student has any number of phone numbers.
-- It gets its own table whose key is (owner key, value).
CREATE TABLE student_phone (
    reg_no  varchar(9)  NOT NULL REFERENCES student ON DELETE CASCADE,
    phone   varchar(15) NOT NULL CHECK (phone ~ '^\+?[0-9]{10,14}$'),
    PRIMARY KEY (reg_no, phone)
);


CREATE TABLE faculty (
    faculty_id  integer     PRIMARY KEY,
    first_name  varchar(40) NOT NULL,
    last_name   varchar(40) NOT NULL,
    school      varchar(10) NOT NULL,                             -- e.g. SCOPE, SENSE
    email       varchar(80) NOT NULL UNIQUE
);


-- -----------------------------------------------------------------------------
-- Course and its DISJOINT, TOTAL specialisation into theory, lab and project.
--
-- Disjoint: course_type is a single-valued discriminator, and every subtype
-- table holds a course_type column that its CHECK pins to one value. The
-- composite foreign key (course_code, course_type) must match the parent row,
-- so a LAB course can never get a theory_course row.
--
-- Total: a foreign key cannot force a parent to HAVE a child row, so a deferred
-- constraint trigger (below) checks at COMMIT that every course has a row in
-- the subtype table its course_type names.
-- -----------------------------------------------------------------------------
CREATE TABLE course (
    course_code  varchar(8)  PRIMARY KEY
                 CHECK (course_code ~ '^[A-Z]{4}[0-9]{3}[A-Z]$'),  -- e.g. BCSE302L
    title        varchar(80) NOT NULL,
    credits      smallint    NOT NULL CHECK (credits BETWEEN 1 AND 5),
    course_type  varchar(7)  NOT NULL CHECK (course_type IN ('THEORY', 'LAB', 'PROJECT')),
    UNIQUE (course_code, course_type)      -- target of the subtype foreign keys
);

CREATE TABLE theory_course (
    course_code     varchar(8) PRIMARY KEY,
    course_type     varchar(7) NOT NULL DEFAULT 'THEORY' CHECK (course_type = 'THEORY'),
    lecture_hours   smallint   NOT NULL CHECK (lecture_hours BETWEEN 1 AND 4),
    tutorial_hours  smallint   NOT NULL DEFAULT 0 CHECK (tutorial_hours BETWEEN 0 AND 2),
    FOREIGN KEY (course_code, course_type)
        REFERENCES course (course_code, course_type) ON DELETE CASCADE
);

CREATE TABLE lab_course (
    course_code    varchar(8)  PRIMARY KEY,
    course_type    varchar(7)  NOT NULL DEFAULT 'LAB' CHECK (course_type = 'LAB'),
    lab_hours      smallint    NOT NULL CHECK (lab_hours BETWEEN 1 AND 6),
    lab_room_type  varchar(20) NOT NULL,                         -- e.g. Computer, Electronics
    FOREIGN KEY (course_code, course_type)
        REFERENCES course (course_code, course_type) ON DELETE CASCADE
);

CREATE TABLE project_course (
    course_code    varchar(8)  PRIMARY KEY,
    course_type    varchar(7)  NOT NULL DEFAULT 'PROJECT' CHECK (course_type = 'PROJECT'),
    max_team_size  smallint    NOT NULL CHECK (max_team_size BETWEEN 1 AND 5),
    deliverable    varchar(30) NOT NULL,                         -- e.g. Report and demo
    FOREIGN KEY (course_code, course_type)
        REFERENCES course (course_code, course_type) ON DELETE CASCADE
);

-- Totality check. Fired for a course row (insert/update) or a subtype row (delete).
CREATE FUNCTION check_course_has_subtype() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_code  varchar(8);
    v_type  varchar(7);
    v_ok    boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_code := OLD.course_code;      -- a subtype row was deleted
    ELSE
        v_code := NEW.course_code;      -- a course row was inserted or updated
    END IF;

    SELECT course_type INTO v_type FROM course WHERE course_code = v_code;
    IF NOT FOUND THEN
        RETURN NULL;                    -- the course itself is gone: nothing to check
    END IF;

    v_ok := CASE v_type
        WHEN 'THEORY'  THEN EXISTS (SELECT 1 FROM theory_course  WHERE course_code = v_code)
        WHEN 'LAB'     THEN EXISTS (SELECT 1 FROM lab_course     WHERE course_code = v_code)
        WHEN 'PROJECT' THEN EXISTS (SELECT 1 FROM project_course WHERE course_code = v_code)
    END;

    IF NOT v_ok THEN
        RAISE EXCEPTION 'total specialisation violated: course % (%) has no row in its subtype table',
                        v_code, v_type
              USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NULL;                        -- return value of an AFTER trigger is ignored
END $$;

-- DEFERRABLE INITIALLY DEFERRED: the check runs at COMMIT, so a transaction can
-- insert the course row first and its subtype row second.
CREATE CONSTRAINT TRIGGER course_must_have_subtype
    AFTER INSERT OR UPDATE ON course
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION check_course_has_subtype();

CREATE CONSTRAINT TRIGGER theory_course_keeps_total
    AFTER DELETE ON theory_course
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION check_course_has_subtype();

CREATE CONSTRAINT TRIGGER lab_course_keeps_total
    AFTER DELETE ON lab_course
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION check_course_has_subtype();

CREATE CONSTRAINT TRIGGER project_course_keeps_total
    AFTER DELETE ON project_course
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION check_course_has_subtype();


-- RECURSIVE relationship: Course "requires" Course.
CREATE TABLE prerequisite (
    course_code  varchar(8) NOT NULL REFERENCES course ON DELETE CASCADE,
    prereq_code  varchar(8) NOT NULL REFERENCES course ON DELETE CASCADE,
    PRIMARY KEY (course_code, prereq_code),
    CHECK (course_code <> prereq_code)          -- a course cannot require itself
);

-- Courses a student has passed (S to E are VIT's pass grades; F is not stored).
CREATE TABLE completed_course (
    reg_no       varchar(9) NOT NULL REFERENCES student ON DELETE CASCADE,
    course_code  varchar(8) NOT NULL REFERENCES course,
    semester     varchar(8) NOT NULL,
    grade        char(1)    NOT NULL CHECK (grade IN ('S', 'A', 'B', 'C', 'D', 'E')),
    PRIMARY KEY (reg_no, course_code)
);


-- -----------------------------------------------------------------------------
-- Slot and its WEAK entity SlotTiming.
-- A timing (day, period) has no identity of its own: it is identified by its
-- owner slot plus the partial key (day, period), and dies with the slot.
-- -----------------------------------------------------------------------------
CREATE TABLE slot (
    slot_id    varchar(3) PRIMARY KEY,                         -- T01..T16, L01..L20
    slot_kind  varchar(6) NOT NULL CHECK (slot_kind IN ('THEORY', 'LAB'))
);

CREATE TABLE slot_timing (
    slot_id  varchar(3) NOT NULL REFERENCES slot ON DELETE CASCADE,
    day      smallint   NOT NULL CHECK (day BETWEEN 1 AND 5),      -- 1 = Monday
    period   smallint   NOT NULL CHECK (period BETWEEN 1 AND 8),
    PRIMARY KEY (slot_id, day, period)
);


-- -----------------------------------------------------------------------------
-- Offering: the AGGREGATION of the ternary relationship
-- "Faculty teaches Course in Slot", turned into an entity with its own
-- attributes so that students can register for it.
-- -----------------------------------------------------------------------------
CREATE TABLE offering (
    offering_id  integer     GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    course_code  varchar(8)  NOT NULL REFERENCES course,
    faculty_id   integer     NOT NULL REFERENCES faculty,
    slot_id      varchar(3)  NOT NULL REFERENCES slot,
    semester     varchar(8)  NOT NULL,
    venue        varchar(10),                    -- NULL until a room is allotted
    capacity     smallint    NOT NULL CHECK (capacity > 0),
    seats_left   smallint    NOT NULL,
    CHECK (seats_left BETWEEN 0 AND capacity),
    -- One class per room per slot. NULL venues never conflict, because UNIQUE
    -- treats NULLs as distinct (NULL = NULL is not true).
    UNIQUE (venue, semester, slot_id)
);

-- Lab courses must sit in lab slots; theory and project courses in theory slots.
-- A CHECK cannot look at other tables, so this is a trigger.
CREATE FUNCTION check_offering_slot_kind() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_course_type  varchar(7);
    v_slot_kind    varchar(6);
BEGIN
    SELECT course_type INTO v_course_type FROM course WHERE course_code = NEW.course_code;
    SELECT slot_kind   INTO v_slot_kind   FROM slot   WHERE slot_id     = NEW.slot_id;
    IF (v_course_type = 'LAB') <> (v_slot_kind = 'LAB') THEN
        RAISE EXCEPTION '% course % cannot be offered in % slot %',
                        v_course_type, NEW.course_code, v_slot_kind, NEW.slot_id
              USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER offering_slot_kind
    BEFORE INSERT OR UPDATE OF course_code, slot_id ON offering
    FOR EACH ROW EXECUTE FUNCTION check_offering_slot_kind();


-- -----------------------------------------------------------------------------
-- Registration and Waitlist: Student registers for Offering (M:N).
-- The primary key starts with offering_id on purpose: seat counts and class
-- lists look rows up by offering, and the PK index serves them. Lookups by
-- student use the secondary index ix_registration_reg_no (06_indexes.sql).
-- -----------------------------------------------------------------------------
CREATE TABLE registration (
    offering_id    integer     NOT NULL REFERENCES offering ON DELETE CASCADE,
    reg_no         varchar(9)  NOT NULL REFERENCES student  ON DELETE CASCADE,
    registered_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (offering_id, reg_no)
);

CREATE TABLE waitlist (
    offering_id  integer     NOT NULL REFERENCES offering ON DELETE CASCADE,
    reg_no       varchar(9)  NOT NULL REFERENCES student  ON DELETE CASCADE,
    queued_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (offering_id, reg_no)
);
