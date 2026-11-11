#pragma once

// Switching interpolation and chatter removal: the time loop used when either is on, and the
// two pieces of the method that are meant to be changed. See docs/switching.md.

#include <vector>

#include "linalg.h"

class Network;

// Interpolation: the network state at fraction al between two solution points x and y.
void interpolateState(const Vector& x, const Vector& y, double al, Vector& out);

// Chatter removal: the steps to take right after a switching, each a fraction of Dt, the integration
// rule for it and how far to interpolate back afterwards. Critical damping adjustment is two
// backward-Euler half steps; PSCAD's method is a trapezoidal step and an interpolation half a step
// back, after solving again at the switching instant with the new G (a step of length 0). The
// elements support exactly the steps {1.0, false}, {0.5, true} and {0.0, false}.
struct Step {
    double fraction;    // of Dt
    bool euler;         // backward Euler (true) or trapezoidal (false)
    double back = 0.0;  // fraction of Dt to interpolate back after the step
};
std::vector<Step> stepsAfterSwitching();
std::vector<Step> stepsWhereDetected();   // where chatter is detected (nothing switched: no step of length 0)

// Chatter detection (chatter=detect): true if some quantity of the network state alternates from step to
// step: its last three changes flip sign each time and are nearly equal in size. states: the last four
// solutions at the regular time step, oldest first; peak: the largest magnitude seen of every quantity.
bool chatterDetected(const std::vector<Vector>& states, const Vector& peak);

// The time loop with switching interpolation and chatter removal (config::interp / config::chatter)
void runWithEvents(Network& net, int maxIterations);
