/* Stop slider: picks a start and end stop on a route drawn as one snaking line.
   createSlider(root, onChange) -> { set({ names, a, b, locked, note }) }; onChange(a, b) fires on user changes only. */
function createSlider(root, onChange) {
  const SVG = "http://www.w3.org/2000/svg";
  const MIN_GAP = 36, ROW_H = 52, TOP = 22, HIT = 28, HANDLE = 36;
  const ICONS = {
    a: '<svg viewBox="0 0 36 36"><circle cx="18" cy="18" r="16" class="h-fill"/><circle cx="18" cy="12.5" r="3.6" class="h-glyph"/><path d="M11.5 25v-2.6a6.5 6.5 0 0 1 13 0V25z" class="h-glyph"/></svg>',
    b: '<svg viewBox="0 0 36 36"><circle cx="18" cy="18" r="15" class="h-fill h-ring"/><path d="M18 27.5s-7-6-7-11.5a7 7 0 0 1 14 0c0 5.5-7 11.5-7 11.5z" class="h-glyph"/><circle cx="18" cy="16" r="2.6" class="h-hole"/></svg>',
  };
  let names = [], a = 0, b = 0, locked = false, pts = [], size = { w: 0, h: 0 };

  root.classList.add("sl");
  root.innerHTML = `<div class="sl-head"><span class="sl-summary"></span><button type="button" class="sl-reset" hidden>Full route</button></div>
    <div class="sl-box"><svg class="sl-svg" aria-hidden="true"></svg><div class="sl-tip" hidden></div></div>
    <p class="sl-note" hidden></p>`;
  const $ = sel => root.querySelector(sel);
  const box = $(".sl-box"), svg = $(".sl-svg"), tip = $(".sl-tip");
  const handles = {};
  for (const [which, label] of [["a", "Start stop"], ["b", "End stop"]]) {
    const h = document.createElement("div");
    h.className = "sl-handle " + which; h.innerHTML = ICONS[which];
    h.tabIndex = 0; h.setAttribute("role", "slider"); h.setAttribute("aria-label", label);
    box.append(h);
    handles[which] = h;
  }

  const get = which => (which === "a" ? a : b);
  const el = (tag, attrs) => { const e = document.createElementNS(SVG, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };

  function layout() {
    const w = box.clientWidth, n = names.length;
    if (!w || n < 2) return false;
    let pad = 34, perRow = Math.floor((w - 2 * pad) / MIN_GAP) + 1;
    if (n <= perRow) { pad = 22; perRow = n; } // one straight row
    perRow = Math.max(2, perRow);
    const gap = (w - 2 * pad) / (perRow - 1), rows = Math.ceil(n / perRow);
    pts = names.map((_, i) => {
      const r = Math.floor(i / perRow), c = i % perRow;
      return { r, x: pad + (r % 2 ? perRow - 1 - c : c) * gap, y: TOP + r * ROW_H };
    });
    size = { w, h: 2 * TOP + (rows - 1) * ROW_H };
    svg.setAttribute("width", size.w); svg.setAttribute("height", size.h);
    svg.replaceChildren(el("path", { class: "sl-base" }), el("path", { class: "sl-sel" }),
      ...pts.map((p, i) => el("circle", { class: "sl-node", cx: p.x, cy: p.y, r: i === 0 || i === n - 1 ? 5 : 3.5 })));
    return true;
  }

  // SVG path through stops i0..i1; rows join with a semicircular U-turn
  function pathFor(i0, i1) {
    let d = `M${pts[i0].x} ${pts[i0].y}`;
    for (let i = i0; i < i1; i++) {
      const p = pts[i], q = pts[i + 1];
      d += p.r === q.r ? `L${q.x} ${q.y}` : `A${ROW_H / 2} ${ROW_H / 2} 0 0 ${p.r % 2 ? 0 : 1} ${q.x} ${q.y}`;
    }
    return d;
  }

  function update() {
    const n = names.length, full = a === 0 && b === n - 1;
    root.classList.toggle("locked", locked);
    $(".sl-summary").textContent = `${names[a]} → ${names[b]} · ${b - a + 1} stops`;
    $(".sl-reset").hidden = full || locked;
    const note = $(".sl-note");
    note.hidden = !note.textContent;
    if (!pts.length) return;
    svg.querySelector(".sl-base").setAttribute("d", pathFor(0, n - 1));
    svg.querySelector(".sl-sel").setAttribute("d", pathFor(a, b));
    svg.querySelectorAll(".sl-node").forEach((node, i) => node.classList.toggle("in", i >= a && i <= b));
    for (const which of ["a", "b"]) {
      const h = handles[which], i = get(which), p = pts[i];
      h.style.transform = `translate(${p.x - HANDLE / 2}px, ${p.y - HANDLE / 2}px)`;
      h.tabIndex = locked ? -1 : 0;
      h.setAttribute("aria-disabled", locked);
      h.setAttribute("aria-valuemin", 1); h.setAttribute("aria-valuemax", n);
      h.setAttribute("aria-valuenow", i + 1); h.setAttribute("aria-valuetext", names[i]);
    }
  }

  function nearest(clientX, clientY) {
    const r = svg.getBoundingClientRect(), x = clientX - r.left, y = clientY - r.top;
    let best = 0, bestD = Infinity;
    pts.forEach((p, i) => { const d = Math.hypot(p.x - x, p.y - y); if (d < bestD) { bestD = d; best = i; } });
    return { i: best, dist: bestD };
  }

  function move(which, i) { // keeps a < b
    const na = which === "a" ? Math.max(0, Math.min(i, b - 1)) : a;
    const nb = which === "b" ? Math.min(names.length - 1, Math.max(i, a + 1)) : b;
    if (na === a && nb === b) return;
    a = na; b = nb;
    update();
    onChange(a, b);
  }

  function showTip(i) {
    tip.textContent = `${i + 1}. ${names[i]}`;
    tip.hidden = false;
    const half = tip.offsetWidth / 2, x = Math.max(half + 4, Math.min(size.w - half - 4, pts[i].x));
    tip.style.left = x + "px";
    tip.style.top = pts[i].y - 26 + "px";
  }

  // tap a stop: before start -> new start, after end -> new end, between -> nearer handle (tie: start)
  svg.addEventListener("click", e => {
    if (locked) return;
    const { i, dist } = nearest(e.clientX, e.clientY);
    if (dist > HIT || i === a || i === b) return;
    if (i < a) move("a", i);
    else if (i > b) move("b", i);
    else move(i - a <= b - i ? "a" : "b", i);
  });
  svg.addEventListener("pointermove", e => {
    if (e.pointerType !== "mouse") return;
    const { i, dist } = nearest(e.clientX, e.clientY);
    if (dist <= HIT) showTip(i); else tip.hidden = true;
  });
  svg.addEventListener("pointerleave", () => { tip.hidden = true; });

  let dragging = null;
  for (const which of ["a", "b"]) {
    const h = handles[which];
    h.addEventListener("pointerdown", e => {
      if (locked) return;
      dragging = which; h.setPointerCapture(e.pointerId); h.classList.add("drag");
    });
    h.addEventListener("pointermove", e => {
      if (dragging !== which) return;
      move(which, nearest(e.clientX, e.clientY).i);
      showTip(get(which));
    });
    const stop = () => { dragging = null; h.classList.remove("drag"); tip.hidden = true; };
    h.addEventListener("pointerup", stop);
    h.addEventListener("pointercancel", stop);
    h.addEventListener("focus", () => { if (!locked) showTip(get(which)); });
    h.addEventListener("blur", () => { tip.hidden = true; });
    h.addEventListener("keydown", e => {
      const step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
      if (locked || (step === undefined && e.key !== "Home" && e.key !== "End")) return;
      e.preventDefault();
      const last = names.length - 1;
      if (step !== undefined) move(which, get(which) + step);
      else if (e.key === "Home") move(which, 0);
      else move(which, last);
      showTip(get(which));
    });
  }
  $(".sl-reset").addEventListener("click", () => { a = 0; b = names.length - 1; update(); onChange(a, b); });

  new ResizeObserver(() => { if (layout()) update(); }).observe(box);

  return {
    set(next) {
      const changedStops = next.names.length !== names.length || next.names.some((x, i) => x !== names[i]);
      names = next.names; locked = !!next.locked;
      a = locked ? 0 : next.a; b = locked ? names.length - 1 : next.b;
      $(".sl-note").textContent = next.note || "";
      if (changedStops || !pts.length) layout();
      if (names.length >= 2) update();
    },
  };
}
