-- =============================================================================
-- 02_reference_data.sql : the invented timetable and the credit settings
--
-- The week is 5 days x 8 periods = 40 (day, period) cells.
--
--   Theory slots T01..T08 meet Mon, Wed, Fri (3 times a week) in period 1..8.
--   Theory slots T09..T16 meet Tue, Thu     (2 times a week) in period 1..8.
--   Together the 16 theory slots cover all 40 cells exactly once.
--
--   Lab slots L01..L20 are blocks of two consecutive periods:
--   (1,2), (3,4), (5,6), (7,8) on each of the 5 days. They also cover all 40
--   cells exactly once.
--
-- So theory slots never clash with each other, lab slots never clash with
-- each other, and every lab slot clashes with exactly two theory slots.
-- Example: L01 = Monday periods 1-2, which T01 and T02 also use on Monday.
-- =============================================================================

INSERT INTO settings (min_credits, max_credits, current_semester)
VALUES (16, 27, 'FALL2026');

-- Theory slots
INSERT INTO slot (slot_id, slot_kind)
SELECT 'T' || lpad(n::text, 2, '0'), 'THEORY'
FROM generate_series(1, 16) AS n;

-- T01..T08: period p on Monday (1), Wednesday (3) and Friday (5)
INSERT INTO slot_timing (slot_id, day, period)
SELECT 'T' || lpad(p::text, 2, '0'), d, p
FROM generate_series(1, 8) AS p
CROSS JOIN unnest(ARRAY[1, 3, 5]) AS d;

-- T09..T16: period p on Tuesday (2) and Thursday (4)
INSERT INTO slot_timing (slot_id, day, period)
SELECT 'T' || lpad((8 + p)::text, 2, '0'), d, p
FROM generate_series(1, 8) AS p
CROSS JOIN unnest(ARRAY[2, 4]) AS d;

-- Lab slots: day d, block b (b = 1..4) is slot number (d - 1) * 4 + b
INSERT INTO slot (slot_id, slot_kind)
SELECT 'L' || lpad(n::text, 2, '0'), 'LAB'
FROM generate_series(1, 20) AS n;

-- Each lab block uses periods 2b - 1 and 2b
INSERT INTO slot_timing (slot_id, day, period)
SELECT 'L' || lpad(((d - 1) * 4 + b)::text, 2, '0'), d, p
FROM generate_series(1, 5) AS d
CROSS JOIN generate_series(1, 4) AS b
CROSS JOIN LATERAL (VALUES (2 * b - 1), (2 * b)) AS periods(p);
