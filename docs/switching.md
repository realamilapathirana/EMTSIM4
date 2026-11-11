# Switching in EMTSim: interpolation and chatter removal

EMTSim solves the network at fixed time steps Δt (Dommel's method, trapezoidal rule). Switching
does not respect that grid, which causes two separate problems. Both are described in Watson &
Arrillaga, *Power Systems Electromagnetic Transients Simulation*, section 9.4; this page says
what EMTSim does about them and where the code is.

Interpolation is on or off (`interp=on|off`). Chatter removal has four settings, described below:
`chatter=off | cda | detect | rootmatch`, default `cda` (`on` means `cda`). A circuit chooses with
an `.options` line before its elements, a run with `--chatter=... --interp=...` on the command line
(`run.bat`, `emtsim.exe`, `python main.py`, `compare.py`), and the editor has both under Run
settings. Try them on the five `circuits/demo_*.net` circuits.

## Problem 1: a switching falls between time points

A switch time, a breaker's current zero or a diode's turn-off almost never lands exactly on a
time point. With a fixed grid the change can only be applied at the next point, so it happens up
to one step late, and a current that should have been zero is chopped.

```
 true switching ─────────┐
                         ▼
 time points ──┼────────┼────────┼────────┼──   fixed grid: the switch acts here ──┐
              t        t+Δt     t+2Δt    t+3Δt                                      ▼
```

### Method: interpolate back to the switching instant

1. Take a normal step from *t* to *t*+Δt.
2. Ask every switching element where in that step it should have switched, as a fraction
   α ∈ [0, 1] of the step (`eventAlpha` / `event_alpha` in the element classes):
   - a switch or fault with a scheduled time *t*ₛ: α = (*t*ₛ − *t*) / Δt;
   - a breaker opening at a current zero: the zero crossing of its current, found by linear
     interpolation between *i*(*t*) and *i*(*t*+Δt) (or where |*i*| drops below its chopping level);
   - a diode or thyristor turning on: where its voltage crosses the forward drop, with the gate
     fired (a thyristor whose gate fires inside the step: the firing instant, by bisection);
   - a diode or thyristor turning off: the zero crossing of its current.
3. Take the earliest α. Interpolate the **whole network state** (node voltages and every element's
   currents, voltages, fluxes, machine speeds, line history samples) linearly back to that instant
   *t*ₑ = *t* + αΔt.
4. Switch the element there, rebuild and refactorise *G*, and continue from *t*ₑ.

The solution now runs on a grid shifted by *t*ₑ. The next regular step is interpolated back onto
the original grid, so the output always has the same time points as a plain run. If several
elements switch at the same instant they are switched together; a free-wheeling diode that must
take over an inductor current turns on in the first step after the switching.

```
 ──┼──────────┼─────────────┼──          step t → t+Δt, event at α
  t          te           t+Δt
   ◄── interpolate back ──┘               state(te) = (1-α) state(t) + α state(t+Δt)
             │ switch, refactorise G
             └──── continue from te; the next step is interpolated back onto the grid
```

## Problem 2: chatter

Even when a switching lands exactly on a time point, the trapezoidal rule leaves a sustained
oscillation. For an inductor the rule is

  *i*(*t*) = *i*(*t*−Δt) + (Δt / 2*L*) [*v*(*t*) + *v*(*t*−Δt)]

Open a switch in series with it: the current is forced to zero, so the bracket must be zero at
every step, i.e. *v*(*t*) = −*v*(*t*−Δt). The inductor voltage flips sign every step, forever,
around the true value (chapter 8 of the *Tiny book of EMT simulation* shows it). Capacitor
currents do the same after a voltage jump. This is numerical, not physical.

### Method: critical damping adjustment (CDA)

After every switching, the next two steps are **backward-Euler half steps** of Δt/2. Backward
Euler has no memory of the previous voltage: for the inductor

  *i*(*t*) = *i*(*t*−Δt/2) + (Δt / 2*L*) *v*(*t*)

so the oscillation cannot start. With the half step length, its conductances (Δt/2*L*, 2*C*/Δt)
are exactly the trapezoidal ones, so *G* is not rebuilt; only the history currents change (they
simply drop their voltage term). After the two half steps, trapezoidal integration resumes.

```
 ──┼──────┼──────┼─────────────┼──   te: switching
  te   te+Δt/2  te+Δt        te+2Δt   two backward-Euler half steps, then trapezoidal again,
                                       interpolated back onto the grid
```

Why both together: interpolation alone still leaves the trapezoidal rule's half-step lag after
the switching (and the chatter); chatter removal alone acts one step late. With both, a switch
closing between time points acts at its instant to the accuracy of the trapezoidal rule itself
(see `demo_interpolation.net`).

### Method: CDA where chatter is detected (`chatter=detect`)

CDA only acts where the program knows something switched. Chatter can also start without a
switching: a stiff source charging a capacitor (`demo_detect.net`), or a saturable core changing
segment (`transformer_inrush.net` chatters by ±7 kV on node 1 with plain CDA). With `detect`, after
every regular step the last four solutions are examined; if any quantity of the state (a node
voltage, a branch current, a flux, ...) changes sign from step to step three times running, with
consecutive changes nearly equal in size (within 25 %) and larger than 1 % of its peak so far, the
two backward-Euler half steps are taken there too. This is the slope check PSCAD/EMTDC uses (Watson
& Arrillaga section 9.4.1). The threshold matters: at 0.1 % it fired on tiny alternations in
`grid100.net` and the repeated half steps damped its real 1–2 kHz ringing by about 20 %; at 1 % it
fires 3 times there, at start-up, and leaves the ringing alone.

### Method: root matching with CDA (`chatter=rootmatch`)

A different idea (Watson & Arrillaga chapter 5): instead of repairing the trapezoidal rule after the
fact, give series R–L branches a difference equation that cannot chatter. Everything else (separate
`L` and `C` elements, cores, lines) keeps the trapezoidal rule and is protected as with `detect`:
the two half steps after every switching and wherever chatter is detected, as PSCAD does. The exact solution of
L di/dt + R i = v, with v held at its new value over the step, is

  *i*(*t*) = e^(−RΔt/L) *i*(*t*−Δt) + (1 − e^(−RΔt/L)) / *R* · *v*(*t*)

(the book's equation 5.2). Its history term is the current alone, so after a switching the
voltage settles at once, and the response to a step is exact at every time point, whatever Δt is.
For coupled branches (R and L matrices) the same is done with a matrix exponential:
Φ = exp(−L⁻¹RΔt) and Γ = ∫exp(−L⁻¹Rs)ds L⁻¹, i(t) = Γ v(t) + Φ i(t−Δt).

Root matching applies to every series R–L branch: `RL`, `RL3`, the series branch of `PI`/`PI3`
lines, source impedances, transformer leakage and machines. As in the book, separate `L` and `C`
elements keep the trapezoidal rule (a lone inductance has no exponential to match), so a separate R
and L only get the CDA half steps; to root-match them, draw them as one `RL` branch
(`demo_rootmatch.net`). EMTSim never merges elements by itself.

During the half steps a root-matched branch uses its root match for Δt/2 (Φ and Γ computed for
Δt/2 as well as Δt). Its conductance Γ then differs from the full-step one, unlike the trapezoidal
elements', so with `rootmatch` *G* is refactorised when the half steps start and again when they
end. With a switch closing between time points (interpolation on), an R–L branch's current then
follows the exact exponential to within 0.011 A of 10 A; with Γ for Δt in the half steps it would
be off by 0.8 A.

The price: holding v over the step delays a sinusoid by about half a step. At 50 Hz and Δt =
100 µs the current of an R–L branch is off by 1.6 % (0.49 A of 30 A, against 0.08 % with the
trapezoidal rule). So root matching is the better choice for switching and step studies with a
large time step, and the trapezoidal rule (with CDA) for steady-state accuracy.

### Choosing

| Method | Removes chatter | Cost | Use when |
|---|---|---|---|
| `off` | no | none | studying the trapezoidal rule itself (the Tiny book) |
| `cda` (default) | after switchings | two half steps per switching | most studies |
| `detect` | after switchings, and wherever it appears | a check of the state every step | non-linear cores, stiff sources, anything that chatters on its own |
| `rootmatch` | in R–L branches, always; elsewhere as `detect` | as `detect`, two more factorisations of *G* per switching, a ½-step lag on sinusoids in R–L branches | switching transients with a large time step, circuits built from R–L branches |

## Where the code is, and how to change it

| Piece | Python | C++ |
|---|---|---|
| The time loop with both methods | `switching.py` → `run_with_events()` | `src/switching.cpp` → `runWithEvents()` |
| **Interpolation method** (state between two solution points) | `switching.py` → `interpolate(x, y, al)` | `src/switching.cpp` → `interpolateState()` |
| **Chatter removal method** (steps taken after a switching) | `switching.py` → `steps_after_switching()` | `src/switching.cpp` → `stepsAfterSwitching()` |
| **Chatter detection** (`chatter=detect`, `rootmatch`) | `switching.py` → `chatter_detected(states, peak)` | `src/switching.cpp` → `chatterDetected()` |
| **Root matching** (`chatter=rootmatch`) | `elements.py` → `root_match()`, used by `RLBlock`, `TransformerCore` (`coefficients()` picks Δt or Δt/2) | `src/elements.cpp` → `rootMatch()`, `expm()` in `src/linalg.cpp`; `gain()` in `src/elements.h` |
| Where each element switches within a step | `elements.py` → `event_alpha()` of `Switch`, `Diode` | `src/elements.cpp` → `eventAlpha()` |
| Backward-Euler history currents | `elements.py`, where `config.euler` is read | `src/elements.cpp`, where `config::euler` is read |
| Saving / loading / one step / earliest event | `emtcls.py` → `save`, `load`, `solve_step`, `detect` | `src/network.cpp` → `save`, `load`, `solveStep`, `detect` |
| Plain loop (both off) | `main.py` | `src/main.cpp` |

To try another chatter-removal scheme, change `steps_after_switching()`: it returns the steps to
take after a switching as `(fraction of Δt, backward Euler?)`. `[(0.5, True), (0.5, True)]` is
CDA; `[]` is none; four half steps, or a half step followed by a trapezoidal step, are other
valid lists. The loop itself accepts any list and interpolates back onto the output grid
whatever the steps are, **but the elements only know two kinds of step**: the trapezoidal step
of Δt, `(1.0, False)`, and the backward-Euler half step of Δt/2, `(0.5, True)` — the two whose
conductances are equal, so *G* needs no rebuild (except for root-matched branches, which have
their own Δt/2 model; the loop refactorises *G* for them). Any other length or rule needs matching
changes to the elements' `stamp()` and history currents (a full backward-Euler step `(1.0, True)`
with the present elements integrates as if it were a half step and does not remove the chatter).

To try another interpolation, change `interpolate()` / `interpolateState()`. It receives the two
state vectors and the fraction; anything that returns a state vector works (the loop never looks
inside the vector). The state vector is the node voltages followed by every element's state in
element order (`save_state` / `saveState`).

To change where an element switches within a step (for example a quadratic fit of the current
zero instead of a linear one), change that element's `event_alpha()` / `eventAlpha()`.

Both ports implement the same algorithm and are compared on every example circuit by
`compare.py`; after a change, run it, the C++ tests (`build.bat`) and the three demos.

## Notes and limits

- The output grid is unchanged by either method; extra solution points are internal.
- The two solvers agree to round-off on all examples. Circuits with diodes or thyristors agree to
  about 10⁻⁴ of the peak, because the switching instant is the ratio of two small numbers.
- If valves keep switching each other at the same instant (more than 20 times with no progress in
  time), the step is solved the plain way, letting `check()` settle them, and the loop goes on.
- The book's one-step spike when a GTO opens between time points (its figure 9.5) does not occur
  in EMTSim even with interpolation off: a step is re-solved until the diodes agree with it.
- With `cda`, chatter started by something other than a switching (a stiff source, a saturable
  core) is not treated; use `detect`, or a smaller time step or a snubber.
- Root matching changes how the elements are built, so `.options` must come before the elements
  (the netlist reader says so if it does not).
