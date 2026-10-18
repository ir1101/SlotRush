// Small enhancements. Every page works without JavaScript: elements are only
// hidden for their entrance when <html> has the "js" class, which base.html sets.

const still = matchMedia("(prefers-reduced-motion: reduce)");

// Section entrances: each [data-reveal] rises into place once, when it scrolls in.
const reveal = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (entry.isIntersecting) {
      entry.target.classList.add("is-in");
      reveal.unobserve(entry.target);        // once only, never replayed
    }
  }
}, { threshold: 0 });   // any visible pixel counts, so nothing can stay hidden in a tall window
document.querySelectorAll("[data-reveal]").forEach((el) => reveal.observe(el));

// Charts, the receipt and counted totals start a little later: once their top is
// above the bottom fifth of the window, so the drawing is seen rather than missed.
const play = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (entry.isIntersecting) {
      entry.target.classList.add("is-in");
      if (entry.target.dataset.count) countUp(entry.target);
      play.unobserve(entry.target);
    }
  }
}, { rootMargin: "0px 0px -20% 0px" });
document.querySelectorAll("[data-chart], [data-count]").forEach((el) => play.observe(el));

// A total counts up from 0 to its value. The page already shows the real value,
// so without JavaScript (or with reduced motion) nothing changes. With motion it
// waits at 0 until it scrolls into view.
if (!still.matches) {
  document.querySelectorAll("[data-count]").forEach((el) => { el.textContent = "0"; });
}
function countUp(el) {
  const target = Number(el.dataset.count);
  if (!target || still.matches) return;
  const start = performance.now();
  const duration = 1400;
  const step = (now) => {
    const p = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - p, 3);     // ease-out: quick at first, settling at the end
    el.textContent = Math.round(target * eased).toLocaleString("en-US");
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// Loading state: once a form is submitted, mark its button busy and disable it,
// so a double click cannot send the same register() call twice.
document.addEventListener("submit", (event) => {
  const button = event.submitter;
  if (!button) return;
  // Wait one tick so the button's own name=value still goes with the form.
  setTimeout(() => {
    button.setAttribute("aria-busy", "true");
    button.disabled = true;
  }, 0);
});
