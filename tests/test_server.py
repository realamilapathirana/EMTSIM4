"""The editor server: local mode, and the group server's sign-in, folders, limits and queue.
    python tests/test_server.py            (the C++ simulator must be built: build.bat)
"""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gui"))
import server  # noqa: E402

def read(name):
    with open(os.path.join(ROOT, "circuits", name), encoding="utf-8") as f:
        return f.read()


DEMO = read("demo_chatter.net")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Client:
    def __init__(self, port):
        self.port, self.cookie = port, None

    def call(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        h = {"Content-Type": "application/json"}
        if self.cookie:
            h["Cookie"] = self.cookie
        h.update(headers or {})
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        data = r.read()
        sc = r.getheader("Set-Cookie")
        if sc:
            self.cookie = sc.split(";")[0]
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data


def start(args):
    port = free_port()
    server.S.__dict__.clear()        # fresh settings for each server
    t = threading.Thread(target=server.main, args=(["--port", str(port), "--no-browser"] + args,), daemon=True)
    t.start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), 0.1).close()
            return port
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("server did not start")


class LocalServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Client(start([]))

    def test_info_and_run(self):
        code, info = self.c.call("GET", "/api/info")
        self.assertEqual((code, info["mode"], info["login"]), (200, "server", False))
        self.assertIn("cpp", info["engines"])
        code, r = self.c.call("POST", "/api/run", {"text": DEMO, "engine": "cpp"})
        self.assertEqual(code, 200)
        self.assertEqual(len(r["cpp"]["t"]), 50)

    def test_lists_examples(self):
        code, r = self.c.call("GET", "/api/circuits")
        self.assertIn("demo_chatter.net", [f["name"] for f in r["files"]])

    def test_static_files_and_headers(self):
        c = http.client.HTTPConnection("127.0.0.1", self.c.port, timeout=10)
        c.request("GET", "/")
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 200)
        self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy"))

    def test_cross_site_post_refused(self):
        code, _ = self.c.call("POST", "/api/run", {"text": DEMO}, {"Origin": "https://evil.example"})
        self.assertEqual(code, 403)


class GroupServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="emtsim_test_")
        cls.users = os.path.join(cls.tmp, "users.json")
        env = dict(os.environ, EMTSIM_PASSWORD="correct horse")
        for u in ("alice", "bob"):
            subprocess.run([sys.executable, os.path.join(ROOT, "gui", "server.py"), "--users", cls.users, "--add-user", u],
                           env=env, check=True, capture_output=True)
        cls.port = start(["--users", cls.users, "--data", os.path.join(cls.tmp, "data"),
                          "--max-steps", "5000", "--workers", "1", "--queue", "0", "--timeout", "60"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def signed_in(self, user="alice"):
        c = Client(self.port)
        code, _ = c.call("POST", "/api/login", {"user": user, "password": "correct horse"})
        self.assertEqual(code, 200)
        return c

    def test_password_is_hashed(self):
        with open(self.users, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("correct horse", text)
        self.assertIn("iterations", text)

    def test_sign_in_required(self):
        c = Client(self.port)
        self.assertEqual(c.call("GET", "/api/info")[1]["user"], None)
        self.assertEqual(c.call("GET", "/api/circuits")[0], 401)
        self.assertEqual(c.call("POST", "/api/run", {"text": DEMO})[0], 401)
        self.assertEqual(c.call("POST", "/api/login", {"user": "alice", "password": "wrong"})[0], 401)
        self.assertEqual(c.call("GET", "/api/circuits")[0], 401)

    def test_lockout_after_wrong_passwords(self):
        c = Client(self.port)
        for _ in range(5):
            c.call("POST", "/api/login", {"user": "bob", "password": "wrong"})
        code, r = c.call("POST", "/api/login", {"user": "bob", "password": "correct horse"})
        self.assertEqual(code, 401)
        self.assertIn("wait a minute", r["error"])
        server.S.accounts._failures.pop("bob", None)     # unlock for the other tests

    def test_cookie_flags(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", "/api/login", json.dumps({"user": "alice", "password": "correct horse"}), {"Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        sc = r.getheader("Set-Cookie")
        self.assertIn("HttpOnly", sc)
        self.assertIn("SameSite=Strict", sc)

    def test_own_folders(self):
        a, b = self.signed_in("alice"), self.signed_in("bob")
        self.assertEqual(a.call("POST", "/api/save", {"name": "mine", "text": DEMO}), (200, {"saved": "mine.net"}))
        files_a = a.call("GET", "/api/circuits")[1]["files"]
        files_b = b.call("GET", "/api/circuits")[1]["files"]
        self.assertIn({"name": "mine.net", "drawing": True, "mine": True}, files_a)
        self.assertNotIn("mine.net", [f["name"] for f in files_b if f["mine"]])
        self.assertEqual(a.call("GET", "/api/circuit?name=mine.net&mine=1")[1]["text"], DEMO)
        self.assertEqual(b.call("GET", "/api/circuit?name=mine.net&mine=1")[0], 404)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "data", "alice", "mine.net")))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "circuits", "mine.net")))
        self.assertEqual(a.call("POST", "/api/save", {"name": "../../evil", "text": "x"})[1], {"saved": "evil.net"})
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.net")))

    def test_run_and_limits(self):
        a = self.signed_in()
        code, r = a.call("POST", "/api/run", {"text": DEMO, "engine": "cpp"})
        self.assertEqual(code, 200)
        self.assertNotIn("error", r["cpp"])
        code, r = a.call("POST", "/api/run", {"text": DEMO.replace(".tran 0.0001 0.005", ".tran 1e-6 1"), "engine": "cpp"})
        self.assertEqual(code, 400)
        self.assertIn("limit on this server is 5000", r["error"])
        # a second .tran line counts too: the simulators use the last one
        two = DEMO.replace(".tran 0.0001 0.005", ".tran 0.0001 0.005\n.tran 1e-6 1")
        self.assertEqual(a.call("POST", "/api/run", {"text": two, "engine": "cpp"})[0], 400)

    def test_queue(self):
        big = read("rectifier.net").replace(
            ".tran 0.00002 0.12", ".tran 0.00002 0.1")
        a, b = self.signed_in("alice"), self.signed_in("bob")
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("a", a.call("POST", "/api/run", {"text": big, "engine": "python"})))
        t.start()
        time.sleep(1.0)       # alice's run holds the only worker
        self.assertEqual(a.call("POST", "/api/run", {"text": DEMO, "engine": "cpp"})[0], 429)
        self.assertEqual(b.call("POST", "/api/run", {"text": DEMO, "engine": "cpp"})[0], 503)
        t.join()
        self.assertEqual(out["a"][0], 200)

    def test_logout(self):
        a = self.signed_in()
        a.call("POST", "/api/logout", {})
        self.assertEqual(a.call("GET", "/api/circuits")[0], 401)


class Safety(unittest.TestCase):
    def test_no_public_server_without_sign_in(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "gui", "server.py"), "--host", "0.0.0.0", "--no-browser",
                            "--port", str(free_port())], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("needs sign-in", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
