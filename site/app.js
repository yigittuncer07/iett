const $ = id => document.getElementById(id);
const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const safe = code => code.replace(/[^A-Za-z0-9_-]/g, "_");
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const clock = s => { s = ((Math.round(s) % 86400) + 86400) % 86400; return `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor(s % 3600 / 60)).padStart(2, "0")}`; };
const minutes = s => Math.round(s / 60);


// Istanbul "today" as YYYY-MM-DD
const dateStr = d => d.toISOString().slice(0, 10);
const todayParts = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Istanbul" }).format(new Date()).split("-").map(Number);
const todayUTC = new Date(Date.UTC(todayParts[0], todayParts[1] - 1, todayParts[2]));
const YESTERDAY = dateStr(new Date(todayUTC - 86400000));
const windowStart = months => dateStr(new Date(Date.UTC(todayParts[0], todayParts[1] - 1 - months, todayParts[2])));

let lines = [], meta = null, trips = [], loadToken = 0;
const state = { dir: null, weekday: todayUTC.getUTCDay(), months: 1, a: 0, b: 0, includeOld: false };
const monthCache = new Map();

try { state.includeOld = localStorage.getItem("includeOld") === "1"; } catch (e) {}

const dirInfo = () => meta.directions[state.dir];
const nStops = () => dirInfo().stops.length;
const dayType = weekday => (weekday === 0 ? "P" : weekday === 6 ? "C" : "I");
const prettyDate = d => new Date(d + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
const hasStopData = () => trips.some(t => t.route === dirInfo().main_route && t.stops && t.stops.length === nStops());

function dirLabel(d) {
  const s = meta.directions[d].stops;
  return "→ " + (s.length ? s[s.length - 1][1] : d);
}

function chip(text, pressed, onclick) {
  const b = document.createElement("button");
  b.className = "chip"; b.textContent = text; b.setAttribute("aria-pressed", pressed); b.onclick = onclick;
  return b;
}

/* ---------- data loading ---------- */

async function loadMonth(code, month) {
  const key = code + "/" + month;
  if (!monthCache.has(key)) {
    monthCache.set(key, fetch(`data/lines/${safe(code)}/${month}.json`).then(r => r.json()).then(j => j.trips));
  }
  return monthCache.get(key);
}

async function loadTrips() {
  const token = ++loadToken;
  const from = windowStart(state.months).slice(0, 7);
  const wanted = meta.months.filter(m => m >= from);
  const loaded = (await Promise.all(wanted.map(m => loadMonth(meta.code, m)))).flat();
  if (token !== loadToken) return false; // a newer request superseded this one
  trips = loaded;
  return true;
}

async function openLine(code) {
  $("results").hidden = true;
  history.replaceState(null, "", "#" + encodeURIComponent(code));
  meta = await (await fetch(`data/lines/${safe(code)}/meta.json`)).json();
  state.dir = Object.keys(meta.directions).sort()[0];
  state.months = 1;
  resetStops();
  $("lineTitle").textContent = `${meta.code} · ${meta.name}`;
  $("line").hidden = false;
  await refresh();
}

function resetStops() { state.a = 0; state.b = Math.max(0, nStops() - 1); }

async function refresh() {
  if (await loadTrips()) render();
}

/* ---------- controls ---------- */

function renderControls() {
  $("dirs").replaceChildren(...Object.keys(meta.directions).sort().map(d =>
    chip(dirLabel(d), state.dir === d, () => { state.dir = d; resetStops(); refresh(); })));
  $("days").replaceChildren(...[1, 2, 3, 4, 5, 6, 0].map(w =>
    chip(DAY_NAMES[w], state.weekday === w, () => { state.weekday = w; renderControls(); renderTable(); })));

  const oldest = meta.months[0] || YESTERDAY.slice(0, 7);
  const [oy, om] = oldest.split("-").map(Number);
  const available = Math.min(12, Math.max(1, (todayParts[0] - oy) * 12 + todayParts[1] - om + 1));
  $("windowSelect").replaceChildren(...Array.from({ length: available }, (_, i) =>
    new Option(`last ${i + 1} month${i ? "s" : ""}`, i + 1)));
  $("windowSelect").value = Math.min(state.months, available);
}

/* ---------- stop slider ---------- */

const slider = createSlider($("slider"), (a, b) => { state.a = a; state.b = b; renderTable(); });

function renderSlider() {
  const stops = dirInfo().stops, locked = !hasStopData();
  $("slider").hidden = stops.length < 2;
  if (locked) resetStops();
  slider.set({ names: stops.map(s => s[1]), a: state.a, b: state.b, locked,
               note: locked ? "No stop-level data yet for this selection; showing the full route." : "" });
}

/* ---------- timetable ---------- */

function renderTable() {
  const info = dirInfo(), n = nStops();
  const stopView = hasStopData() && n >= 2 && !(state.a === 0 && state.b === n - 1);
  const from = windowStart(state.months);
  const rows = timetableRows(trips, {
    schedule: info.schedule[dayType(state.weekday)] || [], mainRoute: info.main_route, weekday: state.weekday,
    from, to: YESTERDAY, routeChanged: meta.route_changed, includeOld: state.includeOld,
    nStops: n, a: stopView ? state.a : null, b: stopView ? state.b : null,
  });

  const notes = [];
  if (meta.route_changed && meta.route_changed >= from) {
    const when = prettyDate(meta.route_changed);
    notes.push(state.includeOld && !stopView ? `Includes data from before the route change on ${when}.`
      : `Route changed on ${when}; using data since then.`);
  }
  $("note").hidden = !notes.length;
  $("note").textContent = notes.join(" ");

  const head = stopView ? ["Departs", "At start stop", "Duration", "Min – Max", "n"]
                        : ["Departs", "Duration", "Arrives", "Min – Max", "n"];
  const sd = r => (r.sd == null ? "–" : minutes(r.sd));
  const cells = r => stopView
    ? [r.planned, clock(r.clockAtStart), `${minutes(r.avg)} min ± ${sd(r)}`, `${minutes(r.min)} – ${minutes(r.max)}`, r.n]
    : [r.planned, `${minutes(r.avg)} min ± ${sd(r)}`, clock(secs(r.planned) + r.avg), `${minutes(r.min)} – ${minutes(r.max)}`, r.n];
  const body = rows.map(r => r.n === 0
    ? `<tr><td>${esc(r.planned)}</td><td colspan="4" class="dim" style="text-align:right">no data yet</td></tr>`
    : "<tr>" + cells(r).map((c, i) => `<td${i === 4 ? ' class="dim"' : ""}>${esc(c)}</td>`).join("") + "</tr>");
  $("table").innerHTML = "<thead><tr>" + head.map(h => `<th>${h}</th>`).join("") + "</tr></thead><tbody>" +
    (body.join("") || '<tr><td colspan="5" class="dim" style="text-align:center">No scheduled departures for this day.</td></tr>') + "</tbody>";
}

function render() {
  renderControls();
  renderSlider();
  renderTable();
}

/* ---------- search and settings ---------- */

$("windowSelect").onchange = e => { state.months = +e.target.value; refresh(); };
$("gear").onclick = () => {
  $("settings").hidden = !$("settings").hidden;
  $("gear").setAttribute("aria-expanded", !$("settings").hidden);
};
$("includeOld").checked = state.includeOld;
$("includeOld").onchange = e => {
  state.includeOld = e.target.checked;
  try { localStorage.setItem("includeOld", state.includeOld ? "1" : "0"); } catch (err) {}
  if (meta) renderTable();
};

$("search").addEventListener("input", e => {
  const q = e.target.value.trim().toLocaleLowerCase("tr");
  const hits = q ? lines.filter(l => l.code.toLocaleLowerCase("tr").startsWith(q) || l.name.toLocaleLowerCase("tr").includes(q)).slice(0, 8) : [];
  $("results").replaceChildren(...hits.map(l => {
    const li = document.createElement("li");
    li.innerHTML = `<b>${esc(l.code)}</b>${esc(l.name)}`;
    li.onclick = () => { $("search").value = l.code; openLine(l.code); };
    return li;
  }));
  $("results").hidden = !hits.length;
});

fetch("data/lines.json").then(r => r.json()).then(l => { lines = l; });

if (location.hash.length > 1) openLine(decodeURIComponent(location.hash.slice(1))); // deep link: #500T
