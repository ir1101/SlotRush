-- =============================================================================
-- 06_indexes.sql : secondary indexes (B-tree)
--
-- Primary keys and UNIQUE constraints already have their own B-tree indexes.
-- These cover the lookups those indexes do not. Every name starts with "ix_"
-- so the benchmark (python -m slotrush bench) can drop them all and rebuild
-- them as B-tree or hash indexes.
--
-- PostgreSQL does NOT index foreign key columns automatically.
-- =============================================================================

-- Student timetable, and the per-student checks inside register().
-- The PK (offering_id, reg_no) cannot help: its index is ordered by offering_id first.
CREATE INDEX ix_registration_reg_no ON registration USING btree (reg_no);

-- Registrations in a time window (a range query).
CREATE INDEX ix_registration_registered_at ON registration USING btree (registered_at);

-- Offerings by slot, by faculty and by course.
CREATE INDEX ix_offering_slot_id     ON offering USING btree (slot_id);
CREATE INDEX ix_offering_faculty_id  ON offering USING btree (faculty_id);
CREATE INDEX ix_offering_course_code ON offering USING btree (course_code);
