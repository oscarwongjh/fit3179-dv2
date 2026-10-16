// Landing television. The page opens on a 1990s set with the title on its screen; as the
// reader scrolls, the camera moves into the screen until it fills the window, and a thin
// bezel then stays round the window for the rest of the story. The scroll position drives
// the zoom directly, so the reader controls its pace and can scroll back out.
//
// Readers who ask for reduced motion get the set without the zoom. Adding ?capture to the
// address does the same with a fixed-height landing, for full-page screenshots, which
// otherwise stretch anything sized to the window.
(function () {
  const hero = document.querySelector(".tv-hero");
  if (!hero) return;
  const stage = hero.querySelector(".tv-stage");
  const tv = hero.querySelector(".tv");
  const card = hero.querySelector(".tv-card");
  const frame = document.querySelector(".screen-frame");
  const root = document.documentElement;

  // The drawing's coordinates, from the viewBox in index.html.
  const VIEW = { w: 1000, h: 800 };
  const SCREEN = { x: 100, y: 170, w: 600, h: 480 };

  const capture = new URLSearchParams(location.search).has("capture");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const still = () => capture || reduceMotion.matches;
  root.classList.toggle("tv-capture", capture);

  let g = null;
  let queued = false;

  // Size the set to fit the window, and work out how far it must grow for its screen to
  // cover the window.
  function measure() {
    root.classList.toggle("tv-still", still());
    const W = stage.clientWidth, H = stage.clientHeight;
    const k = Math.min(0.82 * W / VIEW.w, 0.8 * H / VIEW.h);
    tv.style.width = VIEW.w * k + "px";
    tv.style.height = VIEW.h * k + "px";
    const centre = { x: (SCREEN.x + SCREEN.w / 2) * k, y: (SCREEN.y + SCREEN.h / 2) * k };
    const x0 = (W - VIEW.w * k) / 2, y0 = (H - VIEW.h * k) / 2 + 0.03 * H;
    g = {
      W, H, centre,
      start: { x: x0 + centre.x, y: y0 + centre.y },
      end: Math.max(W / (SCREEN.w * k), H / (SCREEN.h * k)) * 1.04
    };
    card.style.setProperty("--screen-w", SCREEN.w * k + "px");
    draw();
  }

  function progress() {
    if (still()) return 0;
    const travel = hero.offsetHeight - g.H;
    return Math.min(Math.max(-hero.getBoundingClientRect().top / travel, 0), 1);
  }

  function draw() {
    queued = false;
    const p = progress();
    const e = p * p * (3 - 2 * p);
    // Zoom by a constant ratio per step of scroll, so the move feels even, while the
    // screen's centre slides to the middle of the window.
    const s = Math.pow(g.end, e);
    const cx = g.start.x + (g.W / 2 - g.start.x) * e;
    const cy = g.start.y + (g.H / 2 - g.start.y) * e;
    tv.style.transform = `translate(${cx - s * g.centre.x}px, ${cy - s * g.centre.y}px) scale(${s})`;
    card.style.transform = `translate(${cx}px, ${cy}px) translate(-50%, -50%)`;
    hero.style.setProperty("--p", e.toFixed(3));
    // The button fades with the hint; once it is faint it stops taking clicks and focus.
    if (tune) tune.style.visibility = e > 0.2 ? "hidden" : "visible";
    // The bezel round the window takes over from the set's own as the zoom finishes.
    // Without the zoom it simply appears once the landing has scrolled away.
    const shown = still()
      ? (!capture && hero.getBoundingClientRect().bottom < g.H * 0.25 ? 1 : 0)
      : Math.min(Math.max((p - 0.82) / 0.18, 0), 1);
    frame.style.opacity = shown;
  }

  function queue() {
    if (!queued) {
      queued = true;
      requestAnimationFrame(draw);
    }
  }

  // "Tune in" plays the zoom for the reader, who can also just scroll: it moves through the
  // zoom at an even pace and stops where the story begins. Any wheel, touch or key input
  // hands control straight back. Without the zoom it simply jumps to the story.
  const tune = hero.querySelector(".tv-tune");
  let tuning = 0;
  const stopTuning = () => { tuning++; };
  function tuneIn() {
    const top = hero.getBoundingClientRect().top + scrollY;
    const target = top + hero.offsetHeight - g.H * 0.5;
    if (still()) {
      window.scrollTo(0, top + hero.offsetHeight);
      return;
    }
    const run = ++tuning, from = scrollY, start = performance.now(), duration = 1800;
    const ease = t => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    const step = now => {
      if (run !== tuning) return;
      const t = Math.min((now - start) / duration, 1);
      window.scrollTo(0, from + (target - from) * ease(t));
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  if (tune && !capture) {
    tune.hidden = false;
    tune.addEventListener("click", tuneIn);
    ["wheel", "touchstart", "keydown", "mousedown"].forEach(type =>
      window.addEventListener(type, e => { if (e.target !== tune) stopTuning(); }, { passive: true }));
  }

  measure();
  window.addEventListener("scroll", queue, { passive: true });
  window.addEventListener("resize", measure);
  reduceMotion.addEventListener("change", measure);
  document.fonts?.ready.then(measure);
})();
