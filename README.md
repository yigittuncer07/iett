# Istanbul Bus Times

Static site showing how long each scheduled IETT departure actually took, as plain averages of logged trips over up to 12 months, optionally between two chosen stops. See `spec.md`.

Python 3, standard library only. Needs `tmux`, `tmuxinator` and `nginx` (and `cloudflared` if you use the tunnel window).

| File | Purpose |
|---|---|
| `iett.py` | SOAP helper: `call(service, method, params)`, `fetch_stops()` |
| `collect.py` | Long-running: fleet positions every 60s into `data/pings/` |
| `ingest.py [days_back]` | One pass: fetch trip archive, match stops, write `data/trips/` and `data/days/` |
| `publish.py` | Write `site/data/` (line names, schedules, route changes, month files) |
| `site/` | Static frontend; `site/data/` is generated |
| `deploy/nginx.conf` | Hardened nginx config (listens on 127.0.0.1:8080 only) |
| `.tmuxinator.yml` | Runs everything |

## Run

Everything runs from `.tmuxinator.yml`, as your normal user (never root).

1. Set `root:` in `.tmuxinator.yml` to the repo path, and put your tunnel name in the `tunnel` window (or delete it).
2. From the repo directory: `tmuxinator local` (or, on older versions, symlink the file to `~/.config/tmuxinator/iett.yml` and run `tmuxinator start iett`).

| Window | Does |
|---|---|
| `collector` | Fleet positions every minute, restarted if it exits |
| `ingest` | Ingests the last 31 days, publishes (site is live), then backfills up to a year in the background, hourly |
| `publish` | Republishes every 6 hours and gzips old ping files |
| `web` | nginx on 127.0.0.1:8080 serving `site/` |
| `tunnel` | cloudflared pointing at 127.0.0.1:8080 |

tmux sessions don't survive a reboot: after a reboot, run tmuxinator again.

Start the collector as early as possible: stop-level data only exists from the day collection begins.
