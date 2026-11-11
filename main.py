import sys
import emtcls
import config
import elements as el
import dataloader as dl
from switching import run_with_events


# Re-solve a step at most this many times while non-linear elements change state
MAX_ITERATIONS = 50


def run(netlist_path=None, chatter=None, interp=None):
    """chatter: off / cda / detect / rootmatch (True = cda, False = off); interp: True or False.
    Both override the netlist's .options line (None: keep it)."""
    print("\nStart running the simulation..... \n")
    Time=config.srtTime
    if chatter is True or chatter is False:
        chatter = "cda" if chatter else "off"
    config.forced = {k: v for k, v in (("chatter", chatter), ("interp", interp)) if v is not None}
    #Use a netlist file if given, otherwise the circuit in dataloader.py
    if netlist_path:
        import netlist
        dl.elemet_list = netlist.load(netlist_path)
    for k, v in config.forced.items():
        setattr(config, k, v)
    config.forced = {}
    print("Chatter removal: %s, switching interpolation %s\n" % (config.chatter, "on" if config.interp else "off"))
    EMTDC=emtcls.Network()
    EMTDC.updateSwitches(Time)      # initial switch/fault states
    EMTDC.refactor()

    if config.cda() or config.interp:
        run_with_events(EMTDC, MAX_ITERATIONS)
    else:
        # plain trapezoidal loop; half a step of tolerance because Time accumulates round-off
        while Time < config.stpTime - 0.5*config.Dt:
            Time += config.Dt
            if EMTDC.updateSwitches(Time):
                EMTDC.refactor()
            EMTDC.solve_step(Time, valves=True, max_iterations=MAX_ITERATIONS)
            EMTDC.recordv(Time)
    finish(EMTDC)


def finish(EMTDC):
    if EMTDC.unconverged:
        print("Warning: non-linear elements did not settle within %d iterations in %d steps"
              % (MAX_ITERATIONS, EMTDC.unconverged))
    EMTDC.plotv()


if __name__ == "__main__":
    # python main.py                       -> circuit in dataloader.py
    # python main.py circuits/grid100.net  -> circuit from a netlist file
    # python main.py circuits/grid100.net --chatter=detect --interp=off
    #                                      -> override the netlist's .options (chatter removal, interpolation)
    from netlist import parse_chatter, parse_on_off
    path, opts = None, {}
    for arg in sys.argv[1:]:
        key, _, val = arg.partition("=")
        v = parse_chatter(val) if key == "--chatter" else parse_on_off(val) if key == "--interp" else None
        if v is not None:
            opts[key[2:]] = v
        elif arg.startswith("-"):
            raise SystemExit("usage: python main.py [netlist.net] [--chatter=off|cda|detect|rootmatch] [--interp=on|off]")
        else:
            path = arg
    run(path, **opts)
