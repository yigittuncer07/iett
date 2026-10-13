const secs = hms => { const [h, m, s = 0] = hms.split(":").map(Number); return h * 3600 + m * 60 + s; };
const weekdayOf = date => new Date(date + "T12:00:00").getDay(); // 0 = Sunday

/* THE AVERAGING FUNCTION: plain averages of logged trips, nothing else.
   One row per departure in the current schedule (o.schedule). A trip counts toward a row when it ran the main
   route at that planned time, on that weekday, inside the date window, and (stop view) has times for both stops.
   o = { schedule, mainRoute, weekday, from, to, routeChanged, includeOld, nStops, a, b }
   a/b are the start/end stop indexes, or null for the full route. */
function timetableRows(trips, o) {
  const fullRoute = o.a == null;
  // route changes make old stop-level times meaningless, so only full-route times may include older data
  const useCutoff = !(fullRoute && o.includeOld) && o.routeChanged;
  const from = useCutoff && o.routeChanged > o.from ? o.routeChanged : o.from;
  const byPlanned = {};
  for (const t of trips) {
    if (t.route !== o.mainRoute || weekdayOf(t.date) !== o.weekday || t.date < from || t.date > o.to) continue;
    let value, clock;
    if (fullRoute) {
      value = (secs(t.end) - secs(t.start) + 86400) % 86400; // a trip can end after midnight
      clock = secs(t.start);
    } else {
      const s = t.stops;
      if (!s || s.length !== o.nStops || s[o.a] == null || s[o.b] == null) continue;
      value = s[o.b] - s[o.a];
      clock = secs(t.start) + s[o.a];
    }
    (byPlanned[t.planned] ??= []).push({ value, clock });
  }
  return o.schedule.map(planned => summarize(planned, byPlanned[planned] ?? []));
}

function summarize(planned, xs) {
  const n = xs.length;
  if (n === 0) return { planned, n };
  const mean = f => xs.reduce((sum, x) => sum + f(x), 0) / n;
  const avg = mean(x => x.value);
  const values = xs.map(x => x.value);
  return { planned, n, avg, sd: n > 1 ? Math.sqrt(mean(x => (x.value - avg) ** 2)) : null,
           min: Math.min(...values), max: Math.max(...values), clockAtStart: mean(x => x.clock) };
}

if (typeof module !== "undefined") module.exports = { timetableRows };
