"""Project paths and the settings stored in .env.

The .env file is just KEY=VALUE lines, so we read it ourselves instead of adding
another package. docker compose reads the same file, which keeps Python and the
containers in agreement about ports and passwords.
"""
import shutil
from pathlib import Path

# Repo root = the folder that contains the slotrush/ package.
ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
RESULTS_DIR = ROOT / "results"   # every chart, CSV, plan and log goes here
SQL_DIR = ROOT / "sql"

SEED = 2026                      # the one random seed used everywhere
SEMESTER = "FALL2026"            # the semester all generated data belongs to
DEMO_SEMESTER = "DEMO"           # demo offerings live here, apart from the real data
TEST_DB_SUFFIX = "_test"         # tests use <POSTGRES_DB>_test, never the real database


def ensure_env_file() -> bool:
    """Create .env from .env.example if it is missing. Returns True if it was created."""
    if ENV_FILE.exists():
        return False
    shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
    return True


def read_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Parse KEY=VALUE lines. Blank lines and lines starting with # are skipped."""
    if not path.exists():
        raise SystemExit(
            f"{path.name} not found. Run 'python -m slotrush up', "
            "which creates it from .env.example."
        )
    settings = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # partition splits at the FIRST '=', so values may themselves contain '='.
        key, _, value = line.partition("=")
        settings[key.strip()] = value.strip()
    return settings
