// Small enhancements. Every page works without JavaScript: elements are only
// hidden for their entrance when <html> has the "js" class, which base.html sets.

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
