# SlotRush: Database Systems course project

## Context
I am a CSE student at VIT building the project for BCSE302L Database Systems. The project is an FFCS-style course registration system. Under FFCS, each student picks a course, a faculty member and a time slot, and every class has a fixed number of seats. As a result, thousands of students compete for the same seats in the same few minutes.

The goal is not a polished app. The goal is to demonstrate the syllabus with measurable evidence: graphs, EXPLAIN output, logs and test results that I can put in my report and show live in my review.

The syllabus modules are:
1. Architecture
2. Relational model and ER
3. Normalisation
4. Indexing and query processing
5. Transactions and recovery
6. Concurrency control
7. NoSQL
8. Contemporary issues

I must be able to explain every line, so keep the code simple and well commented.

## Before you write any code
1. Save this whole brief as `docs/SPEC.md`.
2. Create a short `CLAUDE.md` at the repo root. It should hold the working rules below and a phase checklist that you keep updated.
3. Propose your plan for Phases 0 and 1, then wait for my approval.

## Working rules
- Work one phase at a time. At the end of each phase:
  - run what you built and the tests
  - commit to git
  - stop and tell me what was built, the exact commands to run it, and which syllabus module it demonstrates
  - wait for me before starting the next phase
- Everything must run on Windows, macOS and Linux. Use Python for all automation, not bash scripts or Makefiles.
- Use a virtual environment and `requirements.txt`. Do not install anything globally.
- Write raw SQL. Do not use an ORM, because the transaction and locking behaviour has to stay visible.
- No login system and no web framework. Use Streamlit only if I ask for it later.
- Use fixed random seeds everywhere, so data and results are reproducible.
- Save every chart, CSV, query plan and log to `results/` with clear file names, so I can cite them in the report.
- Treat every file in `docs/` as a draft. I will check and rewrite the theory myself.
- If something in this brief is wrong or will not work as written, tell me. Do not quietly work around it.

## Stack
- PostgreSQL and MongoDB in one `docker-compose.yml`:
  - use the official PostgreSQL image with a pinned major version, 16 or newer
  - use named volumes, health checks and fixed container names
  - keep credentials in `.env`, with a committed `.env.example`
- Keep `fsync` and `synchronous_commit` at their defaults. The crash demo depends on them.
- Python 3.11 or newer with `psycopg` (version 3), `psycopg_pool`, `Faker`, `matplotlib`, `pymongo` and `pytest`.
- One entry point, `python -m slotrush <command>`, for setup, data loading, every demo and the benchmark.

## Data model
Tables:
- Student and StudentPhone
- Faculty
- Course, TheoryCourse, LabCourse and ProjectCourse
- Slot and SlotTiming
- Offering, Registration and Waitlist
- Prerequisite and CompletedCourse
- Settings, for the minimum and maximum credits per semester

The design must contain each of the following, because I have to point to them:
- Attributes:
  - a composite attribute: student name as first and last name
  - a multivalued attribute: StudentPhone
  - a derived attribute: total registered credits, computed in a view and never stored
- A weak entity: SlotTiming, the (day, period) meetings of a slot, identified by slot, day and period.
- A recursive relationship: Prerequisite, from Course to Course.
- A disjoint, total specialisation of Course into TheoryCourse, LabCourse and ProjectCourse, each with its own attributes:
  - enforce disjointness in the schema, for example with a course_type discriminator and composite foreign keys
  - explain in the docs how totality is guaranteed
- An aggregation: "Faculty teaches Course in Slot" becomes Offering (semester, venue, capacity, seats_left), and students register for an Offering.
- Primary keys, foreign keys, UNIQUE constraints and CHECK constraints, including seats_left between 0 and capacity.
- A `venue` column left nullable until allotted. I will use it to show how NULLs behave in comparisons, `NOT IN` and `COUNT`.

Invent a simplified timetable:
- 5 days of 8 periods
- theory slots that meet two or three times a week
- lab slots of two consecutive periods

Real VIT slot codes are not needed. Two slots clash when they share any (day, period).

For `docs/er-diagram.md`:
- Draw the relational schema as a Mermaid `erDiagram`.
- Mermaid cannot show specialisation or aggregation, so also write out the full EER design in a form I can redraw in Chen notation in draw.io. Include entities, attribute types, relationships with cardinality and participation, the specialisation and the aggregation.

## Business rules (PL/pgSQL)
- `register(reg_no, offering_id)` returns `OK`, `FULL`, `CLASH`, `CREDIT_LIMIT`, `PREREQ` or `DUPLICATE`. In one transaction it:
  1. locks the student row and then the offering row with `SELECT ... FOR UPDATE`
  2. rejects a second offering of a course the student already has this semester
  3. rejects a slot clash
  4. rejects unmet prerequisites, checked against CompletedCourse
  5. rejects anything over the maximum credits
  6. if seats_left is 0, adds the student to Waitlist and returns `FULL`; otherwise decrements seats_left and inserts the registration
- `drop_course(reg_no, offering_id)` uses the same lock order, increments seats_left and deletes the registration.
- `swap_course(reg_no, from_offering, to_offering)`:
  - locks the student first
  - then locks both offerings in ascending ID order, using two separate `SELECT ... FOR UPDATE` statements, lower ID first
  - does the drop and the add all or nothing
- Write a pytest test for every rule and every status code.

## External views, roles and security
- Views: `v_student_timetable`, `v_faculty_class_list`, `v_admin_seat_fill` and `v_student_credits`. Create them all `WITH (security_invoker = true)` so row-level security still applies through them.
- Roles: `student_role`, `faculty_role` and `admin_role`, with GRANTs matching their views.
- Row-level security on Registration: a student session sets `app.reg_no` and sees only its own rows. Test this as a non-owner role, because superusers and table owners bypass RLS.

## Synthetic data
- Use Faker with a fixed seed to generate:
  - about 30,000 students
  - 600 courses
  - 4,500 offerings with capacities between 40 and 80
  - about 250,000 registrations
  - faculty, phones, prerequisites and completed courses
- Keep total seats comfortably above total registrations. Keep every student under the maximum credits, with no clashes.
- Generate registrations in Python and bulk load them with `COPY`, instead of calling `register` 250,000 times. They must still obey the same rules.
- Set seats_left to capacity minus registrations, then run `ANALYZE`.
- Add a `check-data` command that confirms there are no clashes, no duplicates, no credit breaches and no seat counts out of line.

## Demos
Each demo:
- is one command
- resets its own state first (fresh target offerings and fresh bot students), so it can be rerun any number of times
- prints a short plain-English summary
- saves a chart to `results/`

Bots start together using a `threading.Barrier`, each with its own connection. Keep total connections under PostgreSQL's default limit of 100, or raise `max_connections` in the compose file.

1. `lost-update`: 80 bots register for one offering with 30 seats, using a deliberately naive path at READ COMMITTED:
   - read seats_left into Python
   - sleep about 50 ms
   - write back the old value minus one
   - insert the registration
   Show that more than 30 get in.
2. `locking`: the same race, run through `register`. Exactly 30 must get in. A monitor thread samples `pg_locks` joined with `pg_stat_activity` during the run. It saves a snapshot of which sessions are waiting on which.
3. `serializable`: the naive path again, this time at SERIALIZABLE, retrying on SQLSTATE 40001 with a small random backoff and a capped retry count. Then save one chart comparing all three runs on students admitted against capacity, total time and retries.
4. `deadlock`: student A moves from offering P to Q while student B moves from Q to P.
   - Do each move naively as `drop_course` then `register` in one transaction.
   - Force the timing so each holds one offering and waits for the other.
   - Catch SQLSTATE 40P01 and print PostgreSQL's message.
   - Then repeat with `swap_course` and show both swaps succeed.
5. `crash`: run 1,000 registrations across bot threads.
   - Each thread appends to `results/commit_log.csv` only after its COMMIT returns.
   - Partway through, kill the PostgreSQL container with `docker kill`.
   - Start it again and wait until `pg_isready` passes.
   - Check (a): every logged commit exists in Registration.
   - Check (b): for every offering, seats_left plus its registration count equals capacity.
   - Print PASS or FAIL for each check.
   - Explain in the output that rows present in the table but missing from the log are expected. Those commits reached the server, but the acknowledgement was lost in the crash.

## Index benchmark and query processing
- `bench` runs five named queries under three setups:
  - no secondary indexes
  - B+ tree (B-tree) indexes
  - hash indexes on the equality columns
- The five queries:
  - one student's timetable
  - seats left in one slot
  - registrations for a course within a time range (a range query, where a hash index cannot help)
  - students below the minimum credits
  - a faculty class list join
- Primary keys and UNIQUE constraints already create B-tree indexes. Choose predicates those indexes do not cover, and say so in the output.
- Do one warm-up run, then take the median of at least five runs.
- Save `EXPLAIN (ANALYZE, BUFFERS)` output for every query and setup, a CSV of timings and a bar chart.
- `docs/query-processing.md` covers, for each query:
  - the SQL
  - its relational algebra expression
  - the canonical query tree, as a Mermaid diagram
  - the heuristically optimised tree (selections and projections pushed down, most selective join first), as a Mermaid diagram
  - a comparison with the plan PostgreSQL actually chose
- Also write two or three of the queries in tuple relational calculus.

## Normalisation material
- Export a flat, denormalised registration table to `results/flat_registration_export.csv`.
- `docs/normalisation.md` covers:
  - the functional dependencies, attribute closures and candidate keys
  - the decomposition, step by step from 1NF to BCNF
  - lossless-join and dependency-preservation checks
- A 4NF example: a FacultyPreference table holding independent expertise areas and preferred slots for each faculty member, giving two multivalued dependencies.
- A 5NF example: a faculty, course and slot eligibility table with a join dependency. Show that splitting it into two projections creates spurious tuples, while the three-way split does not.
- A script that proves each decomposition is lossless. It joins the parts back together and compares the result with the original.

## NoSQL
- A MongoDB `reviews` collection, in which theory, lab and project reviews carry different fields:
  - seed a few thousand reviews
  - add an index
  - write three or four aggregation queries, such as average rating per faculty and most common tags
- `docs/nosql-cap.md` covers:
  - why reviews suit a document store
  - the CAP argument for this system: seat allotment must stay consistent, while reviews can accept eventual consistency

## Phases
0. Repo skeleton, `docs/SPEC.md`, `CLAUDE.md`, docker compose, and a connection check for both databases
1. Schema, constraints, functions, views, roles, RLS, tests and `docs/er-diagram.md`
2. Data generator, loader and `check-data`
3. Demos 1 to 4
4. Crash demo
5. Index benchmark and `docs/query-processing.md`
6. Normalisation export, document and lossless check
7. MongoDB reviews and `docs/nosql-cap.md`
8. Wrap-up:
   - `README.md` with setup steps
   - a `review` command that runs every demo in order and pauses for Enter between them
   - a short `docs/contemporary-issues.md` on how large portals absorb registration spikes with virtual waiting queues
   - `docs/report-outline.md`, mapping each syllabus module to its evidence files in `results/`
9. Stretch, only if I ask: a pure Python schedule simulator. It:
   - takes a schedule such as `r1(X) w2(X) w1(Y) c1 c2`
   - draws the precedence graph
   - checks conflict serialisability and recoverability
   - simulates 2PL, timestamp ordering with Thomas write rule, wait-die and wound-wait
   - is tested against textbook examples
