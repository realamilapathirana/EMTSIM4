// The solver as a WebAssembly module for the browser editor (built by gui/build_wasm.py).
//
//   emtsim_run(netlist text, chatter, interp) -> JSON text
//
// chatter: -1 = as the netlist says, otherwise a config::Chatter value; interp: -1, 0 or 1.
// The JSON has the same fields as the server's C++ result (gui/server.py run_cpp):
// names, t, V, cnames, I, events {faults, switches}, sim_ms, or {error}. The event log
// (printf "t = ..." lines) reaches JavaScript through the module's print callback.

#include <chrono>
#include <cmath>
#include <cstdio>
#include <exception>
#include <string>

#include <emscripten/emscripten.h>

#include "config.h"
#include "elements.h"
#include "netlist.h"
#include "simulation.h"

namespace {

void str(std::string& o, const std::string& s) {
    o += '"';
    for (char c : s) {
        if (c == '"' || c == '\\') {
            o += '\\';
            o += c;
        } else if (static_cast<unsigned char>(c) < 0x20) {
            char b[8];
            std::snprintf(b, sizeof b, "\\u%04x", static_cast<unsigned char>(c));
            o += b;
        } else {
            o += c;
        }
    }
    o += '"';
}

void num(std::string& o, double x, const char* fmt) {
    char b[32];
    std::snprintf(b, sizeof b, fmt, std::isfinite(x) ? x : 0.0);
    o += b;
}

std::string error(const std::string& msg) {
    std::string o = "{\"error\":";
    str(o, msg);
    return o + "}";
}

std::string run(const char* text, int chatter, int interp) {
    config::forcedChatter = chatter;
    config::forcedInterp = interp;
    const auto start = std::chrono::steady_clock::now();
    Circuit ckt = parseNetlist(text, "circuit");
    const auto net = simulate(std::move(ckt));
    const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();

    const auto& t = net->time();
    const auto& V = net->trace();
    const auto& I = net->currentTrace();
    const std::size_t nV = V.empty() ? 0 : V[0].size(), nI = net->currentNames().size();
    for (const auto& row : V)
        for (double v : row)
            if (!std::isfinite(v))
                return error("The results are not finite: the conductance matrix is singular "
                             "(is there a floating node, or a node connected only through ideal sources?)");

    std::string o;
    o.reserve(32 + t.size() * (nV + nI + 1) * 14);
    o += "{\"names\":[";
    for (std::size_t k = 0; k < nV; ++k) o += (k ? ",\"V" : "\"V") + std::to_string(k + 1) + '"';
    o += "],\"t\":[";
    for (std::size_t s = 0; s < t.size(); ++s) {
        if (s) o += ',';
        num(o, t[s], "%.12g");
    }
    o += "],\"V\":[";
    for (std::size_t k = 0; k < nV; ++k) {
        o += k ? ",[" : "[";
        for (std::size_t s = 0; s < V.size(); ++s) {
            if (s) o += ',';
            num(o, V[s][k], "%.7g");
        }
        o += ']';
    }
    o += "],\"cnames\":[";
    for (std::size_t k = 0; k < nI; ++k) {
        if (k) o += ',';
        str(o, net->currentNames()[k]);
    }
    o += "],\"I\":[";
    for (std::size_t k = 0; k < nI; ++k) {
        o += k ? ",[" : "[";
        for (std::size_t s = 0; s < I.size(); ++s) {
            if (s) o += ',';
            num(o, I[s][k], "%.7g");
        }
        o += ']';
    }
    std::string faults, switches;
    for (const auto& e : net->elements()) {
        if (const auto* f = dynamic_cast<const Fault*>(e.get())) {
            if (!faults.empty()) faults += ',';
            faults += '[';
            num(faults, f->t_apply, "%.12g");
            faults += ',';
            if (f->t_clear) num(faults, *f->t_clear, "%.12g");
            else faults += "null";
            faults += ']';
        } else if (const auto* sw = dynamic_cast<const Switch*>(e.get())) {
            for (double ts : sw->t_switch) {
                if (!switches.empty()) switches += ',';
                num(switches, ts, "%.12g");
            }
        }
    }
    o += "],\"events\":{\"faults\":[" + faults + "],\"switches\":[" + switches + "]},\"sim_ms\":";
    num(o, ms, "%.6g");
    if (net->unconverged) {
        std::printf("Warning: non-linear elements did not settle within %d iterations in %d steps\n", MAX_ITERATIONS,
                    net->unconverged);
    }
    return o + "}";
}

std::string result;   // kept alive until the next call; JavaScript copies it at once

}  // namespace

extern "C" EMSCRIPTEN_KEEPALIVE const char* emtsim_run(const char* text, int chatter, int interp) {
    try {
        result = run(text, chatter, interp);
    } catch (const std::exception& e) {
        result = error(e.what());
    }
    std::fflush(stdout);
    return result.c_str();
}
