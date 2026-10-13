import csv
import gzip
import json
import math
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from iett import call

WINDOW_DAYS = 28
MATCH_RADIUS_M = 300
METROBUS = {"34", "34A", "34AS", "34B", "34BZ", "34C", "34G", "34Z"}
TRIPS_DIR, PINGS_DIR, OUT = "data/trips", "data/pings", "site/data"
ISTANBUL = ZoneInfo("Europe/Istanbul")


def local(ms_text):
    """'/Date(ms)/' -> local 'YYYY-MM-DDTHH:MM:SS', or None."""
    if not ms_text:
        return None
    ms = int(re.search(r"-?\d+", ms_text).group())
    return datetime.fromtimestamp(ms / 1000, ISTANBUL).replace(tzinfo=None).isoformat(timespec="seconds")


def fetch_trips(day):
    """Save the day's completed trips to data/trips/. Empty archive days are skipped and retried next run."""
    path = f"{TRIPS_DIR}/{day}.csv"
    if os.path.exists(path):
        return
    rows = call("ibb/ibb360.asmx", "GetIettArsivGorev_json", f"<Tarih>{day:%Y%m%d}</Tarih>")
    trips = []
    for r in rows:
        planned, start, end = (local(r[k]) for k in ("DTPLANLANANBASLANGICZAMANI", "DTBASLAMAZAMANI", "DTBITISZAMANI"))
        if r["SGOREVDURUM"] == "T" and planned and start and end and r["SHATKODU"] not in METROBUS:
            trips.append([r["SHATKODU"], r["SGUZERGAHKODU"], r["SKAPINUMARA"], planned, start, end])
    if rows:
        with open(path, "w", newline="") as f:
            csv.writer(f).writerows([["line", "route", "door", "planned", "start", "end"]] + trips)


def open_csv(path):
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path)


def read_csv(path):
    with open_csv(path) as f:
        return list(csv.DictReader(f))


def distance_m(lat1, lon1, lat2, lon2):  # haversine
    a = math.sin(math.radians(lat2 - lat1) / 2) ** 2
    a += math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742000 * math.asin(math.sqrt(a))


def load_pings(day):
    """door -> [(time, lat, lon)] sorted by time, or None if there is no pings file for that day."""
    paths = [p for p in (f"{PINGS_DIR}/{day}.csv", f"{PINGS_DIR}/{day}.csv.gz") if os.path.exists(p)]
    if not paths:
        return None
    pings = defaultdict(list)
    for r in read_csv(paths[0]):
        pings[r["door"]].append((r["time"], float(r["lat"]), float(r["lon"])))
    return {door: sorted(p) for door, p in pings.items()}


def match_stops(pings, stops, start, end):
    """Seconds since start at which the bus was closest to each stop (None if never within radius)."""
    pings = [(datetime.fromisoformat(t), la, lo) for t, la, lo in pings if start <= t <= end]
    start_dt, times, i = datetime.fromisoformat(start), [], 0
    for lat, lon in stops:
        dist = lambda j: distance_m(pings[j][1], pings[j][2], lat, lon)
        j = i
        while j < len(pings) and dist(j) > MATCH_RADIUS_M:
            j += 1
        if j == len(pings):
            times.append(None)
            continue
        while j + 1 < len(pings) and dist(j + 1) < dist(j):
            j += 1
        times.append(round((pings[j][0] - start_dt).total_seconds()))
        i = j
    return times


def main():
    os.makedirs(TRIPS_DIR, exist_ok=True)
    names = {r["HAT_KODU"]: r["HAT_ADI"] for r in call("ibb/ibb.asmx", "HatServisi_GYY", "<hat_kodu></hat_kodu>")}
    stops = defaultdict(list)  # (line, dir) -> [(order, code, name, lat, lon)]
    for r in call("ibb/ibb.asmx", "DurakDetay_GYY", "<hat_kodu></hat_kodu>"):
        stops[r["HATKODU"], r["YON"]].append(
            (int(r["SIRANO"]), r["DURAKKODU"], r["DURAKADI"], float(r["YKOORDINATI"]), float(r["XKOORDINATI"])))
    stops = {k: sorted(v) for k, v in stops.items()}

    days = [date.today() - timedelta(days=n) for n in range(1, WINDOW_DAYS + 1)]
    trips_by_day = {}
    for day in days:
        try:
            fetch_trips(day)
        except Exception as error:
            print(f"fetch {day} failed: {error!r}")
        if os.path.exists(f"{TRIPS_DIR}/{day}.csv"):
            trips_by_day[day] = read_csv(f"{TRIPS_DIR}/{day}.csv")

    # keep only each (line, direction)'s most common route
    route_counts = defaultdict(Counter)
    for r in (r for rows in trips_by_day.values() for r in rows):
        route_counts[r["line"], r["route"].rsplit("_", 2)[1]][r["route"]] += 1
    main_route = {k: c.most_common(1)[0][0] for k, c in route_counts.items()}

    by_line = defaultdict(list)
    for day, rows in trips_by_day.items():
        pings = load_pings(day)
        for r in rows:
            direction = r["route"].rsplit("_", 2)[1]
            if main_route[r["line"], direction] != r["route"]:
                continue
            trip = {"date": str(day), "dir": direction, "planned": r["planned"][11:16],
                    "start": r["start"][11:19], "end": r["end"][11:19]}
            if pings and r["door"] in pings:
                coords = [(s[3], s[4]) for s in stops.get((r["line"], direction), [])]
                times = match_stops(pings[r["door"]], coords, r["start"], r["end"])
                if any(t is not None for t in times):
                    trip["stops"] = times
            by_line[r["line"]].append(trip)

    shutil.rmtree("site/data.tmp", ignore_errors=True)
    os.makedirs("site/data.tmp/lines")
    for code, line_trips in by_line.items():
        directions = {d: {"stops": [[s[1], s[2]] for s in stops.get((code, d), [])]} for d in {t["dir"] for t in line_trips}}
        with open(f"site/data.tmp/lines/{re.sub(r'[^A-Za-z0-9_-]', '_', code)}.json", "w") as f:
            json.dump({"code": code, "name": names.get(code, code), "directions": directions, "trips": line_trips}, f, ensure_ascii=False)
    with open("site/data.tmp/lines.json", "w") as f:
        json.dump([{"code": c, "name": names.get(c, c)} for c in sorted(by_line)], f, ensure_ascii=False)

    shutil.rmtree("site/data.old", ignore_errors=True)
    if os.path.exists(OUT):
        os.rename(OUT, "site/data.old")
    os.rename("site/data.tmp", OUT)
    shutil.rmtree("site/data.old", ignore_errors=True)
    print(f"built {len(by_line)} lines")


if __name__ == "__main__":
    main()
