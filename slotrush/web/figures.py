"""Charts for the evidence page, drawn by the browser instead of shown as PNGs.

Each command saves the numbers behind its chart in results/, next to the PNG.
This module reads those files and turns every chart into "panels": plain dicts
that templates/_charts.html draws with HTML and a little SVG, in the site's own
type and colours. All the arithmetic (scales, ticks, positions in percent)
happens here, so the template only places things. The PNGs stay in results/
for the report; FIGURES says which drawn figure stands in for which PNG.

Panel kinds: bars, hist, hbars, line, dots (log scale) and timeline.
"""
import csv
import json
import math

from ..config import RESULTS_DIR

# The three concurrency runs, named as on the home page's guard picker.
RUNS = [("lost_update", "No lock"), ("locking", "Row lock"), ("serializable", "Serializable")]
QUERY_NAMES = {"Q1": "Student timetable", "Q2": "Seats in a slot", "Q3": "Course and time range",
               "Q4": "Below minimum credits", "Q5": "Faculty class list"}
SETUPS = [("none", "no index"), ("btree", "B-tree"), ("hash", "hash")]
SVG_W, SVG_H = 1000, 400        # the line charts' drawing box; CSS stretches it to fit


# ------------------------------------------------------------------ reading results/

def read_json(name: str):
    path = RESULTS_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def read_csv(name: str):
    path = RESULTS_DIR / name
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------ scales

def nice_top(value: float) -> float:
    """The top of an axis: the first round number (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8 or 10
    times a power of ten) at or above value."""
    if value <= 0:
        return 1
    power = 10 ** math.floor(math.log10(value))
    steps = (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10)
    return next(step * power for step in steps if value <= step * power * (1 + 1e-9))


def pct(value: float, top: float) -> float:
    """value as a percentage of top: CSS heights, widths and positions."""
    return round(100 * value / top, 2) if top else 0


def ticks(top: float) -> list[dict]:
    """Three axis labels, 0, half way and the top, each with its position in percent."""
    return [{"at": pct(v, top), "text": f"{v:g}"} for v in (0, top / 2, top)]


# ------------------------------------------------------------------ panel builders

def bars(title: str, items: list, note: str = "", rule: float | None = None,
         top: float | None = None) -> dict:
    """A few labelled bars. items: [(label, value, text, tone)].
    rule: a value to mark across all bars (the capacity). top: fix the scale's top."""
    top = top or max([value for _, value, _, _ in items] + [rule or 0]) or 1
    return {"kind": "bars", "title": title, "note": note,
            "bars": [{"label": label, "h": pct(value, top), "text": text, "tone": tone}
                     for label, value, text, tone in items],
            "rule": pct(rule, top) if rule is not None else None}


def hist(title: str, counts: list, unit: str, x_ticks: list, marks: list = ()) -> dict:
    """Many unlabelled bars with a y axis. Positions in x_ticks and marks are counted
    in bins from the left edge, e.g. 0.5 is the middle of the first bin."""
    top, n = nice_top(max(counts)), len(counts)
    return {"kind": "hist", "title": title, "unit": unit,
            "bins": [pct(c, top) for c in counts], "y_ticks": ticks(top),
            "x_ticks": [{"at": pct(at, n), "text": text} for at, text in x_ticks],
            "marks": [{"at": pct(at, n), "text": text} for at, text in marks]}


def line(title: str, series: list, x_label: str, unit: str,
         x_top: float | None = None, marker: tuple | None = None) -> dict:
    """Lines over time. series: [(name, [(x, y), ...], tone, shaded)].
    marker: (x, text), a moment to mark with a vertical line."""
    x_top = x_top or nice_top(max(x for _, points, _, _ in series for x, _ in points))
    y_top = nice_top(max(y for _, points, _, _ in series for _, y in points))

    def svg_x(x):
        return f"{SVG_W * x / x_top:.1f}"

    def svg_points(points):
        # SVG's y axis points down, so a value of 0 sits at the bottom (SVG_H).
        return " ".join(f"{svg_x(x)},{SVG_H - SVG_H * y / y_top:.1f}" for x, y in points)

    drawn = []
    for name, points, tone, shaded in series:
        one = {"name": name, "tone": tone, "points": svg_points(points)}
        if shaded:      # the same line closed along the bottom edge: the shaded area under it
            one["area"] = (f"{one['points']} {svg_x(points[-1][0])},{SVG_H} "
                           f"{svg_x(points[0][0])},{SVG_H}")
        drawn.append(one)
    return {"kind": "line", "title": title, "x_label": x_label, "unit": unit,
            "series": drawn, "x_ticks": ticks(x_top), "y_ticks": ticks(y_top),
            "marker": {"at": pct(marker[0], x_top), "text": marker[1]} if marker else None,
            "legend": [(s["name"], s["tone"]) for s in drawn] if len(drawn) > 1 else []}


# ------------------------------------------------------------------ one function per PNG

def data_profile():
    data = read_json("data_profile.json")
    if not data:
        return None
    by_credits = {int(c): n for c, n in data["students_by_credits"].items()}
    low, high = min(by_credits), max(max(by_credits), data["max_credits"])
    counts = [by_credits.get(c, 0) for c in range(low, high + 1)]
    min_c, max_c = data["min_credits"], data["max_credits"]
    return [
        hist("Registered credits per student", counts, "students",
             x_ticks=[(c - low + 0.5, str(c)) for c in range(low, high + 1, 3)],
             marks=[(min_c - low, f"min {min_c}"), (max_c - low + 1, f"max {max_c}")]),
        # 20 bins of 5%: a fill of v% sits v / 5 bins from the left.
        hist("How full each offering is", list(data["offerings_by_fill_pct"].values()), "offerings",
             x_ticks=[(v / 5, f"{v}%") for v in (0, 25, 50, 75, 100)]),
    ]


def bench():
    rows = read_csv("bench_summary.csv")
    if not rows:
        return None
    medians = {(r["query"], r["setup"]): float(r["median_ms"]) for r in rows}
    queries = list(dict.fromkeys(r["query"] for r in rows))           # in file order, once each
    # A log scale from the power of ten below the fastest time to the one above the slowest.
    low = 10 ** math.floor(math.log10(min(medians.values())))
    high = 10 ** math.ceil(math.log10(max(medians.values())))

    def x(ms):
        return pct(math.log10(ms / low), math.log10(high / low))

    panel_rows = []
    for q in queries:
        dots = [{"setup": s, "x": x(medians[(q, s)]), "from": x(medians[(q, "none")])}
                for s, _ in SETUPS]
        panel_rows.append({
            "label": f"{q[:2]} {QUERY_NAMES.get(q[:2], q)}",
            "times": ", ".join(f"{name} {medians[(q, s)]:.3g}" for s, name in SETUPS) + " ms",
            "low": min(d["x"] for d in dots), "high": max(d["x"] for d in dots), "dots": dots})
    powers = range(round(math.log10(low)), round(math.log10(high)) + 1)
    return [{"kind": "dots", "title": "Median time per query in ms, log scale",
             "rows": panel_rows, "legend": [(name, s) for s, name in SETUPS],
             "x_ticks": [{"at": x(10 ** k), "text": f"{10 ** k:g}"} for k in powers]}]


def crash(run_name: str, log_name: str):
    run, log = read_json(f"demo_{run_name}.json"), read_csv(log_name)
    if not run or log is None:
        return None
    times = sorted(float(r["acknowledged_at_s"]) for r in log)
    kill, lost = run["seconds"], run["missing"]
    return [
        line("Acknowledged commits before the kill",
             [("commits logged", [(0, 0)] + [(t, k) for k, t in enumerate(times, 1)], "ink", True)],
             x_label="seconds", unit="commits", x_top=nice_top(kill * 1.25),
             marker=(kill, "docker kill")),
        bars("After the restart", [
            ("logged", run["logged"], f"{run['logged']:,}", "ink"),
            ("found after restart", run["found"], f"{run['found']:,}", "ink"),
            ("logged but missing", lost, f"{lost:,}", "critical" if lost else "ink"),
            ("in the table, not logged", run["unlogged"], f"{run['unlogged']:,}", "hatch")],
            note=f"{lost} acknowledged commits were lost." if lost
            else "Nothing acknowledged was lost."),
    ]


def lost_update():
    run, reads = read_json("demo_lost_update.json"), read_csv("demo_lost_update_reads.csv")
    if not run or reads is None:
        return None
    cap, admitted, left = run["capacity"], run["admitted"], run["seats_left"]
    return [
        bars("Over-booked", [("capacity", cap, f"{cap}", "soft"),
                             ("admitted", admitted, f"{admitted}", "critical"),
                             ("seats_left at the end", left, f"{left}", "critical")],
             note=f"{admitted - cap} students too many, and the counter still says {left} left."),
        line("Every bot read a stale seats_left", [
            ("seats_left each bot read",
             [(int(r["commit_order"]), int(r["seats_left_read"])) for r in reads], "critical", False),
            ("what it should have read",
             [(int(r["commit_order"]), int(r["should_have_read"])) for r in reads], "dashed", False)],
             x_label="admitted bots, in commit order", unit="seats_left"),
    ]


def locking():
    run, queue = read_json("demo_locking.json"), read_csv("demo_locking_queue.csv")
    if not run or not queue:
        return None
    cap, full = run["capacity"], run.get("full", run["bots"] - run["admitted"])
    return [
        line("Sessions waiting for the row lock",
             [("waiting sessions",
               [(float(r["seconds"]), int(r["waiting_sessions"])) for r in queue], "ink", True)],
             x_label="seconds since the monitor started", unit="sessions"),
        bars("Exactly the capacity", [("capacity", cap, f"{cap}", "soft"),
                                      ("OK, admitted", run["admitted"], f"{run['admitted']}", "ink"),
                                      ("FULL, waitlisted", full, f"{full}", "hatch")]),
    ]


def isolation():
    runs = [(label, read_json(f"demo_{name}.json")) for name, label in RUNS]
    if any(run is None for _, run in runs):
        return None
    cap = runs[0][1]["capacity"]
    return [
        bars("Students admitted",
             [(label, r["admitted"], f"{r['admitted']}", "critical" if r["admitted"] > cap else "ink")
              for label, r in runs], note=f"The line is the capacity, {cap}.", rule=cap),
        bars("Total time", [(label, r["seconds"], f"{r['seconds']:.2f} s", "ink") for label, r in runs]),
        bars("Retries after SQLSTATE 40001",
             [(label, r["retries"], f"{r['retries']:,}", "ink") for label, r in runs]),
    ]


def deadlock():
    rows = read_csv("demo_deadlock_timeline.csv")
    if not rows:
        return None

    def t(row, moment):
        return float(row[f"{moment}_s"])

    top = nice_top(max(t(r, "end") for r in rows))
    titles = {"naive": "drop_course() then register(): a deadlock",
              "swap": "swap_course(), lower offering id locked first"}
    runs, offset = [], 0.0          # offset: the second run plays after the first
    for run in ("naive", "swap"):
        mine = [r for r in rows if r["run"] == run]
        drawn = []
        for r in mine:
            if run == "naive":      # the drop holds a lock, then register() waits for the other
                spans = [("ink", t(r, "begin"), t(r, "dropped")), ("hatch", t(r, "asked"), t(r, "end"))]
            else:                   # swap_course() waits for its locks, then holds both
                spans = [("hatch", t(r, "asked"), t(r, "dropped")), ("ink", t(r, "dropped"), t(r, "end"))]
            drawn.append({
                "label": f"Student {r['student']}", "result": r["result"],
                "done": round(offset + t(r, "end"), 3),
                # start and seconds replay each span over the time it really took
                "spans": [{"tone": tone, "x": pct(a, top), "w": max(pct(b - a, top), 0.6),
                           "start": round(offset + a, 3), "seconds": round(max(b - a, 0.01), 3)}
                          for tone, a, b in spans]})
        runs.append({"title": titles[run], "rows": drawn})
        offset += max(t(r, "end") for r in mine) + 0.6
    return [{"kind": "timeline", "title": "Two students swap offerings at the same time",
             "runs": runs, "x_ticks": ticks(top), "x_label": "seconds",
             "legend": [("working, holding row locks", "ink"),
                        ("blocked, waiting for a row lock", "hatch")]}]


def nosql():
    data = read_json("nosql_aggregations.json")
    if not data:
        return None
    tags = data["most_common_tags"]
    most = max(tag["count"] for tag in tags)
    return [
        {"kind": "hbars", "title": "Most common review tags",
         "rows": [{"label": tag["_id"], "w": pct(tag["count"], most), "text": f"{tag['count']:,}"}
                  for tag in tags]},
        bars("Average rating by course type",
             [(row["_id"].capitalize(), row["avg_rating"], f"{row['avg_rating']:.2f}", "ink")
              for row in data["rating_by_course_type"]], note="On the 1 to 5 scale.", top=5),
    ]


# PNG in results/ -> (function that draws it, files its numbers come from)
FIGURES = {
    "data_profile.png": (data_profile, ["data_profile.json"]),
    "bench_chart.png": (bench, ["bench_summary.csv"]),
    "demo_crash.png": (lambda: crash("crash", "commit_log.csv"),
                       ["demo_crash.json", "commit_log.csv"]),
    "demo_crash_async.png": (lambda: crash("crash_async", "commit_log_async.csv"),
                             ["demo_crash_async.json", "commit_log_async.csv"]),
    "demo_lost_update.png": (lost_update, ["demo_lost_update.json", "demo_lost_update_reads.csv"]),
    "demo_locking.png": (locking, ["demo_locking.json", "demo_locking_queue.csv"]),
    "demo_isolation_comparison.png": (isolation, ["demo_lost_update.json", "demo_locking.json",
                                                  "demo_serializable.json"]),
    "demo_deadlock.png": (deadlock, ["demo_deadlock_timeline.csv"]),
    "nosql_reviews.png": (nosql, ["nosql_aggregations.json"]),
}


def drawn(png: str) -> dict | None:
    """The drawn version of a PNG ({"panels", "sources"}), or None to show the PNG itself:
    when its numbers have not been saved yet, or come from an older run without them."""
    if png not in FIGURES:
        return None
    build, sources = FIGURES[png]
    try:
        panels = build()
    except (KeyError, ValueError, IndexError):
        return None
    return {"panels": panels, "sources": sources} if panels else None
