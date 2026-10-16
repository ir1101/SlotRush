"""Phase 0: both databases are reachable and configured the way the demos need."""


def setting(pg, name):
    return pg.execute("SELECT current_setting(%s)", (name,)).fetchone()[0]


def test_postgres_is_major_version_17(pg):
    # server_version_num is e.g. 170006 for 17.6
    assert int(setting(pg, "server_version_num")) // 10000 == 17


def test_durability_settings_are_defaults(pg):
    # The crash demo relies on COMMIT waiting for the WAL flush.
    assert setting(pg, "fsync") == "on"
    assert setting(pg, "synchronous_commit") == "on"


def test_max_connections_raised_for_bots(pg):
    assert int(setting(pg, "max_connections")) == 200


def test_postgres_runs_a_query(pg):
    assert pg.execute("SELECT 1 + 1").fetchone()[0] == 2


def test_mongo_answers_ping(mongo):
    assert mongo.admin.command("ping")["ok"] == 1.0


def test_mongo_is_major_version_8(mongo):
    assert mongo.server_info()["version"].startswith("8.")
