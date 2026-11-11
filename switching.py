"""Switching interpolation and chatter removal: the time loop used when either is on, and the two
pieces of the method that are meant to be changed (interpolate, steps_after_switching,
steps_where_detected, chatter_detected).
See docs/switching.md. The same algorithm as src/switching.cpp."""
import math

import numpy as np

import config


def interpolate(x, y, al):
    """Interpolation: the network state at fraction al between two solution points x and y."""
    return x + al*(y - x)


def steps_after_switching():
    """Chatter removal: the steps to take right after a switching, each (fraction of Dt, backward
    Euler?, fraction of Dt to interpolate back afterwards). Critical damping adjustment is two
    backward-Euler half steps. PSCAD's method first solves again at the switching instant with the new
    G (a step of length 0: the solution just after the switching), then takes a trapezoidal step and
    interpolates half a step back. The elements support exactly the steps (1.0, False), (0.5, True)
    and (0.0, False); see docs/switching.md."""
    if config.chatter == "pscad":
        return [(0.0, False, 0.0), (1.0, False, 0.5)]
    return [(0.5, True, 0.0), (0.5, True, 0.0)] if config.removal() else []


def steps_where_detected():
    """Chatter removal where chatter is detected (no switching, so nothing to solve again)"""
    if config.chatter == "pscad":
        return [(1.0, False, 0.5)]
    return steps_after_switching()


def chatter_detected(states, peak):
    """Chatter detection (chatter=detect): True if some quantity of the network state alternates from
    step to step: its last three changes flip sign each time and are nearly equal in size, as chatter
    around a smooth solution does. states: the last four solutions at the regular time step, oldest
    first; peak: the largest magnitude seen so far of every quantity (to ignore round-off)."""
    d1, d2, d3 = states[1] - states[0], states[2] - states[1], states[3] - states[2]
    big = np.minimum(np.minimum(abs(d1), abs(d2)), abs(d3)) > 1e-2*peak + 1e-9
    flips = (d1*d2 < 0) & (d2*d3 < 0)
    even = (abs(d2 + d3) < 0.25*np.maximum(abs(d2), abs(d3))) & (abs(d1 + d2) < 0.25*np.maximum(abs(d1), abs(d2)))
    return bool(np.any(big & flips & even))


def run_with_events(net, max_iterations=50):
    """After every step, the earliest switching inside it is found (Network.detect, from the elements'
    event_alpha), the state is interpolated back to that instant and the element switches there. The
    steps from steps_after_switching() follow; the regular trapezoidal step after them is interpolated
    back onto the output time grid. Grid points passed during the special steps are recorded from
    the last two of them."""
    dt, t0 = config.Dt, config.srtTime
    nsteps = int(round((config.stpTime - t0)/dt))
    eps = 1e-6*dt
    a = tP = t0            # time of the present solution, and of P
    k_rec = 0
    P = net.save()         # last accepted point; S is the new one
    S = None
    pending = []           # special steps still to take after a switching
    stall = 0
    detect = config.detect()
    root = config.chatter == "rootmatch"   # root-matched branches have other conductances in the half steps
    g_euler = False        # the kind of step G was last factorised for
    recent, peak = [], abs(P)   # regular solutions for chatter detection, and the largest values seen

    def record_to(tS):     # the grid points up to tS, from P and S
        nonlocal k_rec
        while k_rec < nsteps:
            tk = t0 + (k_rec + 1)*dt
            if tk > tS + eps:
                break
            al = 1.0 if tS - tP <= 1e-12*dt else (tk - tP)/(tS - tP)
            between = abs(al - 1.0) > 1e-12
            if between:
                net.load(interpolate(P, S, al))
            net.recordv(tk)
            if between:
                net.load(S)
            k_rec += 1

    def accept(t, regular=False):
        nonlocal P, tP, a, recent, peak, pending
        record_to(t)
        P, tP, a = S, t, t
        if not detect:
            return
        if not regular:
            recent = []
            return
        recent = (recent + [S])[-4:]
        peak = np.maximum(peak, abs(S))
        if len(recent) == 4 and chatter_detected(recent, peak):
            pending, recent = list(steps_where_detected()), []

    while k_rec < nsteps:
        special = bool(pending)
        fraction, euler, back = pending[0] if special else (1.0, False, 0.0)
        h = fraction*dt
        b = a + h
        config.step, config.euler = h, euler
        if root and euler != g_euler:
            net.refactor()
            g_euler = euler
        for obj in net.events:
            obj.begin_step(a, b)
        fallback = stall > 20     # valves switching back and forth at one instant: let check() settle them
        net.solve_step(b, valves=True if fallback else "on" if special else False, max_iterations=max_iterations)
        best, hits = (None, []) if fallback or h == 0.0 else net.detect(a, h, config.interp)   # h = 0: nothing to find
        if fallback:
            stall = 0
        S = net.save()
        if best is None:
            if special:
                pending.pop(0)
                if back:           # interpolate back (pscad: to the middle of the step)
                    S = interpolate(P, S, 1.0 - back/fraction)
                    net.load(S)
                    b -= back*dt
                if pending:        # recorded after the last special step
                    P, tP, a = S, b, b
                else:
                    accept(b)
                continue
            g = t0 + math.floor((b - t0)/dt + 1e-6)*dt   # last grid point <= b
            if a + eps < g < b - eps:                     # off the grid: back onto it
                S = interpolate(P, S, (g - a)/dt)
                net.load(S)
                accept(g, regular=True)
            else:
                accept(g if abs(g - b) <= eps else b, regular=True)
            continue
        te = a + best*h           # a switching inside the step
        if best < 1.0 - 1e-12:
            S = interpolate(P, S, best)
            net.load(S)
        stall = stall + 1 if best <= 1e-9 else 0
        accept(te)
        changed = False
        for obj in hits:
            changed = obj.apply_event(te) or changed
        if changed:
            pending = list(steps_after_switching())
            config.euler = g_euler = bool(pending) and pending[0][1]
            net.refactor()
    config.step, config.euler = dt, False
