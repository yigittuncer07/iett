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
| `deploy/nginx.conf` | Hardened nginx config (listens on 0.0.0.0:8001) |
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
| `web` | nginx on port 8001 serving `site/` |
| `tunnel` | cloudflared tunnel to nginx (see below) |

tmux sessions don't survive a reboot: after a reboot, run tmuxinator again.

Start the collector as early as possible: stop-level data only exists from the day collection begins.

## Network and tunnel

The cloudflared tunnel's service URL is `http://127.0.0.1:8001` when cloudflared runs directly on the host, or `http://<host LAN IP>:8001` when it runs in Docker.

nginx now listens on all interfaces, so the site is reachable from the local network on port 8001. That's fine: it serves only `site/`. Don't port-forward 8001 on the router; public traffic should only arrive through the Cloudflare tunnel.
