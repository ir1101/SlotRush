"""The web front end, driven through Flask's test client against the test database.

Uses the "committed" fixture data (tests/fixtures.py): students 21BCE0001..5,
faculty 1001 (offerings 101-104) and 1002 (105-107).
"""
import pytest

from slotrush.web import app as web_app
from slotrush.web import data, figures

from .fixtures import S1, S2


@pytest.fixture
def client(committed, test_db):
    app = web_app.create_app(dbname=test_db)
    app.config["TESTING"] = True
    yield app.test_client()
    data.close_pool()


def login_student(client, reg_no):
    return client.post("/login", data={"role": "student", "reg_no": reg_no})


def test_home_shows_the_race_and_the_receipt(client):
    page = client.get("/").get_data(as_text=True)
    assert "80 students" in page and "Who got a seat" in page
    # The receipt adds the registrations per department; the fixture has none yet.
    assert "Every seat accounted for" in page
    assert '<p class="total" data-count="0">0</p>' in page


def test_pages_need_the_right_role(client):
    response = client.get("/student")
    assert response.status_code == 302 and "/login?need=student" in response.location


def test_unknown_student_cannot_log_in(client):
    response = login_student(client, "99ZZZ0000")
    assert "error=" in response.location


def test_student_login_and_queries_panel(client):
    response = login_student(client, S1)
    assert response.location.endswith("/student")
    page = client.get("/student").get_data(as_text=True)
    assert "Student1 Test1" in page
    # The Queries panel shows the page really ran as student_role with app.reg_no set.
    assert "SET LOCAL ROLE student_role" in page
    assert "set_config(&#39;app.reg_no&#39;" in page


def test_register_through_the_web_returns_ok(client, committed):
    login_student(client, S1)
    response = client.post("/student/register", data={"offering_id": 101})
    page = client.get(response.location).get_data(as_text=True)
    assert '<span class="status">OK</span>' in page
    check = committed()
    assert check.execute("SELECT count(*) FROM registration WHERE reg_no = %s AND offering_id = 101",
                         (S1,)).fetchone()[0] == 1


def test_register_clash_is_reported(client):
    login_student(client, S1)
    client.post("/student/register", data={"offering_id": 101})       # T01
    response = client.post("/student/register", data={"offering_id": 104})   # L01 overlaps T01
    page = client.get(response.location).get_data(as_text=True)
    assert '<span class="status">CLASH</span>' in page


def test_drop_and_swap(client, committed):
    login_student(client, S1)
    client.post("/student/register", data={"offering_id": 105})
    client.post("/student/swap", data={"from_offering": 105, "to_offering": 107})
    check = committed()
    rows = check.execute("SELECT offering_id FROM registration WHERE reg_no = %s", (S1,)).fetchall()
    assert rows == [(107,)]
    client.post("/student/drop", data={"offering_id": 107})
    assert check.execute("SELECT count(*) FROM registration WHERE reg_no = %s",
                         (S1,)).fetchone()[0] == 0


def test_student_sees_only_own_classes(client, committed):
    setup = committed()
    setup.execute("SELECT register(%s, 105)", (S2,))    # S2's class, BMAT101L
    setup.commit()
    login_student(client, S1)
    page = client.get("/student").get_data(as_text=True)
    assert "BMAT101L" not in page


def test_faculty_sees_only_own_class_lists(client, committed):
    setup = committed()
    setup.execute("SELECT register(%s, 101)", (S1,))    # faculty 1001
    setup.execute("SELECT register(%s, 105)", (S2,))    # faculty 1002
    setup.commit()
    client.post("/login", data={"role": "faculty", "faculty_id": "1001"})
    page = client.get("/faculty").get_data(as_text=True)
    assert S1 in page and S2 not in page


def test_admin_sees_every_offering(client):
    client.post("/login", data={"role": "admin"})
    page = client.get("/admin").get_data(as_text=True)
    assert "7 offerings" in page


def test_evidence_page_and_results_files(client):
    assert client.get("/evidence").status_code == 200
    # Paths that climb out of results/ are refused.
    assert client.get("/results/../.env").status_code == 404


def test_evidence_draws_charts_from_saved_numbers(client, tmp_path, monkeypatch):
    # A results/ folder with the bench numbers (drawn by the page) and a PNG whose
    # numbers were never saved (shown as the PNG itself).
    (tmp_path / "bench_chart.png").write_bytes(b"png")
    (tmp_path / "bench_summary.csv").write_text(
        "query,setup,median_ms,access_paths\n"
        "Q1_student_timetable,none,12.4,Seq Scan\n"
        "Q1_student_timetable,btree,0.19,Bitmap Heap Scan\n"
        "Q1_student_timetable,hash,0.17,Bitmap Heap Scan\n", encoding="utf-8")
    (tmp_path / "nosql_reviews.png").write_bytes(b"png")
    monkeypatch.setattr(web_app, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(figures, "RESULTS_DIR", tmp_path)

    page = client.get("/evidence").get_data(as_text=True)
    assert 'class="chart" data-chart' in page and "Q1 Student timetable" in page
    assert 'href="/results/bench_chart.png">The PNG for the report' in page
    assert '<img src="/results/nosql_reviews.png"' in page          # no numbers: the PNG
    assert '<img src="/results/bench_chart.png"' not in page
