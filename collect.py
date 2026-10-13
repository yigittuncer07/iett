import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from iett import call

SERVICE = "FiloDurum/SeferGerceklesme.asmx"
METHOD = "GetFiloAracKonum_json"
PINGS_DIR = "data/pings"
MAX_AGE = timedelta(minutes=5)
INTERVAL = 60
ISTANBUL = ZoneInfo("Europe/Istanbul")

last_seen = {}  # door -> Saat of the last position written


def position_time(saat, now):
    """Saat is 'HH:MM:SS' with no date: assume today, or yesterday if that is in the future."""
    t = datetime.strptime(saat, "%H:%M:%S").time()
    moment = datetime.combine(now.date(), t)
    return moment - timedelta(days=1) if moment > now else moment


def collect_once():
    now = datetime.now(ISTANBUL).replace(tzinfo=None)
    os.makedirs(PINGS_DIR, exist_ok=True)
    new_rows = 0
    for bus in call(SERVICE, METHOD):
        door, saat = bus["KapiNo"], bus["Saat"]
        if last_seen.get(door) == saat:
            continue
        last_seen[door] = saat
        moment = position_time(saat, now)
        if now - moment > MAX_AGE:
            continue
        path = f"{PINGS_DIR}/{moment.date()}.csv"
        new_file = not os.path.exists(path)
        with open(path, "a") as f:
            if new_file:
                f.write("door,time,lat,lon\n")
            f.write(f"{door},{moment.isoformat(timespec='seconds')},{bus['Enlem']},{bus['Boylam']}\n")
        new_rows += 1
    print(f"{now:%Y-%m-%d %H:%M:%S} wrote {new_rows} rows")


while True:
    try:
        collect_once()
    except Exception as error:
        print(f"error: {error!r}")
    time.sleep(INTERVAL)
