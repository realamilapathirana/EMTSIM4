"""Web server for the EMTSim circuit editor.

On this computer (the default):
    python gui/server.py            # opens http://127.0.0.1:8765 in your browser
    python gui/server.py --no-browser --port 9000

For a small group (docs/deploy.md): users sign in, each has a folder for saved circuits, runs are
limited in size and queued, and the server sits behind an HTTPS reverse proxy (Caddy, nginx):
    python gui/server.py --users users.json --add-user alice
    python gui/server.py --users users.json --data userdata --secure-cookies --no-browser

Serves the editor (gui/index.html, with the WebAssembly solver from gui/build_wasm.py if built)
and a JSON API:
    GET  /api/info                 mode, engines, signed-in user, limits
    POST /api/login  {user, password}    POST /api/logout
    GET  /api/circuits             the .net files: examples in circuits/ and (group) the user's own
    GET  /api/circuit?name=x.net[&mine=1]
    POST /api/save   {name, text}  into circuits/ (on this computer) or the user's folder (group)
    POST /api/run    {text, engine: "cpp" | "python" | "both"}
Uses the Python standard library only; the Python simulator itself needs numpy and scipy.
"""
import argparse
import csv
import getpass
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

GUI = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(GUI)
CIRCUITS = os.path.join(ROOT, "circuits")
sys.path.insert(0, GUI)
from accounts import Accounts, SignInError  # noqa: E402

STATIC = {"/": "index.html", "/index.html": "index.html", "/schematic.js": "schematic.js",
          "/emtsim_worker.js": "emtsim_worker.js", "/wasm/emtsim.js": "wasm/emtsim.js", "/wasm/emtsim.wasm": "wasm/emtsim.wasm"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".wasm": "application/wasm"}
COOKIE = "emtsim_session"
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; worker-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")


class Settings:
    accounts = None          # Accounts: sign-in required (group server)
    data = None              # folder with one sub-folder of saved circuits per user
    secure_cookies = False
    max_steps = None         # limits on one run (None: none)
    max_kb = None
    timeout = 600            # seconds per engine
    queue = None             # None: no queue; else a Queue


S = Settings()


class Busy(Exception):
    pass


class Queue:
    """At most `workers` simulations at once, at most `waiting` more waiting (each for at most
    `max_wait` seconds), one per user"""

    def __init__(self, workers, waiting, max_wait):
        self.slots = threading.BoundedSemaphore(workers)
        self.capacity = workers + waiting
        self.max_wait = max_wait
        self.active_users = set()      # running or waiting, one run each
        self.lock = threading.Lock()

    def run(self, user, job):
        with self.lock:
            if user in self.active_users:
                raise Busy(429, "You already have a run in progress; wait for it to finish.")
            if len(self.active_users) >= self.capacity:
                raise Busy(503, "The server is busy: too many runs are waiting. Try again in a minute.")
            self.active_users.add(user)
        try:
            if not self.slots.acquire(timeout=self.max_wait):
                raise Busy(503, "The server is busy: the run waited %d s for its turn. Try again later." % self.max_wait)
            try:
                return job()
            finally:
                self.slots.release()
        finally:
            with self.lock:
                self.active_users.discard(user)


def find_cpp_exe():
    for rel in ("build/emtsim.exe", "build/Release/emtsim.exe", "build/emtsim", "build/Release/emtsim"):
        p = os.path.join(ROOT, rel)
        if os.path.isfile(p):
            return p
    return None


def engines():
    e = []
    if find_cpp_exe():
        e.append("cpp")
    try:
        import numpy  # noqa: F401
        import scipy  # noqa: F401
        e.append("python")
    except ImportError:
        pass
    if len(e) == 2:
        e.append("both")
    if os.path.isfile(os.path.join(GUI, "wasm", "emtsim.wasm")):
        e.append("wasm")
    return e


def run_cpp(net_path, work):
    exe = find_cpp_exe()
    if not exe:
        return {"error": "The C++ simulator is not built yet. Run build.bat (or cmake) first."}
    p = subprocess.run([exe, net_path], cwd=work, capture_output=True, text=True, timeout=S.timeout)
    if p.returncode != 0:
        return {"error": (p.stderr or p.stdout).strip()[-4000:]}
    with open(os.path.join(work, "results.csv"), newline="") as f:
        rows = list(csv.reader(f))
    names = rows[0][1:]
    data = [[float(x) for x in r] for r in rows[1:] if r]
    faults, switches = [], []
    with open(os.path.join(work, "events.csv"), newline="") as f:
        for r in csv.DictReader(f):
            if r["type"] == "fault":
                faults.append([float(r["t_start"]), float(r["t_end"]) if r["t_end"] else None])
            else:
                switches.append(float(r["t_start"]))
    sim_ms = next((float(l.split(":")[1].split()[0]) for l in p.stdout.splitlines() if l.startswith("Simulation time:")), None)
    cnames, I = [], []
    cpath = os.path.join(work, "currents.csv")
    if os.path.isfile(cpath):   # branch currents (and machine speed, angle, power, torque)
        with open(cpath, newline="") as f:
            crow = list(csv.reader(f))
        cnames = crow[0][1:]
        cdata = [[float(x) for x in r[1:]] for r in crow[1:] if r]
        I = [[r[k] for r in cdata] for k in range(len(cnames))]
    return {"names": names, "t": [r[0] for r in data], "V": [[r[k + 1] for r in data] for k in range(len(names))],
            "cnames": cnames, "I": I,
            "events": {"faults": faults, "switches": switches}, "sim_ms": sim_ms,
            "log": "\n".join(l for l in p.stdout.splitlines() if l.startswith("t = ") or l.startswith("Warning"))}


def run_python(net_path):
    p = subprocess.run([sys.executable, os.path.join(GUI, "run_python.py"), net_path],
                       cwd=ROOT, capture_output=True, text=True, timeout=S.timeout)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (p.stderr or p.stdout or "Python simulator failed").strip()[-4000:]}


def simulate(text, engine):
    with tempfile.TemporaryDirectory(prefix="emtsim_") as work:
        net_path = os.path.join(work, "circuit.net")
        with open(net_path, "w", newline="\n") as f:
            f.write(text)
        out = {}
        if engine in ("cpp", "both"):
            out["cpp"] = run_cpp(net_path, work)
        if engine in ("python", "both"):
            out["python"] = run_python(net_path)
    a, b = out.get("cpp"), out.get("python")
    if a and b and "error" not in a and "error" not in b and len(a["V"]) == len(b["V"]):
        diff = max((abs(x - y) for va, vb in zip(a["V"], b["V"]) for x, y in zip(va, vb)), default=0.0)
        peak = max((abs(x) for v in b["V"] for x in v), default=0.0)
        out["compare"] = {"max_diff": diff, "peak": peak,
                          "speedup": (b["sim_ms"] / a["sim_ms"]) if a.get("sim_ms") else None}
    # The comparison above uses full precision; for plotting, 7 significant digits are plenty
    # and roughly halve the size of the response for large networks.
    for r in (a, b):
        for key in ("V", "I"):
            if r and key in r:
                r[key] = [[float("%.7g" % x) for x in v] for v in r[key]]
    return out


def time_steps(text):
    """Number of time steps the netlist asks for: its last .tran line, as in the simulators
    (or the default 100 us for 0.1 s)"""
    dt, stop = 100e-6, 0.1
    for line in text.splitlines():
        tok = line.split("#", 1)[0].split()
        if tok and tok[0].lower() == ".tran":
            try:
                dt, stop = float(tok[1]), float(tok[2])
            except (IndexError, ValueError):
                continue       # the simulator stops at this line with an error
    return stop/dt if dt > 0 else float("inf")


def check_size(text):
    if S.max_kb is not None and len(text.encode("utf-8")) > S.max_kb*1024:
        raise ValueError("The netlist is larger than %d kB, the limit on this server." % S.max_kb)


def check_limits(text):
    check_size(text)
    if S.max_steps is not None:
        n = time_steps(text)
        if n > S.max_steps:
            raise ValueError("This run has %.0f time steps; the limit on this server is %d. Use a larger time step "
                             "or a shorter run, or run it on your own computer (or with 'C++ in this browser')."
                             % (n, S.max_steps))


def safe_name(name):
    name = os.path.basename(str(name or "").strip())
    if not name.endswith(".net"):
        name += ".net"
    if not re.fullmatch(r"[A-Za-z0-9_.\- ]+\.net", name):
        raise ValueError("Use only letters, digits, spaces, '-', '_' and '.' in the file name.")
    return name


def user_folder(user):
    d = os.path.join(S.data, user)
    os.makedirs(d, exist_ok=True)
    return d


def list_files(folder, mine):
    files = []
    for n in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if n.endswith(".net"):
            with open(os.path.join(folder, n), encoding="utf-8") as f:
                files.append({"name": n, "drawing": any(l.startswith("#@layout ") for l in f), "mine": mine})
    return files


def log(*parts):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *parts, flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8", headers=()):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def token(self):
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return c[COOKIE].value if COOKIE in c else None

    def user(self):
        """The signed-in user; '' when the server has no sign-in (this computer)"""
        return S.accounts.user(self.token()) if S.accounts else ""

    def same_origin(self):
        # a browser sends Origin with every POST; a page on another site must not drive this API
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "")
        return urlparse(origin).netloc == host

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in STATIC:
            fname = os.path.join(GUI, STATIC[url.path])
            if os.path.isfile(fname):
                with open(fname, "rb") as f:
                    return self.send(200, f.read(), TYPES[os.path.splitext(fname)[1]])
        if url.path == "/api/info":
            return self.send(200, {"mode": "server", "login": S.accounts is not None, "user": self.user() or None,
                                   "engines": engines(),
                                   "limits": {"max_steps": S.max_steps, "max_kb": S.max_kb, "timeout_s": S.timeout}})
        if not url.path.startswith("/api/"):
            return self.send(404, {"error": "not found"})
        user = self.user()
        if user is None:
            return self.send(401, {"error": "Sign in first."})
        if url.path == "/api/circuits":
            files = list_files(user_folder(user), True) if user else []
            return self.send(200, {"files": files + list_files(CIRCUITS, False)})
        if url.path == "/api/circuit":
            try:
                q = parse_qs(url.query)
                name = safe_name(q.get("name", [""])[0])
                folder = user_folder(user) if user and q.get("mine") else CIRCUITS
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    return self.send(200, {"name": name, "text": f.read()})
            except (OSError, ValueError) as e:
                return self.send(404, {"error": str(e)})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.same_origin():
            return self.send(403, {"error": "cross-site request refused"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > ((S.max_kb or 64*1024) + 64)*1024:
            return self.send(413, {"error": "request too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self.send(400, {"error": "invalid JSON"})
        path = urlparse(self.path).path
        if path == "/api/login":
            if not S.accounts:
                return self.send(400, {"error": "this server has no sign-in"})
            try:
                token = S.accounts.sign_in(body.get("user"), body.get("password"))
            except SignInError as e:
                log("sign-in failed:", repr(str(body.get("user"))[:40]))
                return self.send(401, {"error": str(e)})
            log("signed in:", body.get("user"))
            cookie = "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d%s" % (
                COOKIE, token, int(S.accounts.session_seconds), "; Secure" if S.secure_cookies else "")
            return self.send(200, {"user": body.get("user")}, headers=[("Set-Cookie", cookie)])
        if path == "/api/logout":
            if S.accounts:
                S.accounts.sign_out(self.token())
            return self.send(200, {"ok": True}, headers=[("Set-Cookie", COOKIE + "=; Path=/; Max-Age=0")])
        user = self.user()
        if user is None:
            return self.send(401, {"error": "Sign in first."})
        try:
            if path == "/api/save":
                name = safe_name(body.get("name"))
                text = str(body.get("text", ""))
                check_size(text)
                folder = user_folder(user) if user else CIRCUITS
                with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
                return self.send(200, {"saved": name if user else "circuits/" + name})
            if path == "/api/run":
                engine = body.get("engine", "cpp")
                if engine not in ("cpp", "python", "both") or engine not in engines():
                    return self.send(400, {"error": "engine must be one of " + ", ".join(e for e in engines() if e != "wasm")})
                text = str(body.get("text", ""))
                check_limits(text)
                t0 = time.time()
                job = lambda: simulate(text, engine)  # noqa: E731
                out = S.queue.run(user, job) if S.queue else job()
                if S.accounts:
                    log("run:", user, engine, "%.0f steps" % time_steps(text), "%.1f s" % (time.time() - t0))
                return self.send(200, out)
        except Busy as e:
            return self.send(e.args[0], {"error": e.args[1]})
        except subprocess.TimeoutExpired:
            return self.send(500, {"error": "The simulation took longer than %d s and was stopped." % S.timeout})
        except (OSError, ValueError) as e:
            return self.send(400, {"error": str(e)})
        self.send(404, {"error": "not found"})


def is_loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def manage_users(args):
    acc = Accounts(args.users)
    if args.add_user:
        pw = os.environ.get("EMTSIM_PASSWORD") or getpass.getpass("Password for %s: " % args.add_user)
        if not os.environ.get("EMTSIM_PASSWORD") and getpass.getpass("Again: ") != pw:
            sys.exit("The passwords differ.")
        acc.set_password(args.add_user, pw)
        print("Saved user %s in %s" % (args.add_user, args.users))
    if args.remove_user:
        acc.remove(args.remove_user)
        print("Removed user %s" % args.remove_user)
    if args.list_users:
        print("\n".join(sorted(acc.users)) or "(no users)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="EMTSim circuit editor server")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this computer only)")
    ap.add_argument("--no-browser", action="store_true")
    g = ap.add_argument_group("group server")
    g.add_argument("--users", help="users file: sign-in required, per-user folders, limits and a queue")
    g.add_argument("--add-user", metavar="NAME", help="add a user or change a password (asks for it), then exit")
    g.add_argument("--remove-user", metavar="NAME")
    g.add_argument("--list-users", action="store_true")
    g.add_argument("--data", default=os.path.join(ROOT, "userdata"), help="folder for the users' saved circuits")
    g.add_argument("--secure-cookies", action="store_true", help="behind an HTTPS proxy: cookies only over HTTPS")
    g.add_argument("--max-steps", type=int, default=200_000, help="time steps per run (group server)")
    g.add_argument("--max-kb", type=int, default=1024, help="netlist size in kB (group server)")
    g.add_argument("--timeout", type=int, default=120, help="seconds per engine and run (group server)")
    g.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)//2), help="runs at once")
    g.add_argument("--queue", type=int, default=20, help="runs allowed to wait")
    g.add_argument("--max-wait", type=int, default=120, help="seconds a run may wait for its turn")
    g.add_argument("--session-hours", type=float, default=12.0)
    args = ap.parse_args(argv)

    if args.add_user or args.remove_user or args.list_users:
        if not args.users:
            sys.exit("Give the users file with --users")
        return manage_users(args)
    if args.users:
        S.accounts = Accounts(args.users, args.session_hours)
        if not S.accounts.users:
            sys.exit("%s has no users yet: add one with --add-user NAME" % args.users)
        S.data = os.path.abspath(args.data)
        os.makedirs(S.data, exist_ok=True)
        S.secure_cookies = args.secure_cookies
        S.max_steps, S.max_kb, S.timeout = args.max_steps, args.max_kb, args.timeout
        S.queue = Queue(args.workers, args.queue, args.max_wait)
    elif not is_loopback(args.host) or args.secure_cookies:
        sys.exit("Serving other computers needs sign-in: add --users users.json (see docs/deploy.md)")

    server = None
    for port in range(args.port, args.port + (1 if args.users else 20)):
        try:
            server = ThreadingHTTPServer((args.host, port), Handler)
            break
        except OSError:
            continue
    if server is None:
        sys.exit("No free port found near %d" % args.port)
    server.daemon_threads = True
    url = "http://%s:%d/" % ("127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host, server.server_address[1])
    print("EMTSim circuit editor running at %s" % url)
    print("Engines: %s" % (", ".join(engines()) or "none (run build.bat)"))
    if S.accounts:
        print("Group server: %d users, saved circuits in %s, at most %d steps, %d s, %d runs at once"
              % (len(S.accounts.users), S.data, S.max_steps, S.timeout, args.workers))
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
