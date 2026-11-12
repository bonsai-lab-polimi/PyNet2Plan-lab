"""
Command line of the EON part (registered by :mod:`pynet2plan.cli`)::

    python -m pynet2plan eon [-t TOPO] [-d TRAFFIC]   the EON window
    python -m pynet2plan eon-list                     EON algorithms (formulations/eon, solutions/eon)
    python -m pynet2plan eon-check ALGORITHM          run it on the small EON test network
    python -m pynet2plan eon-run -t data/topologies/eon6.json -d data/traffic_eon/eon6_traffic.csv -a rsa_greedy
    python -m pynet2plan eon-sweep -t ... -d ... -a rsa_greedy -a solutions/rsa_3r --axis num_demands --values 40-240:40
    python -m pynet2plan eon-protection -t ... -d ... --protected rsa_1plus1_ilp
    python -m pynet2plan eon-traffic -t TOPO -n 120 --seed 42 -o traffic.csv
    python -m pynet2plan eon-cost --rate 1200 --span 200 --max-km 3000
    python -m pynet2plan eon-report FOLDER  /  eon-plot FOLDER
"""

from __future__ import annotations

import sys


def _table(args):
    from . import transponders as tpm
    t = tpm.load_table(getattr(args, "transponders", None), slot_width=args.slot_width)
    if getattr(args, "reach_scale", 1.0) not in (None, 1.0):
        t = tpm.scale_reach(t, args.reach_scale)
    return t


def _values(axis, text):
    from ..runner import parse_values
    from ..errors import PyNet2PlanError
    if axis == "none" or not text:
        return []
    try:
        if axis == "reach_scale":
            return [float(x) for x in str(text).split(",") if x.strip()]
        return parse_values(text)
    except ValueError:
        raise PyNet2PlanError(f"--values '{text}': give numbers, e.g. 40-240:40 (num_demands, num_slots) "
                             f"or 0.5,1,2 (reach_scale).") from None


def cmd_eon(args) -> int:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        raise SystemExit("Tkinter is not available in this Python installation, so the EON window "
                         "cannot start.\nOn Linux install it with: sudo apt install python3-tk\n"
                         "(the eon-* commands still work: python -m pynet2plan --help)")
    from ..gui.eon_app import main as eon_main
    eon_main(topology=args.topology, traffic=args.traffic)
    return 0


def cmd_eon_list(args) -> int:
    from . import runner
    for info in runner.discover():
        flags = [f for f, on in (("1+1", getattr(info, "protection", False)),
                                 ("3R", getattr(info, "regeneration", False))) if on]
        print(f"{info.origin + '/eon/' + info.filename:40s} {info.label() if info.ok else info.error.splitlines()[0]}"
              + (f"   [{', '.join(flags)}]" if flags else ""))
    return 0


def cmd_eon_check(args) -> int:
    from . import runner
    res = runner.check_formulation(args.algorithm)
    print(runner.CHECK_NETWORK_HELP + "\n")
    print(f"Status: {res.status}\n{res.message}")
    for i in res.issues:
        print(f"  {i}")
    return 0 if res.ok else 1


def cmd_eon_run(args) -> int:
    from ..cli import _load_inputs, _parse_param_list
    from . import plotting, results, runner
    G, demands = _load_inputs(args)
    res = runner.run_eon(G, demands, args.algorithm, _parse_param_list(args.param), table=_table(args),
                         num_slots=args.slots, slot_width=args.slot_width, output_root=args.out,
                         topology_file=args.topology, traffic_file=args.traffic,
                         transponders_file=args.transponders, save=not args.no_save)
    print(results.format_report(res.summary, res.issues))
    if not res.ok and res.message:
        print("\n" + res.message)
    if res.details:
        print(res.details if args.verbose else "\n(use -v to see the full traceback)")
    if res.folder:
        print(f"\nResults saved in: {res.folder}")
        if args.plot:
            for p in plotting.save_run_figures(res.folder):
                print(f"  figure: {p}")
    return 0 if res.ok else 1


def cmd_eon_sweep(args) -> int:
    from ..cli import _load_inputs, _parse_algorithm_spec
    from . import plotting, runner
    G, demands = _load_inputs(args)

    def progress(done, total, text):
        if text not in ("done", "cancelled"):
            print(f"[{done + 1}/{total}] {text}", flush=True)

    sw = runner.run_eon_sweep(G, demands, [_parse_algorithm_spec(a) for a in args.algorithm], args.axis,
                              _values(args.axis, args.values), table=_table(args), num_slots=args.slots,
                              slot_width=args.slot_width, output_root=args.out,
                              topology_file=args.topology, traffic_file=args.traffic,
                              transponders_file=args.transponders, progress=progress,
                              max_cost=args.max_cost)
    print()
    print(f"{'algorithm':42s} {args.axis:>12s} {'status':>9s} {'served':>8s} {'slots':>7s} {'3R':>4s} "
          f"{'hw cost':>8s}")
    for r in sw.rows:
        ok = r.get("status") in ("FEASIBLE", "BLOCKING", "INVALID")
        print(f"{plotting.series_key(r)[:42]:42s} {str(r.get('sweep_value', '')):>12s} {r.get('status', ''):>9s} "
              f"{(str(r.get('served_demands')) + '/' + str(r.get('num_demands'))) if ok else '-':>8s} "
              f"{str(r.get('total_slots_used', '-')) if ok else '-':>7s} {str(r.get('regenerators', '-')) if ok else '-':>4s} "
              f"{str(r.get('hardware_cost', '-')) if ok else '-':>8s}")
    bad = [r for r in sw.rows if r.get("status") in ("NOT_COMPLETED", "ERROR")]
    if bad:
        print(f"\n{bad[0].get('algorithm')}: {bad[0].get('status')} - {bad[0].get('message')}")
    print(f"\nSweep saved in: {sw.folder}")
    if args.plot and sw.folder:
        for p in plotting.save_run_figures(sw.folder):
            print(f"  figure: {p}")
    return 0 if any(r.get("status") in ("FEASIBLE", "BLOCKING") for r in sw.rows) else 1


def cmd_eon_protection(args) -> int:
    from ..cli import _load_inputs
    from . import runner
    G, demands = _load_inputs(args)
    c = runner.protection_comparison(G, demands, args.unprotected, args.protected, table=_table(args),
                                     num_slots=args.slots, slot_width=args.slot_width)
    print(runner.format_protection_comparison(c))
    return 1 if c.get("message") else 0


def cmd_eon_traffic(args) -> int:
    from .. import network, traffic
    from . import transponders as tpm
    from .traffic import full_mesh_eon_traffic, generation_comment, random_eon_traffic
    G = network.load_topology(args.topology)
    rates = [int(x) for x in args.rates.split(",")] if args.rates else tpm.rates(tpm.load_table())
    if args.full_mesh:
        demands = full_mesh_eon_traffic(G, rates, seed=args.seed)
        comment = generation_comment("full_mesh_eon_traffic", rates=rates, seed=args.seed)
    else:
        demands = random_eon_traffic(G, args.num, rates, seed=args.seed,
                                     allow_duplicate_pairs=not args.no_duplicates)
        comment = generation_comment("random_eon_traffic", num_demands=args.num, rates=rates,
                                     seed=args.seed, allow_duplicate_pairs=not args.no_duplicates)
    traffic.save_traffic(demands, args.out, comments=[f"EON traffic (Gb/s) for {G.graph.get('name', '')}",
                                                      comment])
    print(f"{len(demands)} demands, {traffic.total_traffic(demands)} Gb/s -> {args.out}")
    return 0


def cmd_eon_cost(args) -> int:
    from ..errors import PyNet2PlanError
    from . import analysis
    if args.rate <= 0:
        raise PyNet2PlanError("--rate must be a positive number of Gb/s.")
    if args.span <= 0 or args.max_km < args.span:
        raise PyNet2PlanError("--span must be positive and not larger than --max-km.")
    rows = analysis.chain_comparison(_table(args), args.rate, range(args.span, args.max_km + 1, args.span),
                                     span=args.span)
    print(f"{args.rate} Gb/s over a chain with a node every {args.span} km "
          f"(hardware: 1 per transponder, 3R = 2 transponders)\n")
    print(f"{'km':>6s}  {'long reach, no 3R':30s} {'fast types + 3R':32s} {'+hw':>5s} {'-slots':>7s} {'break-even':>10s}")
    for r in rows:
        be = r["break_even"]
        fast = f"{r['with_3r']} ({r['regenerators']} 3R)"
        extra = "" if r["extra_hw_3r"] is None else format(r["extra_hw_3r"], "g")
        saved = "" if r["slots_saved_3r"] is None else str(r["slots_saved_3r"])
        print(f"{r['km']:>6g}  {r['long_reach'][:30]:30s} {fast[:32]:32s} {extra:>5s} {saved:>7s} "
              f"{'-' if be is None else format(be, '.3g'):>10s}  {r['verdict']}")
    return 0


def cmd_eon_report(args) -> int:
    from . import results
    if results.is_eon_sweep_folder(args.folder):
        from .plotting import series_key
        for r in results.load_sweep(args.folder).rows:
            print(f"{series_key(r)} {r.get('sweep_axis')}={r.get('sweep_value')}: {r.get('status')} "
                  f"served {r.get('served_demands')}/{r.get('num_demands')} slots {r.get('total_slots_used')}")
        return 0
    print(results.load_run(args.folder).report)
    return 0


def cmd_eon_plot(args) -> int:
    from .plotting import save_run_figures
    for p in save_run_figures(args.folder):
        print(p)
    return 0


def add_parsers(sub) -> None:
    from . import runner
    from .transponders import DEFAULT_NUM_SLOTS, DEFAULT_SLOT_WIDTH

    def spectrum(p):
        p.add_argument("--slots", type=int, default=DEFAULT_NUM_SLOTS, help="slots per link (default 320)")
        p.add_argument("--slot-width", type=float, default=DEFAULT_SLOT_WIDTH, help="GHz per slot (12.5)")
        p.add_argument("--transponders", default=None, help="transponder table CSV (default: the slide)")
        p.add_argument("--reach-scale", type=float, default=1.0, help="multiply every reach (e.g. 0.5)")

    def common(p):
        p.add_argument("-t", "--topology", required=True, help="topology file")
        p.add_argument("-d", "--traffic", help="traffic file (Gb/s)")
        p.add_argument("-o", "--out", default=None, help="results folder (default: results/eon/)")
        p.add_argument("--plot", action="store_true", help="also save PNG figures")
        spectrum(p)

    p = sub.add_parser("eon", help="EON: the elastic optical network window (RSA, 1+1, 3R)")
    p.add_argument("-t", "--topology", default=None)
    p.add_argument("-d", "--traffic", default=None)
    sub.add_parser("eon-list", help="EON: list the EON algorithms")
    p = sub.add_parser("eon-check", help="EON: test an EON algorithm on a small network")
    p.add_argument("algorithm")
    p = sub.add_parser("eon-run", help="EON: run one EON algorithm and save the results")
    common(p)
    p.add_argument("-a", "--algorithm", required=True)
    p.add_argument("-p", "--param", action="append", help="algorithm parameter name=value")
    p.add_argument("--no-save", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("eon-sweep", help="EON: compare EON algorithms over a load / spectrum / reach axis")
    common(p)
    p.add_argument("-a", "--algorithm", action="append", required=True, help="name[:param=v1,v2]")
    p.add_argument("--axis", default="none", choices=list(runner.SWEEP_AXES))
    p.add_argument("--values", default="", help="e.g. 40-240:40 (num_demands, num_slots) or 0.5,1 (reach_scale)")
    p.add_argument("--max-cost", type=float, default=None,
                   help="budget on the transponder cost of every plan (3R included, 2 each)")
    p = sub.add_parser("eon-protection", help="EON: no protection vs 1+1 on the same demands (fair comparison)")
    common(p)
    p.add_argument("--unprotected", default="rsa_greedy")
    p.add_argument("--protected", default="rsa_1plus1_two_step", help="e.g. rsa_1plus1_ilp")
    p = sub.add_parser("eon-traffic", help="EON: random demands in Gb/s")
    p.add_argument("-t", "--topology", required=True)
    p.add_argument("-n", "--num", type=int, default=60)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--rates", default=None, help="e.g. 100,400 (default: the rates of the table)")
    p.add_argument("--no-duplicates", action="store_true", help="at most one demand per node pair")
    p.add_argument("--full-mesh", action="store_true", help="one demand per ordered node pair")
    p.add_argument("-o", "--out", required=True)
    p = sub.add_parser("eon-cost", help="EON: long reach or 3R? cost comparison on a chain")
    p.add_argument("--rate", type=int, default=1200)
    p.add_argument("--span", type=int, default=200, help="km between two nodes")
    p.add_argument("--max-km", type=int, default=3000)
    spectrum(p)
    p = sub.add_parser("eon-report", help="EON: print the report of a result folder")
    p.add_argument("folder")
    p = sub.add_parser("eon-plot", help="EON: save figures of a result folder")
    p.add_argument("folder")


def _friendly(handler):
    """An eon-* command: a bad option value or a file that cannot be written is an error message,
    not a traceback; Ctrl-C says where the program was (often a loop that never ends)."""
    def run(args):
        try:
            return handler(args)
        except (ValueError, OSError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        except KeyboardInterrupt as e:
            from .runner import interrupted_message
            print("\n" + interrupted_message(e), file=sys.stderr)
            return 130
    return run


HANDLERS = {name: _friendly(h) for name, h in {
    "eon": cmd_eon, "eon-list": cmd_eon_list, "eon-check": cmd_eon_check, "eon-run": cmd_eon_run,
    "eon-sweep": cmd_eon_sweep, "eon-protection": cmd_eon_protection, "eon-traffic": cmd_eon_traffic,
    "eon-cost": cmd_eon_cost, "eon-report": cmd_eon_report, "eon-plot": cmd_eon_plot}.items()}

