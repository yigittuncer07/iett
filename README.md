# Istanbul Bus Times

Static site showing how long each scheduled IETT departure actually took, as plain averages of logged trips over the last 28 days. Optionally filtered to a start and end stop. See `spec.md`.

Python 3, standard library only.

| File | Purpose |
|---|---|
| `iett.py` | SOAP helper: `call(service, method, params)` |
| `collect.py` | Long-running: fleet positions every 60s into `data/pings/` |
| `build.py` | Daily: fetch archive, stops and names; match trips to stops; write `site/data/` |
| `site/` | Static frontend (`index.html`) plus generated `site/data/` |

## Deploy

Start the collector first: stop-level data only exists from the day collection begins.

### Collector (systemd)

Edit `User=` and the paths in `collect.service`, then:

```
sudo cp collect.service /etc/systemd/system/
sudo systemctl enable --now collect
```

### Cron

Adjust the repo path. `build.py` reads both `.csv` and `.csv.gz` pings.

```
30 4 * * * cd /home/jeff/projects/iett && find data/pings -mtime +0 -name '*.csv' -exec gzip {} \;
0 5 * * *  cd /home/jeff/projects/iett && python3 build.py >> build.log 2>&1
```

The first `build.py` run backfills 28 days of the trip archive (about 20 MB per day, several minutes). Days whose archive is still empty are retried on the next run.

### nginx

```
server {
    listen 80;
    root /home/jeff/projects/iett/site;
    index index.html;
    gzip on;
    gzip_types application/json;
}
```

`build.py` swaps `site/data/` atomically, so nginx never serves a half-written build.
