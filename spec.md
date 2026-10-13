# Istanbul Bus Times — Build Spec

A static website that shows, for any IETT bus line, how long each scheduled departure **actually** took, averaged over real logged trips from the last 12 months (selectable). Optionally filtered to a start and end stop.

The numbers are plain averages of logged data. No estimation, prediction, interpolation or modelling anywhere.

---

## 0. Rules for the coding agent (read first)

**Logic code (`iett.py`, `collect.py`, `ingest.py`, `publish.py`) will be reviewed by a human with little time.**

- Keep it as simple as possible. Fewer lines and fewer features beat cleverness.
- Python 3, **standard library only**. No pip dependencies.
- Budget: about **450 lines total** across the four files, **no file over ~200 lines**.
- Plain functions. No classes unless clearly simpler. No config files: constants at the top of each file.
- `print()` for logs. No logging framework, no retry/backoff machinery. If something fails, print one line and move on; the next run picks it up.
- No test suite, CLI framework, database, Docker or abstraction layers.
- Build only what this spec asks for. Anything in §9 is out of scope.
- Readable names, short functions, a one-line comment where intent isn't obvious.

**Frontend (`site/`)** is the exception: it won't be reviewed, so any approach is fine, with these constraints (the page must also work under the CSP in §8):

- The output must be plain static files in `site/` (an optional build step is OK, but its output goes to `site/` and must never touch `site/data/`).
- The page only loads JSON from `site/data/`. No backend, no API calls, no external CDNs.
- **One exception to "anything goes":** the function that computes averages (§6) must be a single small, clearly named, readable function, because it is the core of the product.

---

## 1. Verified API facts (tested 2026-10-13)

All endpoints are SOAP, need **no auth**, and live under `https://api.ibb.gov.tr/iett/`.

Request format (POST):

```
Content-Type: text/xml; charset=utf-8
SOAPAction: "http://tempuri.org/{METHOD}"

<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <{METHOD} xmlns="http://tempuri.org/">{PARAMS}</{METHOD}>
  </soap:Body>
</soap:Envelope>
```

- `*_json` methods return a **JSON string** inside `<{METHOD}Result>`. Parse the envelope with `xml.etree.ElementTree`, then `json.loads` the element's text.
- `*_GYY` methods return XML: `<NewDataSet><Table>…</Table>…</NewDataSet>` inside the result element.
- Timestamps formatted `/Date(1791781529000)/` are UTC epoch milliseconds.
- Istanbul is UTC+3 all year. Use `zoneinfo.ZoneInfo("Europe/Istanbul")`.

### 1.1 Fleet positions (live): `FiloDurum/SeferGerceklesme.asmx` → `GetFiloAracKonum_json`

- No params. Returns **all ~6,900 buses** in one call (~1.1 MB).
- Fields: `Operator, Garaj, KapiNo, Saat, Boylam, Enlem, Hiz, Plaka`.
  - `KapiNo` = door number, the bus ID. It matches `SKAPINUMARA` in the archive.
  - `Saat` = local time of the position, `"HH:MM:SS"`, **no date**.
  - `Enlem` = latitude, `Boylam` = longitude (strings).
- The server refreshes this snapshot **once per minute**. Polling faster returns identical data.
- Parked buses keep stale `Saat` values (sometimes hours old).
- IETT docs state a limit of 100 requests/hour on this service. One call per minute stays under it.

### 1.2 Trip archive (history): `ibb/ibb360.asmx` → `GetIettArsivGorev_json`

- Param: `<Tarih>YYYYMMDD</Tarih>`.
- Returns every one-way trip of every line that day (~55,000 rows, ~20 MB).
- Data exists from roughly **January 2021**. **Today returns `[]`**; past days are complete.
- Fields used:
  - `SHATKODU` — line code, e.g. `500T`
  - `SGUZERGAHKODU` — route code `LINE_DIR_VARIANT`, e.g. `500T_G_D0`. Parse with `rsplit("_", 2)`. `DIR` is `G` or `D` and matches `YON` in the stop list.
  - `SKAPINUMARA` — door number
  - `DTBASLAMAZAMANI` / `DTBITISZAMANI` — actual start/end (`/Date(ms)/`, end may be null)
  - `DTPLANLANANBASLANGICZAMANI` — planned start
  - `SGOREVDURUM` — status. **Use only `T`** (completed). Other values seen: `I, YK, B, A`.
- About 7% of `T` rows have no end time. Skip them.

### 1.3 Stop lists: `ibb/ibb.asmx` → `DurakDetay_GYY`

- Param: `<hat_kodu></hat_kodu>` (**empty returns all lines**, ~82k rows, ~28 MB, one call).
- Fields: `HATKODU, YON, SIRANO, DURAKKODU, DURAKADI, XKOORDINATI (lon), YKOORDINATI (lat)`, …
- `YON` = `G`/`D`; `SIRANO` = stop order (1 = first stop).

### 1.4 Line names: `ibb/ibb.asmx` → `HatServisi_GYY`

- Param: `<hat_kodu></hat_kodu>` (empty returns all ~780 lines).
- Fields: `HAT_KODU, HAT_ADI` (e.g. `TUZLA ŞİFA MAHALLESİ - 4. LEVENT METRO`), …

### 1.5 Excluded lines (metrobüs, unaffected by traffic)

`34, 34A, 34AS, 34B, 34BZ, 34C, 34G, 34Z`. Hardcode as a constant.

### 1.6 Schedule: `UlasimAnaVeri/PlanlananSeferSaati.asmx` → `GetPlanlananSeferSaati_json`

- Param `<HatKodu>500T</HatKodu>`. **One line per call**; an empty line code returns an error.
- Rows: `SHATKODU`, `SGUZERAH` (route code; the API's own spelling), `SYON` (`G`/`D`), `SGUNTIPI` (`I` weekday, `C` Saturday, `P` Sunday), `DT` (`"05:50"`).
- Archive planned times match schedule times exactly, so plain `"HH:MM"` string equality works.

---

## 2. Repository layout

```
iett.py      # call(service, method, params="") and fetch_stops()
collect.py   # long-running: fleet snapshot every 60s -> data/pings/
ingest.py    # one pass: archive -> data/trips/, matched days -> data/days/
publish.py   # writes site/data/ (every 6 hours)
.tmuxinator.yml
deploy/nginx.conf
data/
  pings/YYYY-MM-DD.csv(.gz)   # raw positions, kept forever
  trips/YYYY-MM-DD.csv        # filtered archive, kept forever
  days/YYYY-MM-DD.json        # {line: [trip, ...]} with stop times
  changes.json                # route-change fingerprints (§5)
site/
  index.html app.js slider.js timetable.js style.css
  data/                       # generated by publish.py only
README.md
```

## 3. `iett.py`

`call(service, method, params="")`: builds the SOAP envelope (§1), POSTs with `urllib.request` (timeout ~120s). `_json` methods return parsed JSON; `_GYY` methods a list of dicts, one per `<Table>`. Raises on HTTP error or SOAP fault. `fetch_stops()` returns `{(line, dir): [(code, name, lat, lon), ...]}` in stop order from `DurakDetay_GYY`.

## 4. `collect.py`

Runs forever (tmuxinator restarts it if it exits). Loop:

1. Call `GetFiloAracKonum_json`.
2. Convert each row's `Saat` to a full local datetime: today's date (Istanbul), or yesterday if that lands in the future.
3. Skip positions older than 5 minutes (parked/stale buses).
4. Skip rows whose `(KapiNo, Saat)` equals the last one seen for that bus.
5. Append the rest to `data/pings/{date of the position}.csv`, columns `door,time,lat,lon` (local `YYYY-MM-DDTHH:MM:SS`).
6. Sleep 60 seconds. On any exception: print one line, sleep, continue.

Start it as early as possible: stop-level data only exists from the day collection starts.

## 5. `ingest.py`

`python3 ingest.py [days_back]` (default 365). One pass, then exits. Fetch all stop lists once. Then for dates from yesterday back `days_back` days, **newest first**:

- If `data/trips/{date}.csv` is missing, fetch the archive; if empty skip the date (a later pass retries); otherwise save it filtered (status `T`, has planned/start/end, not metrobüs), columns `line,route,door,planned,start,end` (local times). Sleep 5 s between archive fetches.
- If `data/days/{date}.json` is missing, process the day: all trips of all lines and routes. If a pings file (`.csv` or `.csv.gz`) exists for the date, match stops; otherwise omit `stops`. Write `{line: [trip, ...]}` via `.tmp` + `os.replace()`. Trip: `{"date", "dir", "route", "planned": "HH:MM", "start": "HH:MM:SS", "end": "HH:MM:SS", "stops": [...]}`.

### Stop matching

For each trip, take that door's pings with `start <= time <= end`, sorted. Walk the stop list for the trip's line and direction in order with a pointer into the pings: for each stop, from the pointer find the first ping within `MATCH_RADIUS_M = 300` (haversine); while the following pings get closer, move forward; record that ping's time and set the pointer to it. If none is within the radius, record `null` and leave the pointer. Each entry is **seconds since the trip's actual start** or `null`. Raw ping times only, no interpolation: accurate to about ±1 minute (pings arrive once a minute). A bus that sits still produces matches at the first ping it ever made near a stop; that is a property of the data.

## 6. `publish.py`

Runs every 6 hours. Fetch line names, all stop lists, and each published line's schedule (§1.6, 0.5 s between calls). Detect route changes (§7). Write `site/data/lines.json` (`[{"code", "name"}]`, lines with data and a `meta.json`) and each line's `meta.json`. Rewrite month files only for months containing a `data/days/` file modified after the last publish (mtime of `lines.json`, set to the publish start time; no `lines.json` = rewrite all). Every file is written `.tmp` then `os.replace()`; only inside `site/data/`; no symlinks. A failed or empty schedule fetch leaves the previous `meta.json` untouched.

`site/data/lines/{code}/meta.json` (codes made filename-safe: anything outside `A-Za-z0-9_-` becomes `_`):

```json
{"code": "500T", "name": "TUZLA ŞİFA MAHALLESİ - 4. LEVENT METRO", "route_changed": "2026-11-02",
 "directions": {"G": {"main_route": "500T_G_D0", "stops": [["code", "name"], ...],
                      "schedule": {"I": ["05:50", ...], "C": [...], "P": [...]}}, "D": {...}},
 "months": ["2026-09", "2026-10"]}
```

`main_route` is the most common route code for that direction in the current schedule; `schedule` its departure times per day type; `route_changed` the last detected route change or `null`; `months` the months that have a month file.

`site/data/lines/{code}/{YYYY-MM}.json`: `{"trips": [...]}`, the line's trips for that month, only dates within the last 365 days (older month files are deleted).

## 7. Route change detection (in `publish.py`)

Stops added, removed or reordered change durations, so older data is excluded by default. (Schedule changes need nothing: timetable rows come from the current schedule.)

- Fingerprint per line = SHA-1 of each direction's ordered stop **codes**.
- `data/changes.json` = `{line: {"hash", "since": "YYYY-MM-DD" | null}}`. New line: store hash, `since: null`. Hash differs: store it, `since = today`. Line missing from the stop-list result: entry untouched, so an API hiccup never wipes history.
- Published as `route_changed`. Accurate to about a day; changes before the first run are undetectable.

## 8. Frontend and web server

Goal-oriented and minimal: answer "how long will my trip take if I leave at X?". Mobile-first. External `app.js`, `slider.js`, `timetable.js`, `style.css` only (no inline scripts, no CDNs).

Controls, top to bottom: line search; direction ("→ last stop"); weekday (defaults to today); data window (1 to 12 months, default 1, only as many as `meta.months` covers); **stop slider**; timetable; a gear with one switch, "Include data from before route changes" (off by default, in `localStorage`).

**Stop slider** (`slider.js`, `createSlider(root, onChange)`; plain SVG + DOM). It selects a start and end stop and outputs two indexes `(a, b)` into the direction's stops, `a < b`; the timetable recomputes on every change. Default is the full route; changing line or direction resets it. With no stop-level data it stays visible, greyed out and locked to the full route, with a one-line note under it.

- **Layout:** the route is one continuous SVG line that wraps into rows like a snake (left to right, U-turn, right to left, ...), so it never scrolls horizontally. Stops per row = as many as fit with at least 36 px between nodes; recomputed on resize (`ResizeObserver`). A short line is one straight row.
- **Look:** neutral background, one accent colour, thin muted line outside the selection and a thick accent line between the handles; small dots for nodes (terminals slightly larger, hollow outside the selection, filled inside); light and dark via the page's CSS variables; transitions at most 120 ms. Handles are 36 px, inline-SVG icons: start = person (filled), end = pin (outlined). A summary line above shows `{start} → {end} · {k} stops` (k counts both ends); a node's name shows in a tooltip on hover or when a handle has keyboard focus. A "Full route" text button appears next to the summary only when the selection isn't the full route.
- **Tap/click a stop:** before the start, it becomes the start; after the end, it becomes the end; between them, the closer handle (in stop count) moves, ties move the start.
- **Drag a handle:** pointer events with `setPointerCapture`; it snaps to the nearest node in 2D, so it works across wrapped rows; the start can't pass the end. `touch-action: none` is set only on the handles, so swiping elsewhere scrolls the page.
- **Keyboard:** handles are `role="slider"`, `tabindex="0"`, with `aria-valuenow` and `aria-valuetext` = stop name. Arrows move one stop; Home/End jump the handle to its furthest allowed position (the start to the first stop or just before the end; the end to the last stop or just after the start).

**Timetable rows are the current schedule's departure times** for the direction and the weekday's day type (Mon-Fri `I`, Sat `C`, Sun `P`), never times from logged trips. A removed departure has no row, a moved one only finds trips since the move, a new one shows "no data yet".

Columns, full route: Departs, Duration (avg ± σ), Arrives, Min-Max, n. With stops: Departs, At start stop (avg clock time), Duration (avg ± σ), Min-Max, n.

**Averaging function** (`timetableRows` in `timetable.js`, one small function): a trip counts toward a row when `route == main_route`, `planned == row time`, its weekday matches, its date is within `[today - N months, yesterday]`, its date is `>= route_changed` (unless the setting is on, which only affects full-route times), and, in the stop view, `stops` exists, `stops.length` equals the direction's stop count and both selected stops are non-null. Values: `end - start`, or `stops[b] - stops[a]`. Output: average, population standard deviation (`–` when n = 1), min, max, n, and for stops the average clock time at the start stop.

Notices (one line, when relevant): "Route changed on 2 Nov; using data since then." or "Includes data from before the route change on 2 Nov."

**`deploy/nginx.conf`** (run as the normal user with `-p "$PWD"`): listens on `127.0.0.1:8080` only; `root site;`; pid, logs and temp paths in `deploy/run/` (gitignored); own small `types {}` block; `autoindex off`, `disable_symlinks on`, `server_tokens off`; dotfiles and `*.tmp` denied; GET/HEAD only; `client_max_body_size 1k`; `try_files $uri $uri/ =404`; headers `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a CSP (`default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'`), all `always`; gzip for json/js/css/svg. No rate limiting (cloudflared makes every client 127.0.0.1; Cloudflare does that).

## 9. Deployment: `.tmuxinator.yml` only

Everything runs as the normal user (never root) from one `.tmuxinator.yml`; start with `tmuxinator local` (or `tmuxinator start iett`). After a reboot run it again.

| Window | Command |
|---|---|
| `collector` | `while true; do python3 collect.py; echo "collector exited, restarting"; sleep 10; done` |
| `ingest` | `python3 ingest.py 31; python3 publish.py; while true; do python3 ingest.py; sleep 1h; done` |
| `publish` | `while true; do sleep 6h; python3 publish.py; find data/pings -name '*.csv' -mtime +0 -exec gzip {} \; ; done` |
| `web` | `mkdir -p deploy/run && nginx -p "$PWD" -c deploy/nginx.conf -g 'daemon off;'` |
| `tunnel` | `cloudflared tunnel run <TUNNEL_NAME>` (placeholder) |

The `ingest` window ingests the last month, publishes straight away so the site is live, then backfills up to a year. Code reading pings handles `.csv` and `.csv.gz`.

## 10. Out of scope (future issues, do not build)

- Excluding public holidays / bayram days, or a toggle for it
- "All weekdays combined" toggle if per-weekday averages prove too noisy
- Expected waiting time at the stop from headways
- Keeping historical stop lists instead of using today's
- Comparing planned vs actual departure times
- Route variants (`_D6074` etc.) as their own timetables
- Showing what changed when a schedule or route changes
- **Live buses on the stop slider.** `GetHatOtoKonum_json` gives each bus's line, route and nearest stop but requires a line code; the API sends no CORS headers, so it needs a server-side proxy; and it shares the documented 100 requests/hour limit with the collector (which uses 60). First step if picked up: confirm whether the limit is actually enforced.
