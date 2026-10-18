"""Start and stop the Docker containers from Python.

Using Python instead of shell scripts keeps the same commands working on
Windows, macOS and Linux. The crash demo (Phase 4) will reuse these helpers.
"""
import shutil
import subprocess
import time

from .config import ROOT, ensure_env_file, read_env

PG_CONTAINER = "slotrush-postgres"      # fixed names, set in docker-compose.yml
MONGO_CONTAINER = "slotrush-mongo"


def require_docker() -> None:
    """Stop with a clear message if the docker command is not installed."""
    if shutil.which("docker") is None:
        raise SystemExit(
            "The 'docker' command was not found.\n"
            "Install Docker Desktop (Windows/macOS) or Docker Engine with the compose "
            "plugin (Linux), start it, then run this command again."
        )


def compose(*args: str) -> int:
    """Run 'docker compose <args>' from the repo root and return its exit code."""
    require_docker()
    return subprocess.run(["docker", "compose", *args], cwd=ROOT).returncode


def up() -> int:
    """Create .env if needed, start both containers and wait until they are healthy."""
    if ensure_env_file():
        # flush so this line appears before any docker output or error
        print("Created .env from .env.example.", flush=True)
    # --wait blocks until every health check in docker-compose.yml passes.
    code = compose("up", "--detach", "--wait")
    if code == 0:
        print("PostgreSQL and MongoDB are running and healthy.")
    return code


def down(wipe: bool = False) -> int:
    """Stop and remove the containers. With wipe=True also delete the data volumes."""
    args = ["down"]
    if wipe:
        args.append("--volumes")
    return compose(*args)


def docker(*args: str) -> subprocess.CompletedProcess:
    """Run 'docker <args>' and capture its output as text."""
    require_docker()
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def postgres_log_since(since: str) -> list[str]:
    """PostgreSQL's server log lines written since an RFC 3339 time (e.g. 2026-10-17T09:00:00Z).
    The official image logs to stderr, which 'docker logs' replays."""
    result = docker("logs", "--since", since, PG_CONTAINER)
    return (result.stdout + result.stderr).splitlines()


def kill_postgres() -> None:
    """SIGKILL the PostgreSQL server: no shutdown checkpoint, no clean exit."""
    docker("kill", PG_CONTAINER)


def start_postgres_and_wait(timeout: float = 120) -> float:
    """Start the container again and wait until pg_isready reports it accepts
    connections (crash recovery has finished by then). Returns the seconds waited."""
    env = read_env()
    started = time.perf_counter()
    docker("start", PG_CONTAINER)
    while time.perf_counter() - started < timeout:
        ready = docker("exec", PG_CONTAINER, "pg_isready", "-q",
                       "-U", env["POSTGRES_USER"], "-d", env["POSTGRES_DB"])
        if ready.returncode == 0:
            return time.perf_counter() - started
        time.sleep(0.5)
    raise SystemExit(f"PostgreSQL did not become ready within {timeout:.0f} s")
