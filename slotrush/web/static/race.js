// The race, replayed on the home page.
//
// 80 bots ask one 30-seat class for a place at the same moment. The totals, the
// counters and the clock come from the saved runs in results/ (home.html passes
// them in as JSON); the path each square takes is drawn, not recorded.
// Every frame is a pure function of the time t: show(t) paints any moment, so a
// replay just restarts the clock. With reduced motion only the end is shown.

(() => {
  const figure = document.querySelector(".race");
  const source = document.getElementById("race-data");
  if (!figure || !source) return;

  const runs = JSON.parse(source.textContent);       // { none: {...}, lock: {...}, serial: {...} }
  const canvas = figure.querySelector("canvas");
  const ctx = canvas.getContext("2d");
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  const out = {};                                     // the counters above the picture
  figure.querySelectorAll("[data-out]").forEach((el) => { out[el.dataset.out] = el; });

  // ------------------------------------------------------------------ helpers

  // mulberry32: a tiny random generator with a fixed seed, so every replay is the same.
  function seeded(seed) {
    return () => {
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Fisher-Yates shuffle with the seeded generator: a fair, repeatable order.
  function shuffle(items, random) {
    for (let i = items.length - 1; i > 0; i--) {
      const j = Math.floor(random() * (i + 1));
      [items[i], items[j]] = [items[j], items[i]];
    }
    return items;
  }

  // Cubic ease-in-out: a square speeds up as it leaves and slows down as it arrives.
  const ease = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);

  // Places a square can be: a cell at the door, a seat (level > 0 means sitting on
  // top of someone: over-booked) or a cell among the bots told FULL.
  const door = (i) => ({ zone: "door", index: i });
  const seat = (i, level = 0) => ({ zone: "seat", index: i, level });
  const full = (i) => ({ zone: "full", index: i });

  // ------------------------------------------------------------------ the three runs as plans
  // A plan gives every bot a list of legs { from, to, t0, t1, bounce } in seconds of
  // replay, and says when each admitted bot reaches its seat (for the counters).

  function plan(guard) {
    const run = runs[guard];
    const random = seeded(612931887);
    const { bots, capacity, admitted } = run;
    const length = Math.min(Math.max(run.seconds, 2.6), 6);   // real time, but at least 2.6 s
    const walk = 0.5;                                          // seconds for one walk to a seat
    const students = [];

    if (guard === "none") {
      // No lock: everyone reads seats_left = 30 at once, thinks, writes back 29.
      // So they all walk in together, two or three to a seat.
      for (let i = 0; i < bots; i++) {
        const t0 = 0.1 * length + random() * 0.15 * length;
        const t1 = 0.5 * length + random() * 0.4 * length;
        const to = i < admitted ? seat(i % capacity, Math.floor(i / capacity)) : full(i - admitted);
        students.push({ legs: [{ from: door(i), to, t0, t1 }] });
      }
    } else if (guard === "lock") {
      // Row lock: one bot holds the offering row at a time, the rest wait their turn.
      const turn = (length - walk) / bots;
      for (let i = 0; i < bots; i++) {
        const to = i < admitted ? seat(i) : full(i - admitted);
        students.push({ waits: true, legs: [{ from: door(i), to, t0: i * turn, t1: i * turn + walk }] });
      }
    } else {
      // Serializable: everyone tries at once; conflicting transactions are aborted
      // (SQLSTATE 40001) and come back to try again, until the seats run out.
      const order = shuffle([...Array(bots).keys()], random);   // who wins, in what order
      const lastWin = 0.75 * length;
      const winAt = new Map(order.slice(0, admitted).map((bot, k) =>
        [bot, [k, 0.1 * length + (k / Math.max(admitted - 1, 1)) * (lastWin - 0.1 * length)]]));
      let told = 0;                                    // bots sent to FULL so far
      for (let i = 0; i < bots; i++) {
        const legs = [];
        const win = winAt.get(i);
        const done = win ? win[1] : lastWin + random() * 0.1 * length;
        // try, get aborted, go back; again and again until this bot's moment
        for (let t = random() * 0.3; t + 0.45 < done; t += 0.5 + random() * 0.25) {
          legs.push({ from: door(i), to: seat(Math.floor(random() * capacity)), t0: t, t1: t + 0.45, bounce: true });
        }
        legs.push({ from: door(i), to: win ? seat(win[0]) : full(told++), t0: done, t1: done + walk });
        students.push({ legs });
      }
    }

    // When each admitted bot sits down, in order: drives "admitted" and seats_left.
    const seated = students.map((s) => s.legs[s.legs.length - 1])
      .filter((leg) => leg.to.zone === "seat").map((leg) => leg.t1).sort((a, b) => a - b);
    const end = Math.max(...students.map((s) => s.legs[s.legs.length - 1].t1));
    return { guard, run, students, seated, end, lastWin: guard === "serial" ? 0.75 * length : end };
  }

  // The counters at replay time t.
  function counters(p, t) {
    const n = p.seated.filter((at) => at <= t).length;
    const { capacity } = p.run;
    return {
      admitted: n,
      // no lock: every bot wrote back its stale 30 - 1, so the counter sticks at 29
      seats: p.guard === "none" ? (n > 0 ? p.run.seats_left : capacity)
                                : Math.max(capacity - n, p.run.seats_left),
      retries: Math.round(p.run.retries * Math.min(t / p.lastWin, 1)),
      seconds: p.run.seconds * Math.min(t / p.end, 1),
    };
  }

  // ------------------------------------------------------------------ where things are
  // Three zones side by side, or stacked on a narrow screen: the door, the seats in
  // rows of ten, and the bots told FULL. One "unit" is one cell.

  let box = null;
  function layout(p) {
    const width = canvas.clientWidth;
    const narrow = width < 640;
    const doorCols = narrow ? 16 : 10;
    const unit = narrow ? width / 16 : width / 38;
    const label = 30;                                         // room above each zone for its name
    const rows = (n, cols) => Math.max(Math.ceil(n / cols), 1);
    const doorRows = rows(p.run.bots, doorCols);
    const seatRows = rows(p.run.capacity, 10);
    const fullRows = rows(p.run.bots - Math.min(p.run.admitted, p.run.capacity), 10);
    let zones;
    if (narrow) {
      const seatY = label + doorRows * unit + unit + label;
      const fullY = seatY + seatRows * unit + unit + label;
      zones = { door: { x: 0, y: label, cols: doorCols },
                seat: { x: 3 * unit, y: seatY, cols: 10 },
                full: { x: 3 * unit, y: fullY, cols: 10 } };
      box = { unit, zones, height: fullY + fullRows * unit };
    } else {
      // side by side, tops aligned, so the three names share one line
      zones = { door: { x: 0, y: label, cols: doorCols },
                seat: { x: 14 * unit, y: label, cols: 10 },
                full: { x: 28 * unit, y: label, cols: 10 } };
      box = { unit, zones, height: label + Math.max(doorRows, seatRows, fullRows) * unit };
    }
    // Sharp on high-density screens: draw at device pixels, think in CSS pixels.
    const ratio = window.devicePixelRatio || 1;
    canvas.style.height = `${box.height}px`;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(box.height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const caption = getComputedStyle(figure.querySelector("figcaption"));
    box.font = `${caption.fontSize} ${caption.fontFamily}`;     // zone names in the caption's type
  }

  // The centre of a place, in CSS pixels. A bot on top of another sits up and to the right.
  function point(place) {
    const z = box.zones[place.zone];
    const col = place.index % z.cols;
    const row = Math.floor(place.index / z.cols);
    const lift = (place.level || 0) * 0.2 * box.unit;
    return [z.x + (col + 0.5) * box.unit + lift, z.y + (row + 0.5) * box.unit - lift];
  }

  // Where one bot is at time t, and how to paint it.
  function where(student, t) {
    let leg = null;
    for (const l of student.legs) if (l.t0 <= t) leg = l;     // the latest leg that has started
    if (!leg) return { at: point(student.legs[0].from), tone: student.waits ? "waiting" : "ink" };
    const a = point(leg.from);
    const b = point(leg.to);
    const p = Math.min((t - leg.t0) / (leg.t1 - leg.t0), 1);
    if (leg.bounce) {
      // halfway towards a seat and straight back: aborted, try again
      const k = 0.45 * Math.sin(Math.PI * p);
      return { at: [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k], tone: "ink" };
    }
    const k = ease(p);
    const at = [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k];
    if (p < 1) return { at, tone: "ink" };
    if (leg.to.zone === "full") return { at, tone: "full" };
    return { at, tone: leg.to.level > 0 ? "critical" : "ink" };
  }

  // ------------------------------------------------------------------ painting

  const css = getComputedStyle(document.documentElement);
  const colour = (name) => css.getPropertyValue(name).trim();
  const tones = { ink: colour("--ink"), waiting: colour("--soft"), critical: colour("--critical"),
                  full: colour("--ink"), seat: colour("--surface"), label: colour("--muted") };

  function draw(p, t) {
    const { unit, zones } = box;
    ctx.clearRect(0, 0, canvas.clientWidth, box.height);

    // the zone names
    ctx.font = box.font;
    ctx.fillStyle = tones.label;
    const names = { door: `${p.run.bots} bots at the door`, seat: `${p.run.capacity} seats`, full: "Told FULL" };
    for (const zone of Object.keys(names)) ctx.fillText(names[zone], zones[zone].x, zones[zone].y - 12);

    // the empty seats
    ctx.fillStyle = tones.seat;
    for (let i = 0; i < p.run.capacity; i++) {
      const [x, y] = point(seat(i));
      ctx.fillRect(x - 0.43 * unit, y - 0.43 * unit, 0.86 * unit, 0.86 * unit);
    }

    // the bots: filled squares, or an outline once told FULL
    const size = 0.58 * unit;
    for (const student of p.students) {
      const { at, tone } = where(student, t);
      if (tone === "full") {
        ctx.strokeStyle = tones.full;
        ctx.lineWidth = 2;
        ctx.strokeRect(at[0] - size / 2 + 1, at[1] - size / 2 + 1, size - 2, size - 2);
      } else {
        ctx.fillStyle = tones[tone];
        ctx.fillRect(at[0] - size / 2, at[1] - size / 2, size, size);
      }
    }
  }

  // ------------------------------------------------------------------ playing

  let current = null;
  let shownAt = 0;           // the replay time on screen now
  let frame = 0;

  function show(t) {
    shownAt = t;
    draw(current, t);
    const c = counters(current, t);
    out.seats.textContent = c.seats;
    out.admitted.textContent = c.admitted;
    out.retries.textContent = c.retries.toLocaleString("en-US");
    out.clock.textContent = `${c.seconds.toFixed(2)} s`;
  }

  function choose() {
    const picked = document.querySelector('input[name="guard"]:checked');
    current = plan(picked ? picked.value : "none");
    const slower = current.end / current.run.seconds;
    out.speed.textContent = slower > 1.15 ? `Slowed down ${slower.toFixed(1)}× so you can follow it.`
                                          : "Played at the measured speed.";
    layout(current);
  }

  function play() {
    choose();
    cancelAnimationFrame(frame);
    if (still.matches) { show(current.end); return; }      // reduced motion: just the outcome
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min((now - start) / 1000, current.end);
      show(t);
      if (t < current.end) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
  }

  // The first frame: everyone at the door (or the end, with reduced motion).
  choose();
  show(still.matches ? current.end : 0);

  // Play once the picture is well in view, then again on every guard change or Replay.
  const watcher = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) { play(); watcher.disconnect(); }
  }, { threshold: 0.5 });
  watcher.observe(canvas);
  document.querySelectorAll('input[name="guard"]').forEach((radio) => radio.addEventListener("change", play));
  figure.querySelector("[data-replay]").addEventListener("click", play);

  // Redraw the same moment when the width changes, and once the web fonts arrive.
  // (Only the width: layout() sets the height itself, which would otherwise loop.)
  let width = canvas.clientWidth;
  new ResizeObserver(() => {
    if (canvas.clientWidth === width) return;
    width = canvas.clientWidth;
    layout(current);
    show(shownAt);
  }).observe(figure);
  document.fonts.ready.then(() => show(shownAt));
})();
