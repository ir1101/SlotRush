"""The charts the evidence page draws itself (slotrush/web/figures.py).

No database needed: each test writes a few small results files into a
temporary folder and points figures.py at it.
"""
import json

import pytest

from slotrush.web import figures


@pytest.fixture
def results(tmp_path, monkeypatch):
    monkeypatch.setattr(figures, "RESULTS_DIR", tmp_path)
    return tmp_path


def save_runs(folder, lost_update, locking, serializable):
    for name, admitted in (("lost_update", lost_update), ("locking", locking),
                           ("serializable", serializable)):
        run = {"capacity": 30, "bots": 80, "admitted": admitted, "seats_left": 0,
               "seconds": 1.5, "retries": 0}
        (folder / f"demo_{name}.json").write_text(json.dumps(run), encoding="utf-8")


@pytest.mark.parametrize("value, top", [(79, 80), (80, 80), (358, 400), (4.717, 5),
                                        (0.4, 0.4), (1372, 1500), (0, 1)])
def test_axis_top_is_a_round_number_at_or_above_the_value(value, top):
    assert figures.nice_top(value) == pytest.approx(top)


def test_a_png_without_saved_numbers_is_shown_as_it_is(results):
    assert figures.drawn("demo_locking.png") is None          # nothing saved yet
    assert figures.drawn("phase0_connection_check.txt") is None


def test_an_older_results_file_falls_back_to_the_png(results):
    (results / "demo_crash.json").write_text('{"run": "crash"}', encoding="utf-8")
    (results / "commit_log.csv").write_text("reg_no,offering_id,status,acknowledged_at_s\n",
                                            encoding="utf-8")
    assert figures.drawn("demo_crash.png") is None


def test_isolation_comparison_marks_overbooking_and_capacity(results):
    save_runs(results, lost_update=80, locking=30, serializable=30)
    fig = figures.drawn("demo_isolation_comparison.png")
    admitted = fig["panels"][0]
    assert [b["tone"] for b in admitted["bars"]] == ["critical", "ink", "ink"]
    assert [b["h"] for b in admitted["bars"]] == [100, 37.5, 37.5]   # 80 is the tallest
    assert admitted["rule"] == 37.5                                  # the capacity line, 30 of 80
    assert "demo_serializable.json" in fig["sources"]


def test_bench_dots_sit_on_a_log_scale_and_start_at_no_index(results):
    (results / "bench_summary.csv").write_text(
        "query,setup,median_ms,access_paths\n"
        "Q1_student_timetable,none,100,Seq Scan\n"
        "Q1_student_timetable,btree,1,Index Scan\n"
        "Q1_student_timetable,hash,10,Index Scan\n", encoding="utf-8")
    panel = figures.bench()[0]
    dots = {d["setup"]: d for d in panel["rows"][0]["dots"]}
    # 1 ms to 100 ms is two powers of ten: 1 at the left, 10 half way, 100 at the right.
    assert (dots["btree"]["x"], dots["hash"]["x"], dots["none"]["x"]) == (0, 50, 100)
    assert all(d["from"] == 100 for d in dots.values())             # they all travel from "none"
    assert [t["text"] for t in panel["x_ticks"]] == ["1", "10", "100"]


def test_line_points_are_flipped_for_svg(results):
    panel = figures.line("t", [("s", [(0, 0), (5, 10)], "ink", True)], "x", "y")
    # x 0..5 -> 0..1000; y 0 sits at the bottom of the 400-high box, y 10 at the top.
    assert panel["series"][0]["points"] == "0.0,400.0 1000.0,0.0"
    assert panel["series"][0]["area"].endswith("1000.0,400 0.0,400")


def test_deadlock_timeline_replays_the_second_run_after_the_first(results):
    (results / "demo_deadlock_timeline.csv").write_text(
        "run,student,result,begin_s,dropped_s,asked_s,end_s\n"
        "naive,A,committed (OK),0,0.02,0.03,1.0\n"
        'naive,B,"deadlock victim, rolled back",0,0.03,0.03,1.0\n'
        "swap,A,committed (OK),0,0.04,0.03,0.5\n"
        "swap,B,committed (OK),0,0.55,0.03,1.0\n", encoding="utf-8")
    runs = figures.deadlock()[0]["runs"]
    first_swap_span = runs[1]["rows"][0]["spans"][0]
    assert first_swap_span["start"] == pytest.approx(1.0 + 0.6 + 0.03)   # after run 1 + a pause
    assert runs[0]["rows"][1]["spans"][1]["tone"] == "hatch"             # B blocked in register()
