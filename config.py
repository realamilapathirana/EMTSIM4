# Simulation settings. The defaults can be changed per circuit with netlist lines
#     .tran dt tstop
#     .options chatter=off|cda|detect|rootmatch interp=on|off
# which netlist.py applies before it builds the elements (their companion models
# depend on the time step).
#
# chatter: chatter removal method (Watson & Arrillaga, sections 9.4.1 and 5); see docs/switching.md
#          off       none
#          cda       two backward-Euler half steps after every switching (on = cda)
#          detect    cda, and also wherever an oscillation from step to step is detected
#          rootmatch series R-L branches use the exponential (root-matching) model
# interp:  interpolate to the exact instant of switching (switch times between time
#          points, breaker current zeros, diode/thyristor turn-on and turn-off)
# With both off, the solver is the plain trapezoidal-rule method.
defaultDt=100e-6
defaultStop=1000*defaultDt

Dt=defaultDt
srtTime=0.0
stpTime=srtTime+defaultStop

# The step being taken (set by the time loop): its length, and whether it is a backward-Euler
# half step (Dt/2, same conductances as the trapezoidal rule, different history currents)
step=Dt
euler=False

CHATTER_METHODS = ("off", "cda", "detect", "rootmatch")
defaultChatter="cda"
defaultInterp=True
chatter=defaultChatter
interp=defaultInterp
forced = {}     # set by the command line: wins over the netlist's .options (keys chatter, interp)


def cda():
    """True if the time loop takes backward-Euler half steps after a switching"""
    return chatter in ("cda", "detect")
