#pragma once

// One complete simulation run, shared by the command-line program (main.cpp) and the WebAssembly
// module for the browser (wasm_api.cpp).

#include <memory>

#include "circuit.h"
#include "network.h"

// Re-solve a step at most this many times while non-linear elements change state
constexpr int MAX_ITERATIONS = 50;

// Build the network and run the time loop: runWithEvents when chatter removal or interpolation is
// on, the plain trapezoidal loop otherwise. config must already be set (parseNetlist does that).
std::unique_ptr<Network> simulate(Circuit ckt, int maxIterations = MAX_ITERATIONS);
