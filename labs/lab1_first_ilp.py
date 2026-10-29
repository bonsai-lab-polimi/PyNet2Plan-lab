#!/usr/bin/env python3
"""
Lab 1 - the first ILP: the splittable flow formulation on Spain-7
=================================================================

Runs formulations/splittable_flow.py on Spain-7 with the traffic of
data/traffic/spain7_traffic_split_vs_unsplit.csv (24 demands, 229 wavelengths)
and does the experiments of the handout:

  1. one run with the same capacity C on every link (default 40)
  2. a capacity sweep, C = 30 ... 60 (every run is repeated to measure the
     mean computation time and its standard deviation)
  3. every single fiber cut (both directions of a link fail) at C = 60

Every run is also saved as CSV files in results/, so you can open it in the
GUI (Results tab > Browse...). The figures are saved in results/lab1_first_ilp/,
as PNG (for the screen) and PDF (for a report), with their data as JSON.

    python labs/lab1_first_ilp.py
    python labs/lab1_first_ilp.py --capacity 36 --failure-capacity 70
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import networkx as nx  # noqa: E402

from pynet2plan import network, plotting, runner, traffic  # noqa: E402

TOPOLOGY = os.path.join(ROOT, "data", "topologies", "spain7.json")
TRAFFIC = os.path.join(ROOT, "data", "traffic", "spain7_traffic_split_vs_unsplit.csv")


def rel(path):
    """Path relative to the project (shorter to read)."""
    try:
        r = os.path.relpath(path, ROOT)
    except ValueError:                      # another drive (Windows)
        return path
    return path if r.startswith("..") else r


def title(text):
    print("\n" + text + "\n" + "=" * len(text))


def with_capacity(G, c):
    H = G.copy()
    network.set_uniform_capacity(H, c)
    return H


def saturated(res):
    return [(l["origin"], l["destination"]) for l in res.tables["links"]
            if l.get("capacity") and l.get("used", 0) >= l["capacity"]]


def fibers(G):
    """Every pair of opposite links once: ('Madrid', 'Valencia'), ..."""
    seen = []
    for u, v in G.edges:
        if (v, u) not in seen and (u, v) not in seen:
            seen.append((u, v))
    return seen


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--capacity", type=int, default=40, help="capacity of every link (wavelengths)")
    ap.add_argument("--sweep", default="30-60", help="capacities of the sweep, e.g. 30-60 or 30-60:2")
    ap.add_argument("--failure-capacity", type=int, default=60, help="capacity for the fiber-cut experiment")
    ap.add_argument("--repetitions", type=int, default=5,
                    help="runs of every capacity of the sweep, to measure the computation time")
    ap.add_argument("--formulation", default="splittable_flow")
    ap.add_argument("--out", default=None, help="results folder (default: results/)")
    ap.add_argument("--figures", default=None, help="figures folder (default: results/lab1_first_ilp)")
    args = ap.parse_args(argv)
    figdir = args.figures or os.path.join(args.out or os.path.join(ROOT, "results"), "lab1_first_ilp")
    os.makedirs(figdir, exist_ok=True)

    G0 = network.load_topology(TOPOLOGY)
    D = traffic.load_traffic(TRAFFIC, G0)
    hops = dict(nx.shortest_path_length(G0))
    lower = sum(d.traffic * hops[d.origin][d.destination] for d in D)
    print(network.describe(G0))
    print(f"Traffic: {len(D)} demands, {traffic.total_traffic(D)} wavelengths ({os.path.basename(TRAFFIC)})")
    print(f"Lower bound (every demand on a fewest-hops path): {lower} wavelengths")

    # 1. one run --------------------------------------------------------------------------
    C = args.capacity
    title(f"1. {args.formulation}, C = {C} on every link")
    G = with_capacity(G0, C)
    res = runner.run_algorithm(G, D, args.formulation, {}, output_root=args.out,
                               topology_file=TOPOLOGY, traffic_file=TRAFFIC)
    print(f"status {res.status}, objective {res.summary.get('objective')}, "
          f"time {res.summary.get('time_s', 0):.3f} s")
    if not res.ok:
        print(res.message)
        return 1
    obj = res.summary["objective"]
    print(f"objective - lower bound = {obj:g} - {lower} = {obj - lower:g} extra wavelengths (detours)")
    print(f"saturated links: {', '.join(f'{u}->{v}' for u, v in saturated(res)) or 'none'}")
    routes = {}
    for r in res.tables["routes"]:
        routes.setdefault(r["demand_id"], []).append(r)
    extra_total = 0
    for dem in D:
        rs = routes.get(dem.id, [])
        extra = sum(r["traffic"] * (r["hops"] - hops[dem.origin][dem.destination]) for r in rs)
        extra_total += extra
        if len(rs) > 1 or extra:
            print(f"  demand {dem.id:2d} {dem.origin}->{dem.destination} ({dem.traffic} λ, fewest hops "
                  f"{hops[dem.origin][dem.destination]}):  "
                  + ";  ".join(f"{r['traffic']} λ on {r['path']}" for r in rs)
                  + (f"   -> {extra} extra" if extra else ""))
    print(f"  total extra = {extra_total}  (= objective - lower bound)")
    print(f"saved in {rel(res.folder)}")
    plotting_map(res, os.path.join(figdir, f"ilp_map_c{C}.png"), C)

    # 2. capacity sweep ---------------------------------------------------------------------
    title("2. Capacity sweep")
    caps = runner.parse_values(args.sweep)
    # every capacity is solved args.repetitions times: the time is the mean of the runs
    sw = runner.run_sweep(G0, D, [(args.formulation, {})], caps, output_root=args.out,
                          topology_file=TOPOLOGY, traffic_file=TRAFFIC, repetitions=args.repetitions)
    rows = []
    for r in sw.rows:
        ok = r["status"] in ("OPTIMAL", "FEASIBLE")
        rows.append(dict(C=r["capacity"], status=r["status"], objective=r.get("objective") if ok else None,
                         split=r.get("split_demands") if ok else None,
                         saturated=r.get("saturated_links") if ok else None,
                         time_ms=1000 * float(r["time_s"]),
                         time_std_ms=1000 * float(r["time_std_s"]) if r.get("time_std_s") not in ("", None) else None,
                         runs=r.get("time_runs")))
    print(f"{'C':>4} {'status':>11} {'objective':>9} {'split':>5} {'full links':>10} {'time ms':>16}")
    for r in rows:
        t = f"{r['time_ms']:.1f}" + (f" ± {r['time_std_ms']:.1f}" if r["time_std_ms"] is not None else "")
        print(f"{r['C']:4d} {r['status']:>11} {r['objective'] if r['objective'] is not None else '-':>9} "
              f"{r['split'] if r['split'] is not None else '-':>5} "
              f"{r['saturated'] if r['saturated'] is not None else '-':>10} {t:>16}")
    print(f"time: mean ± standard deviation of {args.repetitions} runs" if args.repetitions > 1
          else "time: one run per capacity")
    feasible = [r["C"] for r in rows if r["objective"] is not None]
    if feasible:
        at_bound = [r["C"] for r in rows if r["objective"] is not None and r["objective"] <= lower + 1e-6]
        print(f"smallest feasible capacity: C = {min(feasible)}"
              + (f";  the lower bound {lower} is reached from C = {min(at_bound)}" if at_bound else ""))
    print(f"sweep saved in {rel(sw.folder)}")
    plot_sweep_figures(rows, lower, figdir)

    # 3. fiber cuts -------------------------------------------------------------------------
    Cf = args.failure_capacity
    title(f"3. Single fiber cuts at C = {Cf}")
    base = runner.run_algorithm(with_capacity(G0, Cf), D, args.formulation, {}, save=False)
    print(f"no failure: {base.status} {base.summary.get('objective') if base.ok else ''}")
    cuts = []
    for u, v in fibers(G0):
        F = with_capacity(G0, Cf)
        network.set_link_up(F, u, v, False)
        network.set_link_up(F, v, u, False)
        r = runner.run_algorithm(F, D, args.formulation, {}, save=False)
        cuts.append((f"{u}–{v}", r.status, r.summary.get("objective") if r.ok else None))
        print(f"  cut {u + '-' + v:22s} {r.status:>11} {r.summary.get('objective') if r.ok else '':>6}")
    plot_failures(cuts, base.summary.get("objective") if base.ok else None, Cf, figdir)
    print(f"\nfigures saved in {rel(figdir)}")
    return 0


# ----------------------------------------------------------------------------------------
# figures
# ----------------------------------------------------------------------------------------
def save_data(png_path, **data):
    """The data of a figure, next to it as JSON (e.g. to draw it again with another tool)."""
    import json
    with open(os.path.splitext(png_path)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)


def map_data(run):
    """Nodes and links of a saved run, for save_data."""
    return dict(nodes=[dict(name=n, x=a["x"], y=a["y"]) for n, a in run.G.nodes(data=True)],
                links=[dict(origin=l["origin"], destination=l["destination"], used=l.get("used", 0),
                            capacity=l.get("capacity"), up=l.get("up", True)) for l in run.links])


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plotting.use_report_style()     # readable fonts, distinct markers and line styles, ...
    return plt


def save(fig, path, **data):
    """PNG and PDF of the figure, and its data as JSON."""
    for p in plotting.save_figure(fig, path):
        print(f"figure: {rel(p)}")
    save_data(path, **data)
    import matplotlib.pyplot as plt
    plt.close(fig)


def plotting_map(res, path, C):
    plt = _plt()
    from pynet2plan import results
    run = results.load_run(res.folder)
    fig, ax = plt.subplots(figsize=(7.5, 7.2))
    plotting.draw_network(ax, run.G, link_used=plotting.used_from_rows(run.links),
                          title=f"Splittable flow, C = {C}, {res.summary['objective']:g} wavelengths used")
    save(fig, path, kind="map", C=C, objective=res.summary["objective"], **map_data(run))


XLABEL = "capacity of every link, C (wavelengths)"


def plot_sweep_figures(rows, lower, figdir):
    from matplotlib.ticker import MaxNLocator
    plt = _plt()
    ok = [r for r in rows if r["objective"] is not None]
    bad = [r["C"] for r in rows if r["objective"] is None]
    gray = "#616161"
    first, second = plotting.series_style(0), plotting.series_style(1)

    fig, ax = plt.subplots(figsize=(8.5, 5))
    if bad:
        ax.axvspan(min(bad) - 0.5, max(bad) + 0.5, color="#eeeeee", zorder=0)
        ax.text((min(bad) + max(bad)) / 2, 0.5, "infeasible", transform=ax.get_xaxis_transform(),
                ha="center", va="center", color=gray)
    ax.axhline(lower, color=gray, lw=1.2, ls=(0, (4, 3)), label=f"lower bound {lower} (fewest-hop routing)")
    ax.plot([r["C"] for r in ok], [r["objective"] for r in ok], label="splittable flow, optimum", **first)
    if ok:
        top = ok[0]
        ax.annotate(f"C = {top['C']}: {top['objective']:g}", (top["C"], top["objective"]),
                    xytext=(10, 6), textcoords="offset points", color=first["color"])
    ax.set_xlabel(XLABEL)
    ax.set_ylabel("total wavelengths used, summed over the links")
    ax.set_title("Objective vs. link capacity")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, steps=[1, 2, 2.5, 5, 10]))
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, steps=[1, 2, 2.5, 5, 10]))
    ax.legend(loc="upper right")
    save(fig, os.path.join(figdir, "ilp_objective_vs_capacity.png"), kind="sweep", lower_bound=lower, rows=rows)

    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    if bad:
        ax.axvspan(min(bad) - 0.5, max(bad) + 0.5, color="#eeeeee", zorder=0)
    ax.plot([r["C"] for r in ok], [r["split"] for r in ok], label="split demands", **first)
    ax.plot([r["C"] for r in ok], [r["saturated"] for r in ok], label="full links", **second)
    ax.set_xlabel(XLABEL)
    ax.set_ylabel("number of demands or links")
    ax.set_title("Split demands and full links")
    ax.legend(loc="upper right")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, steps=[1, 2, 2.5, 5, 10]))
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, steps=[1, 2, 2.5, 5, 10]))
    save(fig, os.path.join(figdir, "ilp_split_and_full_links.png"), kind="sweep", lower_bound=lower, rows=rows)


def plot_failures(cuts, base, Cf, figdir):
    plt = _plt()
    blue, gray = plotting.SERIES_COLORS[0], "#616161"
    cuts = sorted(cuts, key=lambda c: (c[2] is None, c[2] or 0))
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    ys = list(range(len(cuts)))
    vals = [c[2] or 0 for c in cuts]
    ax.barh(ys, vals, height=0.62, color=[blue if c[2] is not None else "#e0e0e0" for c in cuts])
    for y, c in zip(ys, cuts):
        txt = f"{c[2]:g}" if c[2] is not None else "INFEASIBLE"
        ax.text((c[2] or 0) + 4, y, txt, va="center", color=gray if c[2] is None else "#263238")
    if base is not None:
        ax.axvline(base, color=gray, lw=1.2, ls=(0, (4, 3)))
        ax.text(base, -0.9, f"no failure: {base:g}", ha="center", va="bottom", color=gray)
    ax.set_yticks(ys)
    ax.set_yticklabels([f"cut {c[0]}" for c in cuts])
    ax.invert_yaxis()
    ax.set_xlim(0, max(vals + [base or 0]) * 1.18)
    ax.set_ylim(len(cuts) - 0.5, -1.5)
    ax.set_xlabel("total wavelengths used, summed over the links")
    ax.set_title(f"Single fibre cuts (both directions), C = {Cf}")
    ax.grid(axis="y", visible=False)
    save(fig, os.path.join(figdir, f"ilp_fiber_cuts_c{Cf}.png"), kind="cuts", C=Cf, no_failure=base,
         cuts=[dict(fiber=c[0], status=c[1], objective=c[2]) for c in cuts])


if __name__ == "__main__":
    sys.exit(main())
