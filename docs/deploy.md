# Putting the EMTSim editor on the web

There are two ways, and they differ in where the simulations are computed.

| | Public web site | Group server |
|---|---|---|
| Who uses it | anyone with the link | a small group you trust, with accounts |
| Where it computes | in each visitor's browser (C++ solver compiled to WebAssembly) | on your server |
| What the host needs | any static web hosting (GitHub Pages, Netlify, nginx) | a Linux (or Windows) machine, Python, a C++ build, an HTTPS proxy |
| Engines | C++ (in the browser) | C++ and Python on the server, and C++ in the browser |
| Saved circuits | in the visitor's browser, or downloaded as `.net` | in a folder per user on the server |
| Cost of a heavy run | the visitor's own computer | your server's processor |

For anything public, use the web site. Run the group server only for people you know.

## 1. Public web site (simulations in the browser)

Build the solver for the browser once, and again after any change to the C++ code in `src/`. It
needs the Emscripten SDK:

```sh
git clone https://github.com/emscripten-core/emsdk.git ~/emsdk
cd ~/emsdk && ./emsdk install 3.1.74 && ./emsdk activate 3.1.74     # emsdk.bat on Windows
cd <EMTSim folder>
python gui/build_wasm.py            # -> gui/wasm/emtsim.js, emtsim.wasm
node tests/test_wasm.js             # every example against the native C++ solver (build it first)
python gui/make_site.py --serve 8000    # -> site/, and try it at http://127.0.0.1:8000/
```

`site/` is the whole web site (about 1 MB): the editor, the worker that runs the solver, the
WebAssembly module and the example circuits. Upload its contents to any static host:

- **GitHub Pages:** push the contents of `site/` to a branch (for example `gh-pages`) and turn on
  Pages for that branch in the repository settings. `site/.nojekyll` is already there.
- **Netlify, Cloudflare Pages:** drag the `site` folder onto the dashboard, or point a project at it.
- **Your own nginx or Apache:** copy the folder under the web root. The host must send `.wasm`
  files as `application/wasm` and `.js` files as JavaScript; current nginx and Apache do.

On the site, Run uses the C++ solver in the visitor's browser, in a background thread, so the page
stays responsive and a long run can be stopped. Open lists the examples; Save keeps circuits in
that browser, and Download saves a `.net` file. The results equal the native solver's to the seven
significant digits that are sent for plotting (`tests/test_wasm.js`).

## 2. Group server (simulations on your server)

`gui/server.py` with a users file is a group server. On top of the local editor it adds:

| Protection | What it does | Options |
|---|---|---|
| Sign-in | every API call needs a session; passwords are stored as salted PBKDF2-SHA256 hashes; five wrong passwords lock that user name for a minute | `--users FILE`, `--session-hours` (12) |
| Per-user folders | Save writes to `<data>/<user>/`; Open lists the user's own circuits and the examples, which are read-only | `--data DIR` (`userdata/`) |
| Run limits | a run is refused if its `.tran` asks for too many time steps or the netlist is too big; each engine is stopped after a time limit | `--max-steps` (200000), `--max-kb` (1024), `--timeout` (120 s) |
| Job queue | a fixed number of runs at once, a limited number waiting (for a limited time), one run per user | `--workers` (half the cores), `--queue` (20), `--max-wait` (120 s) |
| Browser protections | cookies are `HttpOnly` and `SameSite=Strict` (and `Secure` with `--secure-cookies`); POSTs from another site are refused; a Content-Security-Policy, `nosniff` and no framing | |

The server refuses to listen beyond this computer (`--host 0.0.0.0`) without a users file.

### Setting it up on Linux

```sh
sudo useradd --system --home /srv/emtsim emtsim
sudo git clone https://github.com/realamilapathirana/EMTSIM3.git /srv/emtsim
cd /srv/emtsim
sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt
sudo ./build.sh                                   # the C++ solver (cmake and g++ needed)
sudo .venv/bin/python gui/build_wasm.py           # optional: also offer "C++ in this browser"
sudo .venv/bin/python gui/server.py --users /srv/emtsim/users.json --add-user alice   # asks for a password
sudo mkdir -p /srv/emtsim/userdata && sudo chown emtsim /srv/emtsim/userdata
sudo chown emtsim /srv/emtsim/users.json && sudo chmod 600 /srv/emtsim/users.json
```

Add, change or remove users the same way (`--add-user NAME` again changes a password,
`--remove-user NAME`, `--list-users`), then restart the service.

Run it as a service, `/etc/systemd/system/emtsim.service`:

```ini
[Unit]
Description=EMTSim circuit editor (group server)
After=network.target

[Service]
User=emtsim
WorkingDirectory=/srv/emtsim
ExecStart=/srv/emtsim/.venv/bin/python gui/server.py --users /srv/emtsim/users.json --data /srv/emtsim/userdata --secure-cookies --no-browser
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/srv/emtsim/userdata

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl daemon-reload && sudo systemctl enable --now emtsim
journalctl -u emtsim -f          # sign-ins and runs are logged here
```

The server listens on 127.0.0.1:8765 only. Put an HTTPS reverse proxy in front of it.

### HTTPS with Caddy (simplest: it gets and renews the certificate itself)

`/etc/caddy/Caddyfile`:

```
emtsim.example.org {
    reverse_proxy 127.0.0.1:8765
}
```

### HTTPS with nginx and Let's Encrypt

```nginx
server {
    listen 80;
    server_name emtsim.example.org;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl http2;
    server_name emtsim.example.org;
    ssl_certificate     /etc/letsencrypt/live/emtsim.example.org/fullchain.pem;   # from certbot
    ssl_certificate_key /etc/letsencrypt/live/emtsim.example.org/privkey.pem;
    client_max_body_size 2m;
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;     # the server checks that POSTs come from this host
        proxy_read_timeout 400s;         # more than --max-wait plus twice --timeout ("both" engines)
    }
}
```

With `--secure-cookies` the browser sends the session cookie over HTTPS only, so sign-in works
through the proxy but not at http://127.0.0.1:8765 directly.

### Keep in mind

- Back up `users.json` and the `userdata/` folder.
- Sessions are kept in memory: restarting the service signs everyone out.
- The limits bound one run, not a user's total use; the queue keeps the server from being
  overloaded, but a user can keep it busy one run at a time.
- Everything runs on one machine. For more users, raise `--workers` on a bigger machine, or point
  people to the public web site, where their own computers do the work.
- After `git pull`, run `./build.sh` (and `gui/build_wasm.py` if you offer the browser engine), then
  restart the service.
