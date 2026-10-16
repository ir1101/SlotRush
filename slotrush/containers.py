"""Start and stop the Docker containers from Python.

Using Python instead of shell scripts keeps the same commands working on
Windows, macOS and Linux. The crash demo (Phase 4) will reuse these helpers.
"""
import shutil
import subprocess

from .config import ROOT, ensure_env_file

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
