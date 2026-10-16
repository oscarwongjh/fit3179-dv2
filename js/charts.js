// Colours and the typeface live in css/style.css. Each spec declares the colours it
// uses as Vega-Lite params or Vega signals, with light-mode defaults so the JSON still
// renders on its own in the Vega editor. Before embedding, those defaults are swapped
// for the live values, so light and dark mode are handled by the stylesheet alone.
const CHARTS = [
  ["#choropleth-eps", "specs/choropleth-eps.vl.json"],
  ["#dorling-eps-change", "specs/dorling-eps-change.vg.json"],
  ["#lines-panels", "specs/lines-panels.vl.json"],
  ["#heatmap-season-bands", "specs/heatmap-season-bands.vl.json"],
  ["#ridgeline-us-uk", "specs/ridgeline-us-uk.vl.json"],
  ["#boxplot-convergence", "specs/boxplot-convergence.vl.json"],
  ["#radial-premiere-month", "specs/radial-premiere-month.vl.json"],
  ["#waffle-renewal", "specs/waffle-renewal.vl.json"],
  ["#flowmap-malaysia", "specs/flowmap-malaysia.vl.json"],
  ["#bump-malaysia", "specs/bump-malaysia.vl.json"],
  ["#beeswarm-malaysia", "specs/beeswarm-malaysia.vg.json"]
];

const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// A param or signal named "inkMuted" takes the value of --viz-ink-muted, if it exists.
function applyTokens(spec) {
  [...(spec.params || []), ...(spec.signals || [])].forEach(p => {
    const v = css("--viz-" + p.name.replace(/[A-Z]/g, c => "-" + c.toLowerCase()));
    if (v) p.value = v;
  });
  return spec;
}

function theme() {
  const font = css("--font-sans"), ink = css("--ink"), muted = css("--ink-muted"),
        rule = css("--rule");
  return {
    background: null,
    font,
    view: { stroke: null },
    title: { font, subtitleFont: font, color: ink, subtitleColor: muted,
             fontWeight: 700, subtitleFontWeight: 400 },
    text: { font },
    legend: { labelFont: font, titleFont: font, labelColor: muted, titleColor: ink,
              titleFontWeight: 600 },
    header: { labelFont: font, titleFont: font, labelColor: ink, titleColor: ink },
    axis: { labelFont: font, titleFont: font, labelColor: muted, titleColor: ink,
            domainColor: rule, gridColor: rule, tickColor: rule }
  };
}

// Play controls. Every chart opens on its complete, static view, which carries the
// explanation. Four charts can also replay their change over time, but only when the
// reader asks: nothing animates by itself. Each has a Play button and a timeline, which
// fills as the chart plays and can be dragged, or stepped with the arrow keys, to any
// point. Play carries on from wherever the timeline is, a run ends back on the static
// view, and pressing the button mid-run stops it.
//
// Every move is continuous: positions are fractional, and the charts interpolate between
// them, so lines draw on, the box plot wipes in and flow widths glide from year to year.
// Each player runs from 0 to `end`, at `speed` milliseconds per unit, easing through
// `stops`, where it can pause for `hold` milliseconds so a year can be read. For readers
// who ask for reduced motion there is no sliding: the chart jumps between the stops.
const linear = t => t;
const easeOut = t => 1 - Math.pow(1 - t, 3);
const easeInOut = t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const PLAYERS = {
  "#dorling-eps-change": {
    signal: "progress", end: 1, speed: 1600, ease: easeOut, stops: [1], hold: 0, key: 0.1,
    value: t => t, ticks: [[0, "Before 2005"], [1, "2015 onward"]], readout: () => null
  },
  "#lines-panels": {
    signal: "cut", end: 34, speed: 150, ease: linear, stops: [34], hold: 0, key: 1,
    value: t => 1991 + t, ticks: [[0, "1991"], [9, "2000"], [19, "2010"], [29, "2020"], [34, "2025"]],
    readout: t => String(Math.floor(1991 + t)), still: [9, 19, 29, 34]
  },
  "#boxplot-convergence": {
    signal: "reveal", end: 6, speed: 850, ease: linear, stops: [6], hold: 0, key: 1,
    value: t => t, ticks: [1995, 2000, 2005, 2010, 2015, 2020].map((y, i) => [i + 0.5, String(y)]),
    readout: t => String(1995 + 5 * Math.min(5, Math.floor(t))), still: [1, 2, 3, 4, 5, 6]
  },
  "#flowmap-malaysia": {
    signal: "yearPos", end: 6, speed: 650, ease: easeInOut, stops: [0, 1, 2, 3, 4, 5, 6], hold: 900, key: 1,
    value: t => t, ticks: [...[2021, 2022, 2023, 2024, 2025, 2026].map((y, i) => [i, String(y)]), [6, "All years"]],
    readout: t => (t > 5.5 ? "All years" : String(2021 + Math.round(t)))
  }
};
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const views = {};
const runs = {};

const player = el => document.querySelector(`.player[data-play="${el}"]`);
const slider = el => player(el).querySelector("input");

// The timeline is a range input, so it works with a mouse, touch and the keyboard.
function buildTimeline(el) {
  const p = PLAYERS[el], box = player(el);
  const wrap = document.createElement("div");
  wrap.className = "timeline";
  const input = document.createElement("input");
  Object.assign(input, { type: "range", min: 0, max: p.end, step: "any", value: p.end });
  input.setAttribute("aria-label", "Timeline for this chart");
  input.style.setProperty("--fill", "100%");
  const ticks = document.createElement("div");
  ticks.className = "ticks";
  ticks.setAttribute("aria-hidden", "true");
  p.ticks.forEach(([at, text]) => {
    const t = document.createElement("span");
    t.textContent = text;
    t.style.left = `${(100 * at) / p.end}%`;
    if (at === 0) t.className = "at-start";
    if (at === p.end) t.className = "at-end";
    ticks.append(t);
  });
  wrap.append(input, ticks);
  box.append(wrap);
  const takeOver = () => { runs[el] = (runs[el] || 0) + 1; showState(el, false); };
  input.addEventListener("input", () => { takeOver(); show(el, +input.value); });
  // Arrow keys move one year or period at a time rather than a sliver of the track.
  input.addEventListener("keydown", e => {
    const dir = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
    if (!dir) return;
    e.preventDefault();
    takeOver();
    const units = +input.value / p.key;
    const next = dir > 0 ? Math.floor(units + 1e-6) + 1 : Math.ceil(units - 1e-6) - 1;
    show(el, Math.min(p.end, Math.max(0, next * p.key)));
  });
  box.querySelector("button").addEventListener("click", () =>
    box.querySelector("button").getAttribute("aria-pressed") === "true" ? stop(el) : play(el));
}

// Draw position t in the chart and on the timeline.
function show(el, t) {
  const p = PLAYERS[el], input = slider(el);
  input.value = t;
  input.style.setProperty("--fill", `${(100 * t) / p.end}%`);
  input.setAttribute("aria-valuetext", p.readout(t) ?? (t >= p.end ? "2015 onward" : t <= 0 ? "Before 2005" : `${Math.round(100 * t)}% of the way`));
  views[el]?.signal(p.signal, p.value(t)).runAsync();
}

function showState(el, playing, step) {
  const b = player(el).querySelector("button");
  b.dataset.label ??= b.textContent;
  const text = !playing ? b.dataset.label : step ? `Stop · ${step}` : "Stop";
  b.setAttribute("aria-pressed", playing);
  if (b.textContent !== text) b.textContent = text;
}

function stop(el) {
  runs[el] = (runs[el] || 0) + 1;
  show(el, PLAYERS[el].end);
  showState(el, false);
}

function play(el) {
  const p = PLAYERS[el], view = views[el];
  if (!view) return;
  const run = runs[el] = (runs[el] || 0) + 1;
  const live = () => runs[el] === run && views[el] === view;
  const here = +slider(el).value;
  const from = here < p.end - 1e-6 ? here : 0;
  const still = reduceMotion.matches;
  const stops = (still ? p.still || p.stops : p.stops).filter(s => s > from + 1e-6);
  showState(el, true, p.readout(from));
  show(el, from);

  // Each leg runs from the current position to the next stop, then holds there.
  let leg = 0, a = from;
  const nextLeg = () => {
    if (!live()) return;
    if (leg === stops.length) return showState(el, false);
    const b = stops[leg++];
    if (still) {
      show(el, b);
      showState(el, true, p.readout(b));
      a = b;
      return setTimeout(nextLeg, Math.max(p.hold, 1000));
    }
    const start = performance.now(), length = p.speed * (b - a), from = a;
    const frame = now => {
      if (!live()) return;
      const u = Math.min((now - start) / length, 1);
      const t = from + (b - from) * p.ease(u);
      show(el, t);
      showState(el, true, p.readout(t));
      if (u < 1) return requestAnimationFrame(frame);
      a = b;
      setTimeout(nextLeg, leg === stops.length ? 250 : p.hold);
    };
    requestAnimationFrame(frame);
  };
  // Starting on a stop, such as the flow map's first year, holds there first.
  setTimeout(nextLeg, still ? 600 : p.stops.includes(from) ? p.hold : 0);
}

Object.keys(PLAYERS).forEach(el => { if (player(el)) buildTimeline(el); });

function render() {
  // A theme change re-draws every chart, so any run in progress ends first.
  Object.keys(PLAYERS).forEach(el => { if (el in views) stop(el); });
  CHARTS.forEach(([el, url]) =>
    fetch(url).then(r => r.json())
      .then(spec => vegaEmbed(el, applyTokens(spec), { actions: false, renderer: "svg", config: theme() }))
      .then(result => {
        views[el] = result.view;
        if (player(el)) player(el).hidden = false;
      })
      .catch(e => console.error(url, e)));
}

// Vega measures label widths when it lays out a chart, so wait for the web font or
// legends and annotations get spaced for the fallback face.
Promise.all(["400", "600", "700"].map(w => document.fonts.load(`${w} 12px "Radio Canada"`)))
  .catch(() => {})
  .then(render);
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
