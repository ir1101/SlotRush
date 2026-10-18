# Report outline: syllabus module → evidence (draft)

Every file below is produced by a command (shown in brackets) and can be regenerated.
`python -m slotrush review` runs them all in order.

## 1. Architecture

- Client–server setup: Python client, PostgreSQL 17 and MongoDB 8 servers in Docker
  (`docker-compose.yml`), one entry point (`slotrush/__main__.py`).
- Three-schema architecture as built:
  - external level: the four views in `sql/04_views.sql`, one per user group, with roles and
    row-level security (`sql/05_security.sql`)
  - conceptual level: the tables and constraints in `sql/01_schema.sql`
  - internal level: indexes (`sql/06_indexes.sql`), WAL and durability settings
- Data independence: the bench drops and rebuilds indexes (internal level) without changing any
  query or view.
- Evidence: `results/phase0_connection_check.txt` (`check`): versions, `fsync`, `synchronous_commit`,
  `wal_level`, `max_connections`.
- Three-tier architecture in the web front end (`python -m slotrush web`): browser → Flask app
  server (`slotrush/web/`) → PostgreSQL. The app server holds a `psycopg_pool` connection pool,
  is the trusted layer that sets `app.reg_no`, and each page's "Queries" panel shows the SQL it
  sent and the role it ran as. Tested in `tests/test_web.py`.

## 2. Relational model and ER

- `docs/er-diagram.md`: Mermaid relational schema and the EER design for Chen notation
  (composite, multivalued and derived attributes, weak entity, recursive relationship, disjoint
  total specialisation, aggregation).
- `sql/01_schema.sql`: PKs, FKs, UNIQUE, CHECK, the deferred totality trigger, the slot-kind trigger.
- `results/check_data.txt`, `results/data_profile.png` (`check-data`): the 258,514 generated
  registrations obey every rule; credit and seat-fill distributions.
- `results/null_behaviour.txt` (`nulls`): NULL in comparisons, three-valued logic, `NOT IN`,
  `COUNT`, UNIQUE, GROUP BY.
- Security: `sql/05_security.sql` (roles, GRANTs, RLS), tested in `tests/test_security.py`.
- Tests: `tests/test_schema.py`, `tests/test_register.py` (every rule and status code).

## 3. Normalisation

- `docs/normalisation.md`: FDs, closures, candidate keys, 1NF → 2NF → 3NF → BCNF, lossless and
  dependency-preservation checks, 4NF and 5NF examples.
- `results/flat_registration_export.csv` (`normalise`): the denormalised table.
- `results/normalisation_lossless_check.txt`: FDs verified on the data, every decomposition
  joined back and compared, one lossy split for contrast.
- `results/nf4_faculty_preference.csv`, `results/nf5_eligibility.csv`.

## 4. Indexing and query processing

- `docs/query-processing.md`: SQL, relational algebra, canonical and optimised query trees,
  comparison with the actual plan, tuple relational calculus.
- `results/bench_chart.png`, `results/bench_summary.csv`, `results/bench_timings.csv` (`bench`).
- `results/plans/<query>__<setup>.txt`: `EXPLAIN (ANALYZE, BUFFERS)` for 5 queries × 3 setups.
- Key observations: B-tree and hash both help equality (Q1 about 60× faster); only the B-tree
  helps the range query (Q3 about 11× faster with a B-tree, no gain with hash); no index helps a
  full aggregation (Q4). Compare setups within one run; absolute times vary between runs.

## 5. Transactions and recovery

- Atomicity: `register()` and `swap_course()` in `sql/03_functions.sql`; the swap's
  all-or-nothing savepoint is tested in `tests/test_register.py` (`test_swap_*`).
- Isolation anomaly: `results/demo_lost_update.png` (`lost-update`).
- Durability and recovery (`crash`): `results/demo_crash.png`, `results/commit_log.csv`,
  `results/demo_crash_recovery_log.txt` (PostgreSQL's own "redo starts / redo done" lines).
- Contrast (`crash --async-commit`): `results/demo_crash_async.png`,
  `results/commit_log_async.csv`: acknowledged commits lost with `synchronous_commit = off`;
  check (b) still passes (atomicity), check (a) fails (durability).

## 6. Concurrency control

- Lost update: `results/demo_lost_update.png`.
- Pessimistic (2PL-style row locks): `results/demo_locking.png`, `results/demo_locking_snapshot.csv`
  (who waits on whom, from `pg_locks` + `pg_stat_activity` + `pg_blocking_pids`).
- Optimistic (SSI): `serializable` output (retry counts), `results/demo_isolation_comparison.png`.
- Deadlock: `results/demo_deadlock.png`, `results/demo_deadlock_server_log.txt` (40P01 with the
  wait-for cycle), and the ordered-locking fix (`swap_course`).
- Tests: `tests/test_concurrency.py` (last seat to exactly one session; opposite swaps do not deadlock).

## 7. NoSQL

- `docs/nosql-cap.md`: why reviews suit a document store, CAP and PACELC for this system.
- `results/nosql_index_explain.txt` (COLLSCAN → IXSCAN), `results/nosql_aggregations.txt` / `.json`,
  `results/nosql_reviews.png` (`reviews`).

## 8. Contemporary issues

- `docs/contemporary-issues.md`: virtual waiting rooms and other ways to absorb registration
  spikes, linked to the locking and serializable measurements.

## Testing (all modules)

- `results/pytest_report.txt` (`test`): every test with its result.
