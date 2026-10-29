"""
pynet2plan.cli -- command line interface
=======================================

    python -m pynet2plan                       start the GUI
    python -m pynet2plan doctor                check the installation (Python, NetworkX, PuLP, solvers)
    python -m pynet2plan list                  list the algorithms in formulations/ and solutions/
    python -m pynet2plan check FILE            test a formulation on a tiny network
    python -m pynet2plan run -t TOPO -d TRAFFIC -a ALGORITHM [-p k=3 ...]
    python -m pynet2plan sweep -t TOPO -d TRAFFIC -a splittable_flow -a "route_formulation_vwp:k=1,2,3" -c 10-40:5
    python -m pynet2plan traffic -t TOPO -n 30 --min 1 --max 8 --seed 1 -o traffic.csv
    python -m pynet2plan report RESULT_FOLDER  print the report of a run
    python -m pynet2plan plot RESULT_FOLDER    save map.png / utilization.png (/ sweep.png)

ALGORITHM is a file name of formulations/ ("splittable_flow"), a path, or
"solutions/<name>" for the reference solutions.
"""

from __future__ import annotations

import argparse
import platform
import sys

from . import __version__


def _parse_param_list(items) -> dict:
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"Bad parameter '{it}': use name=value")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _parse_algorithm_spec(spec: str):
    """'route_formulation_vwp:k=1,2,3:time_limit=30' -> (name, {'k': ['1','2','3'], ...})"""
    parts = spec.split(":")
    name, grid = parts[0], {}
    for p in parts[1:]:
        if "=" not in p:
            raise SystemExit(f"Bad algorithm spec '{spec}': use name:param=v1,v2")
        k, v = p.split("=", 1)
        grid[k.strip()] = [x.strip() for x in v.split(",") if x.strip()]
    return name, grid


def _load_inputs(args):
    from . import network, traffic
    G = network.load_topology(args.topology)
    if args.traffic:
        demands = traffic.load_traffic(args.traffic, G)
    elif G.graph.get("embedded_traffic"):
        demands = traffic.demands_from_dicts(G.graph["embedded_traffic"])
    else:
        raise SystemExit("No traffic: give a traffic file with -d/--traffic.")
    return G, demands


#: first Python version for which the solver packages may not be available yet
TOO_NEW_PYTHON = (3, 15)


def cmd_doctor(args) -> int:
    print(f"PyNet2Plan {__version__}")
    print(f"Python {platform.python_version()} ({sys.executable})")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    print(f"Virtual environment: {'yes, ' + sys.prefix if in_venv else 'no (that is fine, but see the installation guide)'}")
    ok = sys.version_info >= (3, 10)
    if not ok:
        print("  PROBLEM: Python 3.10 or newer is required (3.14 recommended).")
    missing = []
    for mod in ("networkx", "matplotlib", "numpy"):
        try:
            m = __import__(mod)
            print(f"{mod} {m.__version__}")
        except ImportError:
            ok = False
            missing.append(mod)
            print(f"{mod}: NOT INSTALLED  ->  python -m pip install -r requirements.txt")
    if missing and sys.version_info >= TOO_NEW_PYTHON:
        print(f"  NOTE: Python {sys.version_info.major}.{sys.version_info.minor} may be too new: some "
              f"packages (e.g. the HiGHS solver) publish installers for a new Python only some "
              f"weeks after its release. Use Python 3.14 (see the installation guide).")
    try:
        import tkinter
        print(f"tkinter {tkinter.TkVersion} (GUI available)")
    except ImportError:
        print("tkinter: NOT AVAILABLE (the GUI cannot start; on Linux: sudo apt install python3-tk)")
    from .helpers import solver_report
    rep = solver_report()
    print(rep)
    if "PROBLEM" in rep or "No working" in rep or "not installed" in rep:
        ok = False
    print("\nEverything looks fine." if ok else "\nSome problems were found (see above).")
    return 0 if ok else 1


def cmd_list(args) -> int:
    from .loader import discover_all
    for info in discover_all(include_solutions=True):
        status = ("ERROR " if not info.ok else f"TODO {info.todo_count}" if info.todo_count else "OK    ")
        params = ", ".join(f"{k}={v!r}" for k, v in info.parameters.items())
        print(f"[{status}] {info.origin:13s} {info.filename:28s} {info.name}  ({params})")
        if not info.ok:
            print("      " + info.error.replace("\n", "\n      "))
    return 0


def cmd_check(args) -> int:
    from .runner import check_formulation
    res = check_formulation(args.file, solver=args.solver)
    from .runner import CHECK_NETWORK_HELP
    print(CHECK_NETWORK_HELP)
    print(f"\nStatus: {res.status}")
    if res.message:
        print(res.message)
    for i in res.issues:
        print(f"  {i}")
    if res.ok:
        s = res.summary
        obj = s.get("objective")
        print(f"Objective {obj if obj not in (None, '') else '- (heuristic)'}, wavelengths used "
              f"{s.get('wavelength_links')}, blocked {s.get('blocked_traffic')}, time {s.get('time_s')} s")
    return 0 if res.ok else 1


def cmd_run(args) -> int:
    from . import plotting, results, runner
    G, demands = _load_inputs(args)
    if args.capacity is not None:
        from .network import set_uniform_capacity
        set_uniform_capacity(G, args.capacity)
    res = runner.run_algorithm(G, demands, args.algorithm, _parse_param_list(args.param),
                               output_root=args.out, topology_file=args.topology,
                               traffic_file=args.traffic, solver=args.solver,
                               save=not args.no_save)
    print(results.format_report(res.summary, res.issues))
    if not res.ok and res.message:
        print("\n" + res.message)
    if res.details and args.verbose:
        print(res.details)
    elif res.details:
        print("\n(use -v to see the full traceback)")
    if res.folder:
        print(f"\nResults saved in: {res.folder}")
        if args.plot:
            for p in plotting.save_run_figures(res.folder):
                print(f"  figure: {p}")
    return 0 if res.ok else 1


def cmd_sweep(args) -> int:
    from . import runner
    from .plotting import series_key
    G, demands = _load_inputs(args)
    caps = runner.parse_values(args.capacities) if args.capacities else None
    algos = [_parse_algorithm_spec(a) for a in args.algorithm]

    def progress(done, total, text):
        if text not in ("done", "cancelled"):
            print(f"[{done + 1}/{total}] {text}", flush=True)

    sw = runner.run_sweep(G, demands, algos, caps, output_root=args.out,
                          topology_file=args.topology, traffic_file=args.traffic,
                          solver=args.solver, progress=progress, repetitions=args.repetitions)
    print()
    print(f"{'algorithm':50s} {'C':>5s} {'status':>13s} {'λ used':>8s} {'blocked':>8s} "
          f"{'time ms (mean ± std)':>22s}")
    for r in sw.rows:
        t, sd = r.get("time_s"), r.get("time_std_s")
        ok = r.get("status") in ("OPTIMAL", "FEASIBLE", "BLOCKING", "INVALID")
        tt = "-" if t in ("", None) else f"{1000 * float(t):.1f}" + (
            f" ± {1000 * float(sd):.1f} ({r.get('time_runs')} runs)" if sd not in ("", None) else "")
        print(f"{series_key(r)[:50]:50s} {str(r.get('capacity', '')):>5s} {r.get('status', ''):>13s} "
              f"{str(r.get('wavelength_links', '') if ok else '-'):>8s} "
              f"{str(r.get('blocked_traffic', '') if ok else '-'):>8s} {tt:>22s}")
    bad = [r for r in sw.rows if r.get("status") in ("NOT_COMPLETED", "ERROR")]
    if bad:
        print(f"\n{bad[0].get('algorithm')}: {bad[0].get('status')} - {bad[0].get('message')}")
    print(f"\nSweep saved in: {sw.folder}")
    if args.plot and sw.folder:
        from .plotting import save_run_figures
        for p in save_run_figures(sw.folder):
            print(f"  figure: {p}")
    return 0


def cmd_traffic(args) -> int:
    from . import network, traffic
    G = network.load_topology(args.topology)
    if args.full_mesh:
        demands = traffic.full_mesh_traffic(G, args.min, args.max, seed=args.seed)
        comment = traffic.generation_comment("full_mesh_traffic", min_traffic=args.min,
                                             max_traffic=args.max, seed=args.seed)
    else:
        demands = traffic.random_traffic(G, args.num, args.min, args.max, seed=args.seed,
                                         allow_duplicate_pairs=args.duplicates)
        comment = traffic.generation_comment("random_traffic", num_demands=args.num,
                                             min_traffic=args.min, max_traffic=args.max,
                                             seed=args.seed, allow_duplicate_pairs=args.duplicates)
    traffic.save_traffic(demands, args.out, layout="matrix" if args.matrix else "list",
                         nodes=list(G.nodes) if args.matrix else None,
                         comments=[f"topology: {G.graph.get('name', '')}", comment])
    print(f"{len(demands)} demands, {traffic.total_traffic(demands)} wavelengths -> {args.out}")
    return 0


def cmd_report(args) -> int:
    from . import results
    if results.is_sweep_folder(args.folder):
        sw = results.load_sweep(args.folder)
        for r in sw.rows:
            print(f"{r.get('algorithm')} [{r.get('parameters')}] C={r.get('capacity')}: "
                  f"{r.get('status')} {r.get('wavelength_links', '')}")
        return 0
    run = results.load_run(args.folder)
    print(run.report)
    return 0


def cmd_plot(args) -> int:
    from .plotting import save_run_figures
    for p in save_run_figures(args.folder):
        print(p)
    return 0


def build_parser() -> argparse.ArgumentParser:
    examples = __doc__.split("=======================================")[1]
    ap = argparse.ArgumentParser(prog="python -m pynet2plan",
                                 description="PyNet2Plan - command line interface "
                                             "(without a command: start the GUI)",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="examples:" + examples)
    ap.add_argument("--version", action="version", version=f"PyNet2Plan {__version__}")
    sub = ap.add_subparsers(dest="command")

    sub.add_parser("gui", help="start the graphical interface")
    sub.add_parser("doctor", help="check the installation")
    sub.add_parser("list", help="list the available algorithms")

    p = sub.add_parser("check", help="test a formulation on a tiny built-in network")
    p.add_argument("file")
    p.add_argument("--solver", default=None, help="auto | cbc | highs")

    def common(p):
        p.add_argument("-t", "--topology", required=True, help="topology file (.json / .graphml)")
        p.add_argument("-d", "--traffic", help="traffic file (.csv, demand list or matrix)")
        p.add_argument("-o", "--out", default=None, help="results folder (default: results/)")
        p.add_argument("--solver", default=None, help="auto | cbc | highs")
        p.add_argument("--plot", action="store_true", help="also save PNG figures")

    p = sub.add_parser("run", help="run one algorithm and save the results")
    common(p)
    p.add_argument("-a", "--algorithm", required=True)
    p.add_argument("-p", "--param", action="append", help="algorithm parameter name=value")
    p.add_argument("-c", "--capacity", type=int, default=None, help="set a uniform link capacity")
    p.add_argument("--no-save", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true", help="print full tracebacks")

    p = sub.add_parser("sweep", help="compare algorithms over several link capacities")
    common(p)
    p.add_argument("-a", "--algorithm", action="append", required=True,
                   help="name[:param=v1,v2[:param2=...]] (repeat for several algorithms)")
    p.add_argument("-c", "--capacities", default=None, help="e.g. 10,15,20 or 10-40:5")
    p.add_argument("-r", "--repetitions", type=int, default=5,
                   help="runs of every configuration, to measure the mean computation time "
                        "and its standard deviation (default 5)")

    p = sub.add_parser("traffic", help="generate a random traffic matrix")
    p.add_argument("-t", "--topology", required=True)
    p.add_argument("-n", "--num", type=int, default=20, help="number of demands")
    p.add_argument("--min", type=int, default=1)
    p.add_argument("--max", type=int, default=8)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--duplicates", action="store_true", help="allow repeated node pairs")
    p.add_argument("--full-mesh", action="store_true", help="one demand per node pair")
    p.add_argument("--matrix", action="store_true", help="save as N x N matrix")
    p.add_argument("-o", "--out", required=True)

    p = sub.add_parser("report", help="print the report of a result folder")
    p.add_argument("folder")
    p = sub.add_parser("plot", help="save figures of a result folder")
    p.add_argument("folder")
    return ap


def _safe_console():
    """Never crash on characters like 'λ' or '→' in a console that cannot show them
    (e.g. a Windows console with a legacy code page, or output redirected to a file)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None) -> int:
    _safe_console()
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.command in (None, "gui"):
        from .gui import main as gui_main
        gui_main()
        return 0
    handlers = dict(doctor=cmd_doctor, list=cmd_list, check=cmd_check, run=cmd_run,
                    sweep=cmd_sweep, traffic=cmd_traffic, report=cmd_report, plot=cmd_plot)
    from .errors import PyNet2PlanError
    try:
        return handlers[args.command](args)
    except PyNet2PlanError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
