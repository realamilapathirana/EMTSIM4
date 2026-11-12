# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

EMTSim is an electromagnetic transients (EMT) simulator: Dommel's nodal method with trapezoidal
companion models, in two independent implementations that must give the same answers. The Python
solver is the reference, and the C++ solver is a port of it for speed. A browser circuit editor
drives either one. The user-facing documentation is in README.md and docs/switching.md.

## Project rules

- **Keep both solvers.** Never remove or let the Python version fall behind: the user compares the
  two. Every change to the solver, the elements, the netlist format or the switching loop must be
  made in both `*.py` and `src/*`, with the same algorithm and the same order of operations.
- **Commits** are authored by the user (Amila) only. Do not add `Co-Authored-By` or other Claude
  attribution lines to commit messages. Commit only when asked. Pushing is
  `git push emtsim4 new-elements:master` (remote `emtsim4` = github.com/realamilapathirana/EMTSIM4).
- **The Tiny book** (`docs/book/`) is rebuilt only when the user asks for book changes.
- Comments are kept sparse. Docstrings and header comments state what a function computes, not
  how the code got there.

## Commands (Windows; run from the project folder)

```powershell
.\build.bat                                   # CMake + MSVC (NMake), build, then ctest. From bash: cmd //c build.bat
.\build\test_emtsim.exe | Select-String "FAIL|chatter"   # all C++ checks; filter the output to see some
.\run.bat circuits\rectifier.net --chatter=detect --interp=on   # build, run C++, plot
.venv\Scripts\python main.py circuits\rectifier.net --chatter=pscad   # Python solver
.venv\Scripts\python compare.py --netlist circuits\grid100.net --chatter=cda   # C++ vs Python
.\gui.bat                                     # editor at http://127.0.0.1:8765 (gui\server.py --port N --no-browser)
node gui\test_schematic.js                    # editor logic tests (Node.js)
python circuits\make_drawings.py              # regenerate the drawn example and demo circuits (needs Node)
python docs\book\make_book.py                 # Tiny book: figures, HTML, PDF via headless Edge
python gui\build_wasm.py                      # C++ solver -> gui\wasm\emtsim.js/.wasm (Emscripten 3.1.74 in ~\emsdk)
node tests\test_wasm.js                       # WebAssembly build vs native exe, every circuit
python gui\make_site.py --serve 8000          # static site in site\, previewed with correct MIME types
python tests\test_server.py                   # server: local mode, group sign-in/folders/limits/queue
node tests\test_web.js                        # headless Edge/Chrome: static site, local server, group server
```

- `build.bat` finds Visual Studio with vswhere. In PowerShell, call it as `cmd /c .\build.bat` from
  the project folder. The tests are one executable (`test_emtsim`) with about 70 checks; there is no
  per-test filter, so run it and filter the output.
- `make` decides by timestamp. A source file restored from a copy keeps its old timestamp and is
  not recompiled. Touch it (or all of `src/`) before rebuilding.
- The verification for any solver change: `build.bat` passes, then `compare.py --netlist <f>
  --chatter=<m>` reports "agree to within floating-point round-off" for every `circuits/*.net`
  and every method in `off cda detect rootmatch pscad`. Valve circuits with interpolation agree to
  about 1e-4 of the peak, not to round-off; `compare.py` allows that.
- Both solvers write `results.csv` (node voltages), `currents.csv` (branch currents and machine
  quantities) and `events.csv` into the project root. `plot.py` plots them.

## Architecture

### Files that mirror each other

| Python | C++ | Role |
|---|---|---|
| `main.py` | `src/main.cpp` + `src/simulation.cpp` | Command line; plain time loop or the event loop |
| `emtcls.py` (`Network`) | `src/network.cpp/.h` | Assemble G, partition U/K nodes, factorise, one step, save/load state |
| `elements.py` | `src/elements.cpp/.h` | Element models (companion models, valves, lines, machines) |
| `switching.py` | `src/switching.cpp/.h` | Event loop: interpolation and chatter removal |
| `netlist.py` | `src/netlist.cpp/.h` | Netlist reader and element builder |
| `config.py` | `src/config.h` | Δt, run length, chatter/interp settings, the step being taken |
| `dataloader.py` | `src/circuit.cpp` | Built-in circuit used when no netlist is given (kept in sync by hand) |

The linear solve differs on purpose and is not bit-identical between ports.
- **C++:** `SwitchedLDL` (`src/switched_ldl.cpp`), a sparse LDLᵀ. It orders the nodes of
  switching and non-linear elements last in a minimum-degree ordering. It keeps the ordering and
  symbolic analysis while the pattern of G_UU is unchanged, and compares the new values with the
  last ones to recompute L only from the first affected row.
- **Python:** `SwitchedLU` (`switched.py`), dense. Below 200 non-switched nodes it uses one LU,
  skipped when G_UU is unchanged. Above that it factorises the non-switched block once and
  refactorises only the Schur complement of the switched nodes.
- **Correctness of a partial refactorisation** comes from comparing G_UU with the last one, so the
  set of "switched" nodes only affects speed. For example, `rootmatch` half steps change every
  R–L entry and give a near-full refactorisation.
- `linalg.cpp` keeps the plain `SparseLDL` (used by the tests), the dense `Matrix`, `LUFactor`
  and `expm`.

### The solution step

Every element turns into a conductance stamp plus history current injections. Nodes are split into
unknown (U) and known (K, fixed by ideal sources), and each step solves
G_UU v_U = i_U − G_UK v_K. G is refactorised only when a switch, fault, valve or non-linear segment
changes (`refactor()`). Non-linear elements (diodes, thyristors, saturable inductors, surge
arresters) are piecewise linear: `check()` changes their state and the step is re-solved, up to
50 times.

### The element interface (same in both ports)

`stamp()`, `history(t)`, `update(t, v)` (commit the step), `check(t, v)` (non-linear state),
`known_terminals()/known_voltages(t)` (ideal sources), `current_names()/currents()` (output
columns), `save_state/load_state` (continuous state for interpolation), and for switching elements
`begin_step(a, b)`, `event_alpha(a, dt)` (fraction of the step where it switches) and
`apply_event(t)`.

- In Python, `save_state` is driven by the class attribute `state_vars`, a list of attribute
  paths such as `("rl.vprev", "rl.iprev")`. In C++ each class overrides `saveState/loadState`
  explicitly. The state vector is node voltages, then every element's state in element order.
  Any new state variable must be added to both, in the same order, or interpolation and
  `compare.py` break.
- `RLBlock` is the shared n-coupled series R–L branch used by `RL`, `RL3`, PI-line series
  branches, source impedances (`V`/`V3` with R and L become a source plus a `.Z` `CoupledRL`)
  and machines. `TransformerCore` has its own scalar leakage model.

### Switching, chatter and the step kinds

`run_with_events` / `runWithEvents` is used whenever chatter removal or interpolation is on.
Otherwise `main` runs the plain loop. The full description is in docs/switching.md. The parts that
cross files:

- The loop sets `config.step` (length) and `config.euler` (backward Euler) before every solve.
  Elements read them in `history`/`update`, and machines integrate with `config.step`. The
  elements support exactly three steps, all with the trapezoidal conductances, so G needs no
  rebuild: `(1.0, False)` a normal step, `(0.5, True)` a CDA backward-Euler half step, and
  `(0.0, False)` the `pscad` re-solve at the switching instant.
- Special steps are tuples `(fraction of Δt, euler, fraction to interpolate back afterwards)`
  from `steps_after_switching()` and `steps_where_detected()`. `chatter_detected()` is the
  PSCAD-style slope check, with a threshold of 1 % of each quantity's running peak.
- `chatter=rootmatch` is the exception to "G is fixed". Root-matched branches precompute Φ and Γ
  for both Δt and Δt/2 (`coefficients()` in Python, `gain()` in C++, chosen by `config.euler`),
  and the loop refactorises G when entering and leaving the half steps.
- Methods: `off`, `cda` (default), `detect`, `rootmatch`, `pscad`. `config.removal()` means
  any method except `off`, and `config.detect()` is true for `detect`, `rootmatch` and `pscad`.
  The list of methods is repeated in `config.CHATTER_METHODS`, the C++ `Chatter` enum and
  `chatterName`, `parseChatter`, `compare.py --chatter` choices, the usage strings in both
  `main`s, the editor's `<select data-optsel="chatter">` in `gui/index.html`, and the docs.

### Netlists

- The format is documented in the `netlist.py` module docstring and README "Defining a circuit".
  `TERMINALS` in `netlist.py` gives each element type's node count. `_build()` maps a line to
  element objects, and `src/netlist.cpp` mirrors it.
- `.options chatter=… interp=…` must come before the elements, because root matching is decided
  when elements are built. The reader raises an error otherwise. Command-line `--chatter/--interp`
  are "forced" settings, applied before loading and protected from `.options`.
- Most `.net` files in `circuits/` carry the editor drawing as one `#@layout {json}` comment
  line, and their netlist is generated from that drawing. Edit the generator, not the file:
  `circuits/make_drawings.py` (the drawn examples and `demo_*.net`), `make_grid100.py`,
  `make_grid1000.py` and `make_example3ph.py`. They build the netlist through
  `node gui/layout_to_net.js`, so drawing and netlist always agree.

### Circuit editor (`gui/`)

- `schematic.js` is a UMD module shared by the page and Node. It holds the component `TYPES`,
  the connectivity, `buildNetlist()` and `parseFile()`. Run settings are written as
  `.tran`/`.options`.
- `index.html` is the whole UI: palette and icons, properties panel, plots with zoom and
  "Hold run" overlay, and the single- and three-phase modes.
- `server.py` serves the page and the JSON API (listed in its docstring). It runs
  `build/emtsim.exe`, or `gui/run_python.py` for the Python engine, each in a temp folder.

### Three ways the editor works (docs/deploy.md)

The page asks `api/info` at start and sets `info.mode`. All its file and run calls go through
`listCircuits`, `readCircuit`, `save` and `run` in `index.html`, which branch on `info`.

- **Local server** (default): `server.py` on 127.0.0.1, with no sign-in. It saves into `circuits/`.
- **Group server** (`--users users.json`): `accounts.py` handles PBKDF2 passwords, in-memory
  sessions (an HttpOnly SameSite=Strict cookie) and lockout. Saves go to `<data>/<user>/`, and
  examples stay read-only. `check_limits()` reads the **last** `.tran` line, as the solvers do.
  `Queue` gives N workers, a waiting cap and wait time, and one run per user. POSTs with a foreign
  `Origin` are refused. It refuses a non-loopback `--host` or `--secure-cookies` without `--users`.
- **Static site** (`gui/make_site.py` → `site/`): no server code. It contains `circuits/index.json`
  and a static `api/info` saying `mode: static`. Saves go to localStorage. Runs use the
  WebAssembly solver only.
- **Browser engine** (`engine=wasm`, offered in every mode when `gui/wasm/` is built):
  `emtsim_worker.js` loads `wasm/emtsim.js` and calls `emtsim_run(text, chatter, interp)` from
  `src/wasm_api.cpp`. It returns the server's C++ result JSON (V and I to 7 significant digits),
  and the page stores it as `results.cpp` with `results.browser = true`. Stop terminates the worker.
- `src/simulation.cpp` `simulate()` is the one run used by `main.cpp` and `wasm_api.cpp`. A change
  to the C++ solver needs `gui/build_wasm.py` again before `tests/test_wasm.js` and the site.
  `gui/wasm/`, `site/`, `userdata/` and `users.json` are git-ignored build outputs and data.

### Adding an element type touches

`elements.py` and `src/elements.cpp/.h` (the model and its `state_vars`/`saveState`), `netlist.py`
(`TERMINALS`, `_build`, the docstring) and `src/netlist.cpp`, `gui/schematic.js` (`TYPES` and the
netlist line) and `gui/index.html` (palette entry and icon), and the README element reference. Add
a check in `tests/test_emtsim.cpp` and run `compare.py` on a circuit that uses it.

### Documentation and book

- `docs/switching.md` is the reference for interpolation and the chatter methods, including the
  measured comparisons. Keep it in step with `switching.py`.
- `docs/book/make_book.py` builds `TinyBookOfEMT.pdf`. It has its own mini solver, and its numbers
  are checked against `build/emtsim.exe`. `make_kdp.py` builds the 5×8 in KDP edition into
  `docs/book/kdp/`, and `make_docx.py` builds the Word version.
- The reference text for the switching methods is Watson & Arrillaga, *Power Systems
  Electromagnetic Transients Simulation*, section 9.4 (root matching: chapter 5). The PDF is in
  the project folder.
