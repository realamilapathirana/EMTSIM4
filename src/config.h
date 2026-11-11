#pragma once

// Simulation settings. The defaults can be changed per circuit with netlist lines
//     .tran dt tstop
//     .options chatter=off|cda|detect|rootmatch interp=on|off
// which the netlist reader applies before it builds the elements (their companion
// models depend on the time step).
//
// chatter: chatter removal method (Watson & Arrillaga, sections 9.4.1 and 5); see docs/switching.md
//          off       none
//          cda       two backward-Euler half steps after every switching (on = cda)
//          detect    cda, and also wherever an oscillation from step to step is detected
//          rootmatch detect, and series R-L branches use the exponential (root-matching) model
// interp:  interpolate to the exact instant of switching (switch times between time
//          points, breaker current zeros, diode/thyristor turn-on and turn-off)
// With both off, the solver is the plain trapezoidal-rule method.
namespace config {

constexpr double defaultDt = 100e-6;               // time step (s)
constexpr double defaultStop = 1000 * defaultDt;   // stop time (s)

inline double Dt = defaultDt;                      // time step (s)
inline double srtTime = 0.0;                       // start time (s)
inline double stpTime = srtTime + defaultStop;     // stop time (s)

enum class Chatter { Off, CDA, Detect, RootMatch };
constexpr Chatter defaultChatter = Chatter::CDA;
constexpr bool defaultInterp = true;
inline Chatter chatter = defaultChatter;           // chatter removal method
inline bool interp = defaultInterp;                // switching interpolation
inline int forcedChatter = -1, forcedInterp = -1;  // command line, wins over .options (-1: not given)

inline bool cda() { return chatter != Chatter::Off; }   // half steps after switching
inline bool detect() { return chatter == Chatter::Detect || chatter == Chatter::RootMatch; }   // and where chatter is detected
inline const char* chatterName(Chatter c) {
    return c == Chatter::Off ? "off" : c == Chatter::CDA ? "cda" : c == Chatter::Detect ? "detect" : "rootmatch";
}

// The step being taken (set by the time loop): its length, and whether it is a backward-Euler
// half step (Dt/2, same conductances as the trapezoidal rule, different history currents)
inline double step = defaultDt;
inline bool euler = false;

}  // namespace config
