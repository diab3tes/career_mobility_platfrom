/* Hover tilt + cursor spotlight for any element with class "tilt".
   Uses event delegation, so it also works for cards React renders later.
   Mouse only; off when the user prefers reduced motion. Optional data-tilt="2" sets max degrees. */
(function () {
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var DEFAULT_MAX = 5;
  var active = null;
  var frame = 0;
  var last = null;

  function reset(el) {
    el.classList.remove("is-tilting");
    el.style.removeProperty("--rx");
    el.style.removeProperty("--ry");
  }

  function apply() {
    frame = 0;
    if (!last) return;
    var el = last.el, e = last.e;
    var r = el.getBoundingClientRect();
    var px = Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1);
    var py = Math.min(Math.max((e.clientY - r.top) / r.height, 0), 1);
    var max = parseFloat(el.dataset.tilt) || DEFAULT_MAX;
    el.style.setProperty("--ry", ((px - 0.5) * 2 * max).toFixed(2) + "deg");
    el.style.setProperty("--rx", ((0.5 - py) * 2 * max).toFixed(2) + "deg");
    el.style.setProperty("--mx", (px * 100).toFixed(1) + "%");
    el.style.setProperty("--my", (py * 100).toFixed(1) + "%");
    el.classList.add("is-tilting");
  }

  document.addEventListener("pointermove", function (e) {
    if (e.pointerType !== "mouse" || reduce.matches) return;
    var el = e.target.closest ? e.target.closest(".tilt") : null;
    if (active && active !== el) reset(active);
    active = el;
    if (!el) return;
    last = { el: el, e: e };
    if (!frame) frame = requestAnimationFrame(apply);
  }, { passive: true });

  document.documentElement.addEventListener("mouseleave", function () { if (active) { reset(active); active = null; } });
  window.addEventListener("blur", function () { if (active) { reset(active); active = null; } });
})();
