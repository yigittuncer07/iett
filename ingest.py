import csv
import gzip
import json
import math
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from iett import call, fetch_stops

MATCH_RADIUS_M = 300
METROBUS = {"34", "34A", "34AS", "34B", "34BZ", "34C", "34G", "34Z"}
TRIPS_DIR, PINGS_DIR, DAYS_DIR = "data/trips", "data/pings", "data/days"
ISTANBUL = ZoneInfo("Europe/Istanbul")


def local(ms_text):
    """'/Date(ms)/' -> local 'YYYY-MM-DDTHH:MM:SS', or None."""
    if not ms_text:
        return None
    ms = int(re.search(r"-?\d+", ms_text).group())
    return datetime.fromtimestamp(ms / 1000, ISTANBUL).replace(tzinfo=None).isoformat(timespec="seconds")


def fetch_trips(day):
    """Save the day's completed trips. Returns False if the archive is still empty (retried next pass)."""
    rows = call("ibb/ibb360.asmx", "GetIettArsivGorev_json", f"<Tarih>{day:%Y%m%d}</Tarih>")
    if not rows:
        return False
    trips = []
    for r in rows:
        planned, start, end = (local(r[k]) for k in ("DTPLANLANANBASLANGICZAMANI", "DTBASLAMAZAMANI", "DTBITISZAMANI"))
        if r["SGOREVDURUM"] == "T" and planned and start and end and r["SHATKODU"] not in METROBUS:
            trips.append([r["SHATKODU"], r["SGUZERGAHKODU"], r["SKAPINUMARA"], planned, start, end])
    with open(f"{TRIPS_DIR}/{day}.csv", "w", newline="") as f:
        csv.writer(f).writerows([["line", "route", "door", "planned", "start", "end"]] + trips)
    return True


def read_csv(path):
    with (gzip.open(path, "rt") if path.endswith(".gz") else open(path)) as f:
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


def process_day(day, stops):
    """Write data/days/{day}.json: {line: [trip, ...]} for every trip, with stop times where pings exist."""
    pings = load_pings(day)
    by_line = defaultdict(list)
    for r in read_csv(f"{TRIPS_DIR}/{day}.csv"):
        direction = r["route"].rsplit("_", 2)[1]
        trip = {"date": str(day), "dir": direction, "route": r["route"], "planned": r["planned"][11:16],
                "start": r["start"][11:19], "end": r["end"][11:19]}
        if pings and r["door"] in pings and (r["line"], direction) in stops:
            coords = [(s[2], s[3]) for s in stops[r["line"], direction]]
            times = match_stops(pings[r["door"]], coords, r["start"], r["end"])
            if any(t is not None for t in times):
                trip["stops"] = times
        by_line[r["line"]].append(trip)
    path = f"{DAYS_DIR}/{day}.json"
    with open(path + ".tmp", "w") as f:
        json.dump(by_line, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def main():
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 365
    os.makedirs(TRIPS_DIR, exist_ok=True)
    os.makedirs(DAYS_DIR, exist_ok=True)
    stops = fetch_stops()
    for n in range(1, days_back + 1):  # newest first
        day = date.today() - timedelta(days=n)
        try:
            if not os.path.exists(f"{TRIPS_DIR}/{day}.csv"):
                fetched = fetch_trips(day)
                time.sleep(5)
                if not fetched:
                    print(f"{day}: archive empty, skipping")
                    continue
            if not os.path.exists(f"{DAYS_DIR}/{day}.json"):
                process_day(day, stops)
                print(f"{day}: processed")
        except Exception as error:
            print(f"{day} failed: {error!r}")


if __name__ == "__main__":
    main()
