# Deploying the viewer (private beta on your own Linux server)

Arabic version: [README.ar.md](README.ar.md).

The viewer is one small Flask application (`bf2demo.web`) plus a static page (plain ES modules, no build step). The only thing it needs on a
server is Python 3.10+, three pip packages and a folder of `.bf2demo` recordings. A reverse proxy (Caddy or nginx) gives it a domain, TLS and a password.

## How big it is (measured)

| part | size |
|---|---|
| page: HTML + CSS + 19 JS modules (2 480 lines) | 159 KB, **58 KB** over the wire (gzip) |
| web server code (`bf2demo/web/*.py`, 1 140 lines) | small; the whole `bf2demo` package is 2.6 MB (1.2 MB of it is the game's template tables) |
| the viewer's game asset store (`<cache>/game`: HUD icons, 8 fonts, tables, minimap + facts of 32 levels) | 10 MB (the HUD icons and fonts are only ~0.2 MB) |
| minimap backdrops (`<cache>/maps`) | 13 MB |
| optional HD maps (`<cache>/hd_maps`, 4096 px JPEGs) | 105 MB |
| one parsed recording (what the browser downloads, gzip) | 7 KB - 1.2 MB, median 136 KB (a 20 MB recording: 0.3 MB) |
| first visit of a normal match | about 0.5 - 1.7 MB, later visits use the browser cache |

Parsing is the only heavy part and happens **once per recording** (then it is cached on disk): a 20 MB recording takes about 23 s of one CPU core and
about 400 MB of RAM, a 2 hour 79 player round about 3 minutes and several GB. `BF2VIEW_MAX_PARSE=1` keeps a small server safe.

## What goes to the server, and what never does

Goes: the `bf2demo` package, `deploy/requirements-web.txt`, the recordings you pick, and (optional) the asset store and maps.
Stays on your PC (the publish script does not read them): `samples/` (recordings with the real names of other players), `extracted_bin/`
(the game's and the dedicated server's binaries), `re_work/` (decompiler output), `local/`, `.claude/`, `.agents/`, `tests/`, `.git`.

Two things to decide before the site is public (the beta is protected by a password for exactly this reason):

* **The game's own artwork.** With the asset store the page shows EA's icons, fonts and minimaps. Serve them only to people you trust, or publish with
  `--no-assets` (the viewer still works: grid instead of a map, plain shapes instead of icons, system fonts).
* **Player names.** Every recording lists its players. Publish recordings you may show, not the whole `samples/` folder.

## One-time setup (Ubuntu)

```bash
# 1. a service user and the folders
sudo adduser --system --group --home /srv/bf2view bf2view
sudo usermod -aG bf2view deploy                      # "deploy" = the account you push with over ssh
sudo mkdir -p /srv/bf2view/{app,demos,cache}
sudo chown -R deploy:bf2view /srv/bf2view
sudo chmod -R g+rX /srv/bf2view && sudo chmod 2775 /srv/bf2view/cache /srv/bf2view/demos && sudo chown bf2view:bf2view /srv/bf2view/cache

# 2. Python environment
sudo apt install -y python3-venv
python3 -m venv /srv/bf2view/venv
/srv/bf2view/venv/bin/pip install -r /srv/bf2view/app/deploy/requirements-web.txt    # after the first publish (step 4)

# 3. configuration and service
sudo install -m 640 -o root -g bf2view env.example /srv/bf2view/env                  # copy of deploy/env.example
sudo cp bf2view.service /etc/systemd/system/ && sudo systemctl daemon-reload
echo 'deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart bf2view' | sudo tee /etc/sudoers.d/bf2view
```

```bash
# 4. from your PC (Git Bash / WSL), in the repository
deploy/publish.sh deploy@your-server.example.com /path/to/the/recordings/you/choose
#   add --no-assets as the last argument to leave the game's artwork out
```

Then on the server: `sudo systemctl enable --now bf2view` and `curl -I http://127.0.0.1:8081/` (expects `200`).

## Domain, sub domain and TLS (Caddy)

1. DNS: an `A` (and `AAAA`) record `bf2.example.com` -> the server's address.
2. Copy `deploy/bf2view.caddy` into the folder your Caddyfile imports its site files from, replace the host name, make the password hash with
   `caddy hash-password`, then `sudo systemctl reload caddy`. Caddy requests the certificate by itself. (nginx: `deploy/nginx.conf.example` + certbot.)
3. Open `https://bf2.example.com/`, log in as `beta`.

## Updating and checking

* Update = run `deploy/publish.sh` again (it restarts the service). Recordings parsed once stay cached; a new document format re-parses them in the background.
* Logs: `journalctl -u bf2view -f`. Status: `systemctl status bf2view`.
* Single worker on purpose: the parse jobs live in the process. Do not raise `--workers`.
* `BF2VIEW_UPLOAD=1` allows uploads of up to 400 MB each by anyone who can open the page: keep it `0` unless the password stays on.

## The support button (Telegram, crypto wallets, payment links)

Copy `donate.example.json` to `/srv/bf2view/donate.json`, replace the placeholders and set `BF2VIEW_DONATE_FILE=/srv/bf2view/donate.json` (and restart).
The top bar button, the library card and a dialog with a copy button per wallet appear. Check the file before restarting:
`python -m bf2demo.web.donate /srv/bf2view/donate.json` prints what the page will show. Addresses are validated against the format of their network (USDT
on `TRC20`, `ERC20`/`BSC`/`POLYGON`..., `BTC`, `LTC`, `SOL`; unknown networks are accepted as written) and a bad one stops the start instead of being published;
links must be `https`. Keep the real file out of git (it is read from the server's own path). A wallet address is public by nature, but always send a
small test amount first and use one address per network.

## Before it is really public

Add rate limiting in the proxy, decide the artwork question above, and think about removing community recordings from the git history if the repository
itself is ever published (`extracted_bin/` and `samples/` are in the history; they are untracked now, not erased).
