#!/usr/bin/env python3
"""
Lab 1 -- comparison of formulations on the Spain-7 network
==========================================================

Reproduces the two comparison exercises of CND Lab session #1 with the
algorithms of formulations/ (YOUR unsplittable formulation included):

1) Task #1: splittable vs. unsplittable flow formulation, for several
   uniform link capacities C (objective and computation time)

2) Route formulation (VWP) vs. flow formulation, for several C and
   k in {1, 2, 3}, plus the minimum capacity for which the route formulation
   is feasible with k = 1, 2, 3

By default Task #1 uses data/traffic/spain7_traffic_split_vs_unsplit.csv, a
matrix where splitting matters for C = 34..56, and part 2 uses
data/traffic/spain7_traffic.csv. The lab handout used
--task1 10,15,17,20,30,40,50 --rf 25,30,35 with its own data.

Every run is saved (CSV) in a sweep folder of results/, which you can open in
the GUI (Results tab > Open results folder...) to look at link occupancy,
routes, etc. The sweep charts are saved as sweep.png in the same folder.

Run from the project root:

    python labs/lab1_comparison.py                 # uses formulations/
    python labs/lab1_comparison.py --solutions     # instructor: reference solutions
    python labs/lab1_comparison.py --topology data/topologies/nsfnet14.json \\
                                   --traffic data/traffic/nsfnet14_traffic.csv \\
                                   --task1-traffic data/traffic/nsfnet14_traffic.csv --task1 20-40:4
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pynet2plan import network, plotting, runner, traffic  # noqa: E402


def table(rows, columns):
    widths = [max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns]
    print("  ".join(c.ljust(w) for c, w in zip(columns, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(w) for c, w in zip(columns, widths)))


def pretty(r):
    ok = r["status"] in ("OPTIMAL", "FEASIBLE")
    t, sd = r.get("time_s"), r.get("time_std_s")
    time_ms = "-"
    if ok and t not in ("", None):
        time_ms = f"{1000 * float(t):.1f}" + (f" ± {1000 * float(sd):.1f}" if sd not in ("", None) else "")
    return dict(C=r.get("capacity"), algorithm=plotting.series_key(r), status=r["status"],
                objective=r.get("objective") if ok else "-", time_ms=time_ms)


def warn_not_completed(rows):
    bad = [r for r in rows if r["status"] in ("NOT_COMPLETED", "ERROR")]
    if bad:
        print(f"\n  NOTE: {bad[0]['algorithm']} -> {bad[0]['status']}: {bad[0]['message']}")
        print("  Complete the TODOs of the formulation first (python -m pynet2plan check <file>).")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--topology", default=os.path.join(ROOT, "data", "topologies", "spain7.json"))
    ap.add_argument("--traffic", default=os.path.join(ROOT, "data", "traffic", "spain7_traffic.csv"),
                    help="traffic of part 2 (route vs. flow formulation)")
    ap.add_argument("--task1-traffic",
                    default=os.path.join(ROOT, "data", "traffic", "spain7_traffic_split_vs_unsplit.csv"),
                    help="traffic of Task #1 (splittable vs. unsplittable)")
    ap.add_argument("--task1", default="32,34,35,36,38,40,42,44,48,52,56,60",
                    help="capacities of Task #1 (e.g. 10,15,17,20,30,40,50 or 20-40:5)")
    ap.add_argument("--rf", default="25,28,29,30,35", help="capacities of the RF vs FF comparison")
    ap.add_argument("--solutions", action="store_true",
                    help="(instructor) use the reference solutions of the exercises of Lab 2")
    ap.add_argument("--repetitions", type=int, default=5,
                    help="runs of every case, to measure the mean computation time and its standard deviation")
    ap.add_argument("--out", default=None, help="results folder (default: results/)")
    args = ap.parse_args(argv)

    G = network.load_topology(args.topology)
    D = traffic.load_traffic(args.traffic, G)
    D1 = traffic.load_traffic(args.task1_traffic, G)
    print(network.describe(G))
    unsplittable = "solutions/unsplittable_flow" if args.solutions else "unsplittable_flow"
    route = "solutions/route_formulation_vwp" if args.solutions else "route_formulation_vwp"

    print("\n=== Task #1: splittable vs. unsplittable flow formulation ===")
    print(f"  traffic: {os.path.basename(args.task1_traffic)}: {len(D1)} demands, "
          f"{traffic.total_traffic(D1)} wavelengths")
    sw1 = runner.run_sweep(G, D1, [("splittable_flow", {}), (unsplittable, {})],
                           runner.parse_values(args.task1), output_root=args.out,
                           topology_file=args.topology, traffic_file=args.task1_traffic,
                           repetitions=args.repetitions)
    table([pretty(r) for r in sw1.rows], ["C", "algorithm", "status", "objective", "time_ms"])
    warn_not_completed(sw1.rows)
    plotting.save_run_figures(sw1.folder)
    print(f"\n  saved in {sw1.folder}")

    print("\n=== Route formulation (VWP) vs. flow formulation ===")
    print(f"  traffic: {os.path.basename(args.traffic)}: {len(D)} demands, "
          f"{traffic.total_traffic(D)} wavelengths")
    sw2 = runner.run_sweep(G, D, [("splittable_flow", {}), (route, {"k": [1, 2, 3]})],
                           runner.parse_values(args.rf), output_root=args.out,
                           topology_file=args.topology, traffic_file=args.traffic,
                           repetitions=args.repetitions)
    table([pretty(r) for r in sw2.rows], ["C", "algorithm", "status", "objective", "time_ms"])
    warn_not_completed(sw2.rows)
    plotting.save_run_figures(sw2.folder)
    print(f"\n  saved in {sw2.folder}")

    print("\n=== Minimum uniform capacity for which the route formulation is feasible ===")
    if runner.check_formulation(route).status == "NOT_COMPLETED":
        print("  Complete formulations/route_formulation_vwp.py first (Lab 2).")
        return
    for k in (1, 2, 3):
        lo, hi = 1, 200
        H = G.copy()

        def feasible(c):
            network.set_uniform_capacity(H, c)
            return runner.run_algorithm(H, D, route, {"k": k}, save=False).ok
        if not feasible(hi):
            print(f"  k={k}: not feasible even with C={hi}")
            continue
        while lo < hi:                       # feasibility is monotone in C: bisection
            mid = (lo + hi) // 2
            if feasible(mid):
                hi = mid
            else:
                lo = mid + 1
        print(f"  k={k}: minimum C = {lo}")


if __name__ == "__main__":
    main()
