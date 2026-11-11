#include <chrono>
#include <exception>
#include <iostream>

#include "circuit.h"
#include "config.h"
#include "netlist.h"
#include "network.h"
#include "simulation.h"

// Usage:  emtsim                         -> circuit in circuit.cpp
//         emtsim circuits/grid100.net    -> circuit from a netlist file
//         emtsim circuits/grid100.net --chatter=detect --interp=off
//                                        -> override the netlist's .options (chatter removal, interpolation)
int main(int argc, char** argv) {
    try {
        std::string path;
        for (int k = 1; k < argc; ++k) {
            const std::string arg = argv[k];
            const std::size_t eq = arg.find('=');
            const std::string key = arg.substr(0, eq), val = eq == std::string::npos ? "" : arg.substr(eq + 1);
            const int v = key == "--chatter" ? parseChatter(val) : key == "--interp" ? parseOnOff(val) : -1;
            if (v >= 0)
                (key == "--chatter" ? config::forcedChatter : config::forcedInterp) = v;
            else if (!arg.empty() && arg[0] == '-')
                throw std::runtime_error("usage: emtsim [netlist.net] [--chatter=off|cda|detect|rootmatch|pscad] [--interp=on|off]");
            else
                path = arg;
        }
        std::cout << "\nStart running the simulation..... \n\n";
        const auto wallStart = std::chrono::steady_clock::now();

        // Initialize the network with the circuit from a netlist file or circuit.cpp
        Circuit ckt = !path.empty() ? loadNetlist(path) : buildCircuit();
        if (config::forcedChatter >= 0) config::chatter = static_cast<config::Chatter>(config::forcedChatter);
        if (config::forcedInterp >= 0) config::interp = config::forcedInterp != 0;
        std::cout << "Chatter removal: " << config::chatterName(config::chatter) << ", switching interpolation "
                  << (config::interp ? "on" : "off") << "\n\n";
        const auto net = simulate(std::move(ckt));
        const Network& EMTDC = *net;
        const int unconverged = EMTDC.unconverged;

        // Setup + time loop, excluding writing the results
        const double simMs =
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - wallStart).count();

        EMTDC.writeResults("results.csv");
        EMTDC.writeCurrents("currents.csv");
        EMTDC.writeEvents("events.csv");
        std::cout << "\nDone: " << EMTDC.time().size() << " steps, " << EMTDC.numNodes() << " nodes";
        if (EMTDC.totalNodes() > EMTDC.numNodes())
            std::cout << " (+" << EMTDC.totalNodes() - EMTDC.numNodes() << " internal)";
        std::cout << ".\n"
                  << "Sparse LDL: G_UU has " << EMTDC.nnzG_UU() << " non-zeros, L has " << EMTDC.nnzFactor()
                  << " below the diagonal, " << EMTDC.factorisations() << " factorisations";
        if (EMTDC.resolves()) std::cout << " (" << EMTDC.resolves() << " re-solves for non-linear elements)";
        std::cout << "\n";
        if (unconverged)
            std::cout << "Warning: non-linear elements did not settle within " << MAX_ITERATIONS << " iterations in "
                      << unconverged << " steps\n";
        std::cout << "Simulation time: " << simMs << " ms\n"
                  << "Results written to results.csv, currents.csv and events.csv. Plot them with:  python plot.py\n";
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "Error: " << ex.what() << "\n";
        return 1;
    }
}
