"""User accounts and sign-in sessions for a group EMTSim server (gui/server.py --users FILE).

The users file is JSON, {"users": {name: {"salt", "hash", "iterations"}}}, with PBKDF2-HMAC-SHA256
password hashes; it is managed with
    python gui/server.py --users users.json --add-user alice      (asks for the password)
    python gui/server.py --users users.json --remove-user alice
Sessions live in memory (a restart signs everyone out). After MAX_FAILURES wrong passwords in a
row, a user name is locked for LOCK_SECONDS.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

ITERATIONS = 310_000
MAX_FAILURES = 5
LOCK_SECONDS = 60
NAME = re.compile(r"[A-Za-z0-9_.-]{1,32}")


def _hash(password, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


class SignInError(Exception):
    pass


class Accounts:
    def __init__(self, path, session_hours=12.0):
        self.path = path
        self.session_seconds = session_hours*3600
        self._lock = threading.Lock()
        self._sessions = {}     # token -> (user, expiry)
        self._failures = {}     # user -> (count, time of the last failure)
        self.users = {}
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                self.users = json.load(f).get("users", {})

    def _write(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"users": self.users}, f, indent=1)
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def set_password(self, name, password):
        if not NAME.fullmatch(name):
            raise ValueError("A user name has 1-32 letters, digits, '_', '-' or '.'")
        if len(password) < 8:
            raise ValueError("Use a password of at least 8 characters")
        salt = secrets.token_bytes(16)
        self.users[name] = {"salt": salt.hex(), "hash": _hash(password, salt, ITERATIONS), "iterations": ITERATIONS}
        self._write()

    def remove(self, name):
        if self.users.pop(name, None) is None:
            raise ValueError("No user " + name)
        self._write()
        with self._lock:
            self._sessions = {t: s for t, s in self._sessions.items() if s[0] != name}

    def sign_in(self, name, password):
        """A new session token, or SignInError"""
        name = str(name or "")
        with self._lock:
            count, last = self._failures.get(name, (0, 0.0))
            if count >= MAX_FAILURES and time.time() - last < LOCK_SECONDS:
                raise SignInError("Too many wrong passwords: wait a minute and try again.")
        u = self.users.get(name)
        if u:
            ok = hmac.compare_digest(_hash(str(password), bytes.fromhex(u["salt"]), u["iterations"]), u["hash"])
        else:
            _hash(str(password), b"0"*16, ITERATIONS)   # take as long as for a real user
            ok = False
        with self._lock:
            if not ok:
                count = count + 1 if count < MAX_FAILURES else 1
                self._failures[name] = (count, time.time())
                raise SignInError("Wrong user name or password.")
            self._failures.pop(name, None)
            token = secrets.token_urlsafe(32)
            self._sessions[token] = (name, time.time() + self.session_seconds)
            return token

    def user(self, token):
        """The signed-in user of a session token, or None"""
        if not token:
            return None
        with self._lock:
            s = self._sessions.get(token)
            if not s:
                return None
            if time.time() > s[1] or s[0] not in self.users:
                del self._sessions[token]
                return None
            return s[0]

    def sign_out(self, token):
        with self._lock:
            self._sessions.pop(token, None)
