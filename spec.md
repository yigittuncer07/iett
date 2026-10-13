# Istanbul Bus Times — Build Spec

A static website that shows, for any IETT bus line, how long each scheduled departure **actually** took, averaged over real logged trips from the last 28 days. Optionally filtered to a start and end stop.

The numbers are plain averages of logged data. No estimation, prediction, interpolation or modelling anywhere.

---

## 0. Rules for the coding agent (read first)

**Logic code (`iett.py`, `collect.py`, `build.py`) will be reviewed by a human with little time.**

- Keep it as simple as possible. Fewer lines and fewer features beat cleverness.
- Python 3, **standard library only**. No pip dependencies.
- Budget: about **300 lines total** across the three files, **no file over ~150 lines**.
- Plain functions. No classes unless clearly simpler. No config files: constants at the top of each file.
- `print()` for logs. No logging framework, no retry/backoff machinery. If something fails, print one line and move on; the next run picks it up.
- No test suite, CLI framework, database, Docker or abstraction layers.
- Build only what this spec asks for. Anything in §8 is out of scope.
- Readable names, short functions, a one-line comment where intent isn't obvious.

**Frontend (`site/`)** is the exception: it won't be reviewed, so any approach is fine, with these constraints:

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

---

## 2. Repository layout

```
iett.py      # call(service, method, params="") -> parsed result. ~30 lines.
collect.py   # long-running: fleet snapshot every 60s -> data/pings/
build.py     # daily: fetch archive/stops/lines, match, write site/data/
data/
  pings/YYYY-MM-DD.csv(.gz)   # raw positions, kept forever
  trips/YYYY-MM-DD.csv        # filtered archive, kept forever
site/
  index.html …                # frontend
  data/                       # generated by build.py only
README.md                     # setup: systemd unit, cron lines, nginx snippet
```

---

## 3. `iett.py`

One function, `call(service, method, params="")`:

- Builds the SOAP envelope (§1), POSTs with `urllib.request` (timeout ~120s).
- `_json` methods → return the parsed JSON.
- `_GYY` methods → return a list of dicts, one per `<Table>` (tag → text).
- Raises on HTTP error or SOAP fault. Callers decide what to do.

---

## 4. `collect.py`

Runs forever as a systemd service.

Loop:

1. Call `GetFiloAracKonum_json`.
2. Convert each row's `Saat` to a full local datetime: use today's date (Istanbul time). If that lands **in the future**, use yesterday (handles midnight).
3. Skip rows where the position is **older than 5 minutes** (parked/stale buses).
4. Skip rows whose `(KapiNo, Saat)` equals the last one seen for that bus (in-memory dict). This keeps only new positions.
5. Append the rest to `data/pings/{date of the position}.csv`, columns:
   `door,time,lat,lon` (time as `YYYY-MM-DDTHH:MM:SS`, local).
6. Sleep 60 seconds. On any exception: print one line, sleep, continue.

Expected volume: roughly 1,500–2,000 new rows/minute at peak, ~100 MB/day uncompressed. A daily cron `gzip` compresses files older than a day (§7).

**This is step 1 and should be deployed first.** Stop-level data only exists from the day collection starts.

---

## 5. `build.py`

Runs daily from cron. Steps:

### 5.1 Fetch

1. `HatServisi_GYY` (all) → line names.
2. `DurakDetay_GYY` (all) → stop lists, grouped by `(HATKODU, YON)`, sorted by `SIRANO`.
3. For each date from **yesterday back 28 days**: if `data/trips/{date}.csv` doesn't exist, fetch `GetIettArsivGorev_json`. If the result is non-empty, save it filtered:
   - status `T`, has an end time, line not in the metrobüs list
   - columns: `line,route,door,planned,start,end` (times as local `YYYY-MM-DDTHH:MM:SS`)

   If the result is empty, skip saving; a later run fetches it. This one rule covers the first backfill, late archive availability, and missed days.

### 5.2 Choose each line's main route

For each `(line, direction)`, keep only trips on the **most common route code** in the 28-day window (e.g. `500T_G_D0`). Variants are short-turns or detours; ignore them for now.

### 5.3 Match trips to stops (only for dates that have a pings file)

For each trip, take that door's pings with `start ≤ time ≤ end`, sorted by time. Walk the stop list for the trip's line and direction in order, keeping a pointer into the pings:

- For each stop, starting from the pointer, find the **first ping within `MATCH_RADIUS_M = 300`** of the stop. While the following pings stay within the radius and get closer, move forward. Record the closest one's time, and set the pointer to it.
- If no ping is found within the radius, record `null` for that stop and don't move the pointer.
- Distance: haversine (stdlib `math`).

Store each stop's result as **seconds since the trip's actual start**, or `null`.

This uses raw ping times only (no interpolation). Pings arrive once a minute, so each stop time is accurate to about ±1 minute. That's a property of the data, not a bug.

Load each day's pings file once into a dict `door → [(time, lat, lon), …]` and process that day's trips. The build recomputes all 28 days each run; that's fine unless it becomes slow (see §8).

### 5.4 Write `site/data/`

`lines.json` — lines that have trips in the window:

```json
[{"code": "500T", "name": "TUZLA ŞİFA MAHALLESİ - 4. LEVENT METRO"}, …]
```

`lines/{code}.json` — one per line (make codes filename-safe):

```json
{
  "code": "500T",
  "name": "TUZLA ŞİFA MAHALLESİ - 4. LEVENT METRO",
  "directions": {
    "G": {"stops": [["code", "name"], …]},
    "D": {"stops": [["301341", "4.LEVENT METRO"], …]}
  },
  "trips": [
    {"date": "2026-10-12", "dir": "G", "planned": "07:10",
     "start": "07:12:31", "end": "09:40:05",
     "stops": [0, 95, 160, null, …]}
  ]
}
```

- `stops` has one entry per stop in that direction's list (same order), or is **omitted** for dates without pings.
- The direction's display name in the UI is "→ {last stop name}".

Write everything to `site/data.tmp/`, then swap it with `site/data/` using renames at the end. The site should never serve a half-written build.

---

## 6. Frontend

### Main flow

1. Search a line by code or name (from `lines.json`).
2. Pick direction (shown as "→ last stop") and weekday (**defaults to today**).
3. Show the **timetable**.

### Timetable (default: full route)

One row per **planned departure time** (`planned`), sorted, among trips matching direction + weekday:

| Departs | Avg duration | Arrives (planned + avg) | Min – Max | Trips (n) |

### With stops selected (optional start stop A and end stop B, B after A)

Same rows, using only trips where both A and B have non-null times:

| Departs | At stop A (avg clock time) | Avg A→B | Min – Max | Trips (n) |

If no trips have stop data, show a short note like "No stop-level data yet for this line; showing full route," and fall back to the full-route table.

### The averaging function (must be small and readable)

```
input: trips of one line, direction, weekday, optional stop indexes a, b
group trips by planned
for each group:
  values = full route: end - start (minutes)
           with stops: stops[b] - stops[a], skipping trips with a null
  row = planned, average(values), min, max, count
  (with stops: also average clock time at A = start + stops[a])
drop rows with count 0; return rows sorted by planned
```

### Design

Minimal, clean, elegant. Mobile-first: most users check this on a phone. One screen, no clutter. Show `n` on every row so users can judge how much data a number rests on.

---

## 7. Deployment (document in README.md)

- **Collector:** systemd service running `python3 collect.py` with `Restart=always`.
- **Cron:**
  - `0 5 * * *` → `python3 build.py`
  - `30 4 * * *` → gzip `data/pings/*.csv` older than one day (`find … -mtime +0 -name '*.csv' -exec gzip {} \;`). `build.py` must read both `.csv` and `.csv.gz` (use `gzip.open` when the name ends in `.gz`).
- **nginx:** serve `site/` as static files, with gzip enabled for `.json`. cloudflared already points at nginx.

---

## 8. Build order

1. `iett.py` + `collect.py` + its systemd unit. **Deploy and start collecting immediately.**
2. `build.py` §5.1, §5.2, §5.4 **without** stop matching (`stops` omitted everywhere). This backfills 28 days of archive, so full-route timetables work on day one.
3. Frontend: line search, direction, weekday, full-route timetable.
4. Stop matching (§5.3) + the stop filter in the frontend.
5. README with deployment snippets.

Stop after each step so the human can review.

---

## 9. Out of scope (future GitHub issues, do not build)

- Route variants (`_D6074` etc.) as their own timetables
- Excluding public holidays / bayram days, or a toggle for it
- "All weekdays combined" toggle if per-weekday averages (max 4 trips each) prove too noisy
- Expected waiting time at the stop from headways
- Caching per-day match results if the build gets slow
- Keeping historical stop lists instead of using today's
- Comparing planned vs actual departure times
