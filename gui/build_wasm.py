"""Build the C++ solver as WebAssembly for the browser editor: gui/wasm/emtsim.js and emtsim.wasm.

    python gui/build_wasm.py                 needs the Emscripten SDK (emsdk)

em++ is taken from the PATH, or from the emsdk in $EMSDK or ~/emsdk (called directly, with the
emsdk's .emscripten configuration). Install it once with:
    git clone https://github.com/emscripten-core/emsdk.git ~/emsdk
    cd ~/emsdk && ./emsdk install 3.1.74 && ./emsdk activate 3.1.74      (emsdk.bat on Windows)
"""
import os
import shutil
import subprocess
import sys

GUI = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(GUI)
OUT = os.path.join(GUI, "wasm")
SOURCES = ["linalg", "elements", "network", "netlist", "switching", "simulation", "switched_ldl", "wasm_api"]
FLAGS = ["-std=c++17", "-O3", "-fwasm-exceptions",
         "-sMODULARIZE=1", "-sEXPORT_NAME=createEmtsim", "-sENVIRONMENT=web,worker,node",
         "-sALLOW_MEMORY_GROWTH=1", "-sSTACK_SIZE=1048576",
         "-sEXPORTED_FUNCTIONS=_emtsim_run", "-sEXPORTED_RUNTIME_METHODS=ccall"]


def emsdk_dir():
    for d in (os.environ.get("EMSDK"), os.path.join(os.path.expanduser("~"), "emsdk")):
        if d and os.path.isfile(os.path.join(d, "emsdk.py")):
            return d
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    args = [os.path.join(ROOT, "src", s + ".cpp") for s in SOURCES] + ["-I" + os.path.join(ROOT, "src")] + FLAGS
    args += ["-o", os.path.join(OUT, "emtsim.js")]
    env = dict(os.environ)
    empp = shutil.which("em++")
    if not empp:
        sdk = emsdk_dir()
        empp = sdk and os.path.join(sdk, "upstream", "emscripten", "em++.bat" if os.name == "nt" else "em++")
        if not empp or not os.path.isfile(empp):
            sys.exit(__doc__)
        env.setdefault("EM_CONFIG", os.path.join(sdk, ".emscripten"))
        env.setdefault("EMSDK_PYTHON", sys.executable)
    print("Building gui/wasm/emtsim.js and emtsim.wasm ...")
    r = subprocess.run([empp] + args, cwd=ROOT, env=env)
    if r.returncode:
        sys.exit("em++ failed")
    size = os.path.getsize(os.path.join(OUT, "emtsim.wasm")) / 1024
    print("Done: gui/wasm/emtsim.wasm (%.0f kB)" % size)


if __name__ == "__main__":
    main()
