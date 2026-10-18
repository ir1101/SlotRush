# SlotRush

An FFCS-style course registration system built for **BCSE302L Database Systems**. Students
pick a course, a faculty member and a slot; every class has a fixed number of seats; thousands
of students compete for them at once. The point is not the app but the evidence: charts,
`EXPLAIN` plans, logs and test results for every syllabus module, all saved to `results/`.

PostgreSQL 17 holds the registration data (raw SQL and PL/pgSQL, no ORM). MongoDB 8 holds course
reviews. Everything runs from one Python entry point: `python -m slotrush <command>`.

## Setup

You need **Docker** (Docker Desktop on Windows and macOS, Docker Engine with the compose plugin
on Linux), **Python 3.11 or newer** and **Git**. Nothing is installed globally: Python packages
go into a virtual environment.

1. Get the code and open a terminal in the project folder.
2. Create the virtual environment:
   ```
   python -m venv .venv
   ```
3. Install the packages into it:
   - Windows: `.venv\Scripts\python -m pip install -r requirements.txt`
   - macOS / Linux: `.venv/bin/python -m pip install -r requirements.txt`

   **From here on, `python` means `.venv\Scripts\python` on Windows or `.venv/bin/python` on
   macOS / Linux** (or activate the venv and type `python`).
4. Start the databases (this also creates `.env` from `.env.example`):
   ```
   python -m slotrush up
   python -m slotrush check
   ```
5. Build the schema and load the synthetic data (about 1–2 minutes, ends with `check-data`):
   ```
   python -m slotrush load
   ```
6. Run the tests (the report is saved to `results/pytest_report.txt`):
   ```
   python -m slotrush test
   ```
7. Run everything for the review, pausing between steps:
   ```
   python -m slotrush review
   ```
8. Open the web front end at http://127.0.0.1:5000 (Ctrl+C stops it):
   ```
   python -m slotrush web
   ```

To open a SQL prompt: `docker exec -it slotrush-postgres psql -U slotrush -d slotrush`.
To stop: `python -m slotrush down` (data is kept; `down --wipe` deletes it).

## Commands

| Command | What it does | Syllabus module |
|---|---|---|
| `up`, `down`, `check` | containers and connection check | 1 Architecture |
| `setup` | drop and rebuild the schema from `sql/` | 2 Relational model and ER |
| `load` | setup, generate data (fixed seed), COPY, ANALYZE, check-data | 2 |
| `check-data` | no clashes, duplicates, credit breaches or bad seat counts | 2 |
| `nulls` | NULL in comparisons, `NOT IN`, `COUNT`, UNIQUE | 2 |
| `lost-update` | 80 bots, 30 seats, naive read-write at READ COMMITTED | 5, 6 |
| `locking` | the same race through `register()` (`SELECT … FOR UPDATE`), with a `pg_locks` monitor | 6 |
| `serializable` | naive path at SERIALIZABLE with 40001 retries, plus the comparison chart | 6 |
| `deadlock` | opposite moves deadlock (40P01); `swap_course` does not | 6 |
| `crash` | `docker kill` in the middle of 1,000 registrations, then check durability; `--async-commit` for the contrast | 5 |
| `bench` | five queries under no index, B-tree and hash indexes | 4 |
| `normalise` | flat export, FD checks, 1NF to BCNF, 4NF and 5NF, lossless-join checks | 3 |
| `reviews` | MongoDB reviews: seed, index explain, aggregations | 7 |
| `web` | the web front end (Flask): log in as a student, faculty member or admin; every page shows the SQL it ran | 1 Architecture, 2 (views, roles, RLS) |
| `test` | pytest, report saved to `results/` | all |
| `review` | runs the demos in order; `--no-pause`, `--start N` | all |

Which file proves what, module by module: [docs/report-outline.md](docs/report-outline.md).

## Layout

```
docker-compose.yml   PostgreSQL 17 + MongoDB 8 (settings from .env)
sql/                 01_schema, 02_reference_data, 03_functions, 04_views, 05_security, 06_indexes
slotrush/            the Python package (one module per command; demos/ holds the five demos)
tests/               pytest: rules, constraints, security, concurrency, generator, normalisation
docs/                SPEC (the brief), ER design, query processing, normalisation, NoSQL/CAP, ...
results/             every chart, CSV, plan and log the commands produce
```

## Where this differs from the brief, and why

- **Capacities are 50–90, not 40–80.** 4,500 offerings × 60 seats is about 270,000 seats for
  about 250,000 registrations: 93% full, not "comfortably above". With 50–90 there are 315,596 seats
  for 258,514 registrations (82%). Set in `slotrush/generate.py` (`Scale`).
- **PostgreSQL 17**, not 18: 18 adds B-tree skip scan, which would let composite constraint
  indexes serve queries on their second column and blur the "no secondary index" baseline.
- **The crash demo proves WAL recovery and `synchronous_commit`, not `fsync`.** `docker kill`
  kills processes, not the machine, so the OS still writes what it was given. `crash
  --async-commit` shows acknowledged commits being lost when `synchronous_commit = off`.
- **`app.reg_no` is not authentication**: any session can set it. It is safe only behind a
  trusted application layer.
- **security_invoker views need grants on the base tables**, so `student` also has row-level
  security (a student sees only their own row) and faculty get only the name columns.
- **Demo data lives apart**: demo offerings are in semester `DEMO`, bot students are
  `99BOT0001…`. Every demo wipes all demo rows first, so the lost-update demo's broken seat count
  never affects `check-data` or the crash check.

## The web front end

`python -m slotrush web` serves server-rendered pages from Flask (`slotrush/web/`). There are no
passwords: "Log in as" only chooses a role and a student or faculty member. Each request then
runs in one transaction that starts with `SET LOCAL ROLE student_role` (or `faculty_role` /
`admin_role`) and `set_config('app.reg_no', …, true)`, so the same row-level security the tests
check decides what each page shows. Registering, dropping and swapping call the PL/pgSQL
functions and show the status code they return. A "Queries" panel at the bottom of every page
lists the exact SQL it ran and as which role.

- Pages: home (live counts), log in as, student (timetable, credits meter, drop, swap),
  catalogue (search and register), faculty (class lists), admin (seat fill), evidence
  (everything in `results/`; the charts are drawn by the page from the numbers each command
  saves, and link to the PNG versions for the report).
- The look was designed with the taste-skill process (notes and direction sheet in
  `.taste-skill/`): olive on bone, Libre Franklin for display and Source Serif 4 for text
  (Google Fonts; without internet they fall back to system fonts). The home page opens on
  "30 seats, 80 students" and lets you pick a guard (no lock, row lock, serializable) to see what
  the concurrency demos measured, with a replay of the 80 bots racing for the 30 seats; it reads
  the numbers from `results/`. All motion respects the system's reduced-motion setting.
- Four found photographs (public domain, CC0 and CC BY) are in `slotrush/web/static/img/`, with
  their sources and licences in `credits.json`; the footer credits each one. They show the world
  around the project (punched cards, lecture seats, the VIT campus), never SlotRush itself.
- It is a single-user demo on `127.0.0.1`: the development server, no CSRF tokens, and a new
  session key on every start (restarting signs everyone out).

## Troubleshooting

- *`docker` not found right after installing Docker Desktop*: open a new terminal (PATH is read at start).
- *`docker` commands hang*: Docker Desktop's engine is stuck. Quit it from the tray and start it again.
- *Port 5432 or 27017 already in use*: change `POSTGRES_PORT` / `MONGO_PORT` in `.env`, then `down` and `up`.
- *Project inside OneDrive*: works, but OneDrive syncing `.venv` is slow; a folder outside OneDrive is better.
