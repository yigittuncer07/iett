import glob
import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from iett import call, fetch_stops

KEEP_DAYS = 365
SITE, DAYS_DIR, CHANGES = "site/data", "data/days", "data/changes.json"
TODAY = datetime.now(ZoneInfo("Europe/Istanbul")).date()
OLDEST_DAY = str(TODAY - timedelta(days=KEEP_DAYS))


def safe(code):
    return re.sub(r"[^A-Za-z0-9_-]", "_", code)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def write_json(path, data):
    write_text(path, json.dumps(data, ensure_ascii=False))


def detect_route_changes(stops):
    """Fingerprint each line's ordered stop codes; a different fingerprint means the route changed today."""
    changes = json.load(open(CHANGES)) if os.path.exists(CHANGES) else {}
    for line in {line for line, _ in stops}:
        directions = sorted(d for l, d in stops if l == line)
        fingerprint = "|".join(d + ":" + ",".join(s[0] for s in stops[line, d]) for d in directions)
        digest = hashlib.sha1(fingerprint.encode()).hexdigest()
        if line not in changes:
            changes[line] = {"hash": digest, "since": None}
        elif changes[line]["hash"] != digest:
            changes[line] = {"hash": digest, "since": str(TODAY)}
    write_json(CHANGES, changes)
    return changes


def rewrite_months(last_publish):
    """Rewrite lines/{code}/{YYYY-MM}.json for months with a day file newer than the last publish."""
    files = sorted(f for f in glob.glob(f"{DAYS_DIR}/*.json") if os.path.basename(f)[:10] >= OLDEST_DAY)
    stale = {os.path.basename(f)[:7] for f in files if os.path.getmtime(f) > last_publish}
    for month in sorted(stale):
        by_line = defaultdict(list)  # trips kept as JSON strings to save memory
        for f in (f for f in files if os.path.basename(f).startswith(month)):
            for line, trips in json.load(open(f)).items():
                by_line[line] += [json.dumps(t, ensure_ascii=False) for t in trips]
        for line, trips in by_line.items():
            write_text(f"{SITE}/lines/{safe(line)}/{month}.json", '{"trips":[' + ",".join(trips) + "]}")
        print(f"{month}: rewrote {len(by_line)} lines")


def months_on_disk(code):
    """Months with a month file for this line; month files wholly outside the window are deleted."""
    months = []
    for path in sorted(glob.glob(f"{SITE}/lines/{safe(code)}/????-??.json")):
        month = os.path.basename(path)[:7]
        if month < OLDEST_DAY[:7]:
            os.remove(path)
        else:
            months.append(month)
    return months


def build_meta(code, name, stops, schedule_rows, route_changed, months):
    directions = {}
    for d in ("G", "D"):
        rows = [r for r in schedule_rows if r["SYON"] == d]
        if not rows:
            continue
        main_route = Counter(r["SGUZERAH"] for r in rows).most_common(1)[0][0]
        schedule = {t: sorted({r["DT"] for r in rows if r["SGUZERAH"] == main_route and r["SGUNTIPI"] == t}) for t in "ICP"}
        directions[d] = {"main_route": main_route, "stops": [[s[0], s[1]] for s in stops.get((code, d), [])],
                         "schedule": schedule}
    return {"code": code, "name": name, "route_changed": route_changed, "directions": directions, "months": months}


def main():
    started = time.time()
    lines_json = f"{SITE}/lines.json"
    last_publish = os.path.getmtime(lines_json) if os.path.exists(lines_json) else 0
    names = {r["HAT_KODU"]: r["HAT_ADI"] for r in call("ibb/ibb.asmx", "HatServisi_GYY", "<hat_kodu></hat_kodu>")}
    stops = fetch_stops()
    changes = detect_route_changes(stops)
    rewrite_months(last_publish)

    published = []
    for code, name in sorted(names.items()):
        months = months_on_disk(code)
        if not months:
            continue
        meta_path = f"{SITE}/lines/{safe(code)}/meta.json"
        try:
            time.sleep(0.5)
            rows = call("UlasimAnaVeri/PlanlananSeferSaati.asmx", "GetPlanlananSeferSaati_json", f"<HatKodu>{code}</HatKodu>")
            if rows:
                write_json(meta_path, build_meta(code, name, stops, rows, changes.get(code, {}).get("since"), months))
        except Exception as error:  # keep the previous meta.json, if any
            print(f"{code}: schedule failed: {error!r}")
        if os.path.exists(meta_path):
            published.append({"code": code, "name": name})

    write_json(lines_json, published)
    os.utime(lines_json, (started, started))  # days processed during this run count as newer next time
    print(f"published {len(published)} lines")


if __name__ == "__main__":
    main()
