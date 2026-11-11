#include "simulation.h"

#include "config.h"
#include "switching.h"

std::unique_ptr<Network> simulate(Circuit ckt, int maxIterations) {
    auto net = std::make_unique<Network>(std::move(ckt.elements), ckt.userNodes);
    double t = config::srtTime;
    net->updateSwitches(t);   // initial switch/fault states
    net->refactor();
    if (config::removal() || config::interp) {
        runWithEvents(*net, maxIterations);
    } else {
        // plain trapezoidal loop; half a step of tolerance because t accumulates round-off
        while (t < config::stpTime - 0.5 * config::Dt) {
            t += config::Dt;
            if (net->updateSwitches(t)) net->refactor();
            net->solveStep(t, Network::AllValves, maxIterations);
            net->recordv(t);
        }
    }
    return net;
}
