"""Build the editor as a static web site that runs every simulation in the visitor's browser.

    python gui/build_wasm.py          (once, and after changing the C++ solver)
    python gui/make_site.py [--out site]

The folder (default site/) can be served by any web host (GitHub Pages, Netlify, nginx, ...):
no server code, no computing on the host. It holds the editor, the WebAssembly solver and the
example circuits (circuits/*.net with circuits/index.json). Visitors save circuits in their own
browser and download them as .net files. Try it on this computer with
    python gui/make_site.py --serve 8000     and open http://127.0.0.1:8000/
(python -m http.server is not enough on Windows: it serves .js files as text/plain, which
browsers refuse to run in a worker.)
"""
import argparse
import functools
import http.server
import json
import os
import shutil
import sys

GUI = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(GUI)
FILES = ["index.html", "schematic.js", "emtsim_worker.js", "wasm/emtsim.js", "wasm/emtsim.wasm"]


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                      ".wasm": "application/wasm", ".json": "application/json", ".net": "text/plain; charset=utf-8",
                      "": "application/octet-stream"}

    def log_message(self, fmt, *args):
        pass


def serve(folder, port):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=folder))
    print("Serving %s at http://127.0.0.1:%d/  (Ctrl+C to stop)" % (folder, port), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "site"))
    ap.add_argument("--serve", type=int, metavar="PORT", help="then serve the site on this computer to try it")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    if not os.path.isfile(os.path.join(GUI, "wasm", "emtsim.wasm")):
        sys.exit("Build the WebAssembly solver first:  python gui/build_wasm.py")
    if os.path.isdir(out):
        if not os.path.isfile(os.path.join(out, "emtsim_worker.js")):
            sys.exit("%s exists and is not an EMTSim site; choose another --out" % out)
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "wasm"))
    os.makedirs(os.path.join(out, "circuits"))
    for f in FILES:
        shutil.copyfile(os.path.join(GUI, f), os.path.join(out, f))
    files = []
    for n in sorted(os.listdir(os.path.join(ROOT, "circuits"))):
        if n.endswith(".net"):
            src = os.path.join(ROOT, "circuits", n)
            shutil.copyfile(src, os.path.join(out, "circuits", n))
            with open(src, encoding="utf-8") as fh:
                files.append({"name": n, "drawing": any(l.startswith("#@layout ") for l in fh)})
    with open(os.path.join(out, "circuits", "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"files": files}, fh, indent=1)
    os.makedirs(os.path.join(out, "api"))
    with open(os.path.join(out, "api", "info"), "w", encoding="utf-8") as fh:   # what the page asks a server for
        json.dump({"mode": "static", "login": False, "user": None, "engines": ["wasm"]}, fh)
    open(os.path.join(out, ".nojekyll"), "w").close()   # GitHub Pages: serve the files as they are
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(out) for f in fs)/1e6
    print("Wrote %s: %d files, %.1f MB, %d example circuits" % (out, len(FILES) + len(files) + 3, size, len(files)))
    if args.serve:
        serve(out, args.serve)


if __name__ == "__main__":
    main()
