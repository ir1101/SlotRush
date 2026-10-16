# SlotRush: working notes for Claude

FFCS-style course registration system for BCSE302L Database Systems.
Full brief: [docs/SPEC.md](docs/SPEC.md). The goal is syllabus evidence
(charts, EXPLAIN output, logs, test results), not a polished app.

## Working rules
- One phase at a time. At the end of each phase: run what was built and the
  tests, commit to git, then stop and report what was built, the exact
  commands to run it, and which syllabus module it demonstrates. Wait for the
  user before starting the next phase.
- Must run on Windows, macOS and Linux. Python for all automation: no bash
  scripts, no Makefiles.
- Virtual environment plus `requirements.txt`. Never install anything globally.
- Raw SQL only, no ORM: transaction and locking behaviour must stay visible.
- No login system, no web framework. Streamlit only if the user asks.
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
- `slotrush/`: `__main__.py` (argparse CLI), `config.py` (paths, .env reader),
  `db.py` (`pg_connect`, `mongo_client`), `containers.py` (docker compose),
  `check.py`.
- Run with the venv's Python: `.venv\Scripts\python` (Windows) or
  `.venv/bin/python` (macOS/Linux).
- `python -m slotrush up | down [--wipe] | check`; tests: `python -m pytest`.

## Phase checklist
- [~] 0. Repo skeleton, SPEC.md, CLAUDE.md, docker compose, connection check for both databases
  (code committed; live check waits for Docker Desktop to be installed)
- [ ] 1. Schema, constraints, functions, views, roles, RLS, tests, `docs/er-diagram.md`
- [ ] 2. Data generator, loader, `check-data`
- [ ] 3. Demos 1 to 4 (lost-update, locking, serializable, deadlock)
- [ ] 4. Crash demo
- [ ] 5. Index benchmark and `docs/query-processing.md`
- [ ] 6. Normalisation export, document, lossless check
- [ ] 7. MongoDB reviews and `docs/nosql-cap.md`
- [ ] 8. Wrap-up: README, `review` command, contemporary issues, report outline
- [ ] 9. Stretch (only if asked): schedule simulator

Current status: Phase 0 built. Docker is not installed on this machine yet, so
`check` and the 6 database tests in `tests/test_connection.py` cannot pass until
it is. Phase 1 plan is approved; do not start it until the user says so.
