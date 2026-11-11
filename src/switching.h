#pragma once

// Switching interpolation and chatter removal: the time loop used when either is on, and the
// two pieces of the method that are meant to be changed. See docs/switching.md.

#include <vector>

#include "linalg.h"

class Network;

// Interpolation: the network state at fraction al between two solution points x and y.
void interpolateState(const Vector& x, const Vector& y, double al, Vector& out);

// Chatter removal: the steps to take right after a switching, each a fraction of Dt and the
// integration rule for it. Critical damping adjustment is two backward-Euler half steps. The
// elements support exactly {1.0, false} and {0.5, true}, the two steps with equal conductances.
struct Step {
    double fraction;   // of Dt
    bool euler;        // backward Euler (true) or trapezoidal (false)
};
std::vector<Step> stepsAfterSwitching();

// Chatter detection (chatter=detect): true if some quantity of the network state alternates from step to
// step: its last three changes flip sign each time and are nearly equal in size. states: the last four
// solutions at the regular time step, oldest first; peak: the largest magnitude seen of every quantity.
bool chatterDetected(const std::vector<Vector>& states, const Vector& peak);

// The time loop with switching interpolation and chatter removal (config::interp / config::chatter)
void runWithEvents(Network& net, int maxIterations);
