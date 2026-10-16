"""Tests for the .env reader. These need no database."""
import pytest

from slotrush.config import ENV_EXAMPLE, read_env


def test_read_env_skips_comments_and_blank_lines(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# a comment\n\nPOSTGRES_PORT=5432\n  MONGO_PORT = 27017  \n",
                        encoding="utf-8")
    assert read_env(env_file) == {"POSTGRES_PORT": "5432", "MONGO_PORT": "27017"}


def test_read_env_keeps_equals_signs_inside_values(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("POSTGRES_PASSWORD=a=b=c\n", encoding="utf-8")
    assert read_env(env_file)["POSTGRES_PASSWORD"] == "a=b=c"


def test_read_env_missing_file_gives_a_hint(tmp_path):
    with pytest.raises(SystemExit, match="slotrush up"):
        read_env(tmp_path / ".env")


def test_env_example_has_every_key_the_code_uses():
    keys = set(read_env(ENV_EXAMPLE))
    needed = {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_HOST",
              "POSTGRES_PORT", "MONGO_USER", "MONGO_PASSWORD", "MONGO_HOST", "MONGO_PORT"}
    assert needed <= keys
