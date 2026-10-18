# SlotRush: working notes for Claude

FFCS-style course registration system for BCSE302L Database Systems.
Full brief: [docs/SPEC.md](docs/SPEC.md). The goal is syllabus evidence
(charts, EXPLAIN output, logs, test results), not a polished app.

## Working rules
- Originally one phase at a time. On 2026-10-17 the user asked for Phases 1-8
  in one go (deadline in 5 days), so build them back to back, run each
  phase's commands and tests as it is finished, and report all phases at the
  end: what was built, exact commands, and the syllabus module for each.
  Phase 9 (stretch) still only if asked.
- Never run `git commit` (or anything else that writes git history). The user
  commits manually. At the end of a phase, list the changed files and suggest
  a commit message instead.
- Must run on Windows, macOS and Linux. Python for all automation: no bash
  scripts, no Makefiles.
- Virtual environment plus `requirements.txt`. Never install anything globally.
- Raw SQL only, no ORM: transaction and locking behaviour must stay visible.
- No real login system. On 2026-10-18 the user approved a web framework: the
  front end is Flask with server-rendered Jinja pages (`slotrush/web/`), raw SQL
  through a `psycopg_pool` pool, no ORM. "Log in as" only picks a role + reg_no /
  faculty_id; every request runs `SET LOCAL ROLE` + `set_config('app.…', true)`.
  Look: on 2026-10-18 the user replaced the Dragonfly reference with a full
  taste-skill redesign (direction "Type and nothing else", seed 612931887, notes
  and sheet in `.taste-skill/`): olive #38450f on bone #ecebe7, Libre Franklin 700
  + Source Serif 4, no monospace outside code, no 01/02 numbering, no hairlines
  (tables and form fields excepted), square flat buttons, plain top bar.
  Check with `node ~/.claude/skills/taste-skill/scripts/lint.mjs slotrush/web`
  (inspect.mjs needs Node 22; this machine has Node 20).
  Found photographs live in `slotrush/web/static/img/` with `credits.json`;
  the footer prints their credits.
- Fixed random seeds everywhere.
- Every chart, CSV, query plan and log goes to `results/` with a clear name.
- Everything in `docs/` is a draft; the user rewrites the theory.
- If the brief is wrong or will not work as written, say so. Never quietly
  work around it.
- Simple, well-commented code: the user must be able to explain every line.
- Single entry point: `python -m slotrush <command>`.

## Layout and commands
- `docker-compose.yml`: `postgres:17` (`slotrush-postgres`) and `mongo:8.0`
  (`slotrush-mongo`), settings from `.env` (template `.env.example`).
- `sql/01..06`: schema, reference timetable, PL/pgSQL rules, views, security, indexes.
  Everything lives in PostgreSQL schema `slotrush`; `setup` drops and rebuilds it.
- `slotrush/`: one module per command (`setup_db`, `load` + `generate`, `check_data`,
  `nulls`, `bench`, `normalise`, `nosql`, `review`), `demos/` (lost_update, locking,
  serializable, deadlock, crash, shared `common`), `charts.py` (shared chart style).
- `slotrush/web/`: `app.py` (routes, `create_app(dbname)`), `data.py` (pool, `as_role()`,
  query log for the "Queries" panel), `figures.py` (evidence charts drawn by the page from
  the numbers each command saves next to its PNG; `templates/_charts.html` draws them),
  `templates/`, `static/` (CSS, `site.js`, `race.js` = the home page's race replay, `img/`).
  Run: `python -m slotrush web` (port 5000); `.claude/launch.json` has a `slotrush-web`
  preview config. Tests: `tests/test_web.py` (Flask test client), `tests/test_figures.py`.
- The PNGs in `results/` are for the report; the web page draws the same numbers itself
  (`data_profile.json`, `demo_*_reads/queue/timeline.csv`, the demo JSONs, bench CSVs).
- Tests use database `slotrush_test` (rebuilt per session); demos use the main DB.
- Demo rows: semester `DEMO`, bots `99BOT####`; every demo wipes all demo rows first.
- Run with the venv's Python: `.venv\Scripts\python` (Windows) or
  `.venv/bin/python` (macOS/Linux). `python -m slotrush --help` lists commands.

## Decisions that differ from the brief (told to the user)
- Capacities 50-90 instead of 40-80 (seat headroom); ~258.5k registrations.
- PostgreSQL 17 (18's skip scan would blur the bench baseline).
- Crash demo proves WAL recovery + synchronous_commit, not fsync; `--async-commit` contrast.
- RLS also on `student`; faculty get name columns only (security_invoker needs base grants).

## Phase checklist
- [x] 0. Repo skeleton, SPEC.md, CLAUDE.md, docker compose, connection check for both databases
- [x] 1. Schema, constraints, functions, views, roles, RLS, tests, `docs/er-diagram.md`
- [x] 2. Data generator, loader, `check-data`
- [x] 3. Demos 1 to 4 (lost-update, locking, serializable, deadlock)
- [x] 4. Crash demo
- [x] 5. Index benchmark and `docs/query-processing.md`
- [x] 6. Normalisation export, document, lossless check
- [x] 7. MongoDB reviews and `docs/nosql-cap.md`
- [x] 8. Wrap-up: README, `review` command, contemporary issues, report outline
- [ ] 9. Stretch (only if asked): schedule simulator

- [x] Web front end (after Phase 8, on request): home, log in as, student
  (timetable, credits, drop/swap, catalogue + register), faculty, admin, evidence.

Current status: Phases 0-8 and the web front end built and tested (125 tests);
nothing committed (the user commits). Phase 9 only if the user asks.

## Machine notes (this Windows laptop)
- Docker Desktop is a per-user install; sessions started before it was installed
  need PATH refreshed from the registry before `docker` (or `slotrush up`) works.
- If `docker` commands hang, Docker Desktop's backend is stuck: quit it fully
  and restart it.
