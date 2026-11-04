#!/usr/bin/env python3
"""
Lab 2 - the route formulation, compared with the flow formulation
=================================================================

Run it after completing formulations/route_formulation_vwp.py (its five TODOs):

  1. checks the formulation on the small test network of PyNet2Plan
  2. Spain-7 with C = 40 on every link: the flow formulation and the route
     formulation with k = 1, 2, 3 candidate paths per demand
  3. COST239: optimal objective as a function of the capacity, for several k
  4. a larger network (GEANT2, 35 nodes): size of the two models and
     computation times, as the mean and the standard deviation of several runs

The figures are saved in results/lab2_route_formulation/ (PNG and PDF, with
their data as JSON).

    python labs/lab2_route_formulation.py
    python labs/lab2_route_formulation.py --skip-large --repetitions 3
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pynet2plan import network, plotting, runner, traffic  # noqa: E402

TOPOLOGY = os.path.join(ROOT, "data", "topologies", "spain7.json")
TRAFFIC = os.path.join(ROOT, "data", "traffic", "spain7_traffic_split_vs_unsplit.csv")
MEDIUM = "cost239"
MEDIUM_TOPOLOGY = os.path.join(ROOT, "data", "topologies", f"{MEDIUM}.json")
MEDIUM_TRAFFIC = os.path.join(ROOT, "data", "traffic", f"{MEDIUM}_traffic.csv")
LARGE = "top22_geant2"
LARGE_TOPOLOGY = os.path.join(ROOT, "data", "topologies", "real", f"{LARGE}.json")
LARGE_TRAFFIC = os.path.join(ROOT, "data", "traffic", "real", f"{LARGE}_traffic.csv")
FLOW = "splittable_flow"


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


def num(v):
    """A number as printed in the tables: 422 rather than 422.00000000000006."""
    return "-" if v is None else f"{round(float(v), 6):g}"


def objective(res):
    return res.summary.get("objective") if res.ok else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--formulation", default=os.path.join(ROOT, "formulations", "route_formulation_vwp.py"),
                    help="the route formulation to test (default: your exercise file)")
    ap.add_argument("--capacity", type=int, default=40, help="capacity of every link in part 2")
    ap.add_argument("--medium-sweep", default="6-15", help="capacities of part 3 (COST239)")
    ap.add_argument("--medium-k", default="1,2,3,4", help="values of k of part 3")
    ap.add_argument("--large-sweep", default="18,20,22,24", help="capacities of part 4 (GEANT2)")
    ap.add_argument("--large-k", default="3,5,8", help="values of k of part 4")
    ap.add_argument("--skip-large", action="store_true", help="skip part 4")
    ap.add_argument("--repetitions", type=int, default=5, help="runs of every case of part 4")
    ap.add_argument("--out", default=None, help="results folder (default: results/)")
    ap.add_argument("--figures", default=None, help="figures folder (default: results/lab2_route_formulation)")
    args = ap.parse_args(argv)
    figdir = args.figures or os.path.join(args.out or os.path.join(ROOT, "results"), "lab2_route_formulation")
    os.makedirs(figdir, exist_ok=True)
    ROUTE = args.formulation
    shown = rel(ROUTE) if os.path.isfile(ROUTE) else ROUTE

    # 1. check ------------------------------------------------------------------------------
    title("1. Check of the formulation")
    print(f"file: {shown}")
    chk = runner.check_formulation(ROUTE)
    print(f"test network: status {chk.status}, objective {num(chk.summary.get('objective'))}")
    if not chk.ok:
        print("\n" + chk.message.strip())
        print("\nComplete the formulation (see the message above), then run this script again.")
        return 1
    if abs(float(chk.summary["objective"]) - 20) > 1e-6:
        print("Warning: on the test network the optimum of the route formulation is 20, as for the "
              "flow formulation. Check the objective function.")
    else:
        print("expected 20 (as the splittable flow formulation): ok")

    # 2. Spain-7 ----------------------------------------------------------------------------
    C = args.capacity
    title(f"2. Spain-7, C = {C} on every link")
    G0 = network.load_topology(TOPOLOGY)
    D = traffic.load_traffic(TRAFFIC, G0)
    print(f"{len(D)} demands, {traffic.total_traffic(D)} wavelengths ({os.path.basename(TRAFFIC)})")
    G = with_capacity(G0, C)
    cases = [("flow formulation", FLOW, {})] + [(f"route, k = {k}", ROUTE, {"k": k}) for k in (1, 2, 3)]
    print(f"{'':18s} {'status':>10s} {'objective':>9s} {'variables':>9s} {'constraints':>11s} {'split':>5s}")
    for label, name, params in cases:
        r = runner.run_algorithm(G, D, name, params, save=False)
        s = r.summary
        print(f"{label:18s} {r.status:>10s} {num(objective(r)):>9s} {s.get('num_variables', ''):>9} "
              f"{s.get('num_constraints', ''):>11} {s.get('split_demands', '-') if r.ok else '-':>5}")
    print(f"route formulation: |D| x k variables ({len(D)} x k) and |D| + |E| constraints "
          f"({len(D)} + {G.number_of_edges()}); flow formulation: |D| x |E| variables "
          f"({len(D)} x {G.number_of_edges()}) and |D| x |N| + |E| constraints "
          f"({len(D)} x {G.number_of_nodes()} + {G.number_of_edges()})")

    # 3. COST239: objective and k ------------------------------------------------------------
    title("3. COST239: optimal objective for several k")
    GM = network.load_topology(MEDIUM_TOPOLOGY)
    DM = traffic.load_traffic(MEDIUM_TRAFFIC, GM)
    print(f"{GM.graph['name']}: {GM.number_of_nodes()} nodes, {GM.number_of_edges()} links, "
          f"{len(DM)} demands, {traffic.total_traffic(DM)} wavelengths")
    ks = runner.parse_values(args.medium_k)
    rows = []
    print(f"{'C':>4} {'flow':>6} " + " ".join(f"{'k = ' + str(k):>7}" for k in ks))
    for c in runner.parse_values(args.medium_sweep):
        H = with_capacity(GM, c)
        row = dict(C=c, flow=objective(runner.run_algorithm(H, DM, FLOW, {}, save=False)))
        for k in ks:
            row[f"k{k}"] = objective(runner.run_algorithm(H, DM, ROUTE, {"k": k}, save=False))
        rows.append(row)
        print(f"{c:4d} {num(row['flow']) if row['flow'] is not None else 'infeas.':>6} "
              + " ".join(f"{num(row[f'k{k}']) if row[f'k{k}'] is not None else 'infeas.':>7}" for k in ks))
    for k in ks:
        same = [r["C"] for r in rows if r["flow"] is not None and r[f"k{k}"] is not None
                and abs(r[f"k{k}"] - r["flow"]) < 1e-6]
        print(f"k = {k}: same optimum as the flow formulation for C = {compact(same) or 'none of these'}")
    plot_medium(rows, ks, GM.graph["name"], figdir)

    # 4. GEANT2: size and time ----------------------------------------------------------------
    if not args.skip_large:
        title("4. Model size and computation time on a larger network")
        GL = network.load_topology(LARGE_TOPOLOGY)
        DL = traffic.load_traffic(LARGE_TRAFFIC, GL)
        name = GL.graph["name"].split(" (")[0]
        print(f"{GL.graph['name']}: {GL.number_of_nodes()} nodes, {GL.number_of_edges()} links, "
              f"{len(DL)} demands, {traffic.total_traffic(DL)} wavelengths")
        # A computation time changes from run to run: every case is solved several times, and
        # the repetitions are interleaved so that a slow period affects all the cases alike.
        reps = max(1, args.repetitions)
        caps = runner.parse_values(args.large_sweep)
        cases = [("flow", FLOW, {})] + [(f"k = {k}", ROUTE, {"k": k}) for k in runner.parse_values(args.large_k)]
        graphs = {c: with_capacity(GL, c) for c in caps}
        first, times = {}, {}
        for _ in range(reps):
            for c in caps:
                for label, fname, params in cases:
                    r = runner.run_algorithm(graphs[c], DL, fname, params, save=False)
                    first.setdefault((c, label), r)
                    times.setdefault((c, label), []).append(r.summary.get("time_s", 0))
        print(f"time in seconds: mean ± standard deviation of {reps} runs" if reps > 1 else
              "time in seconds: one run")
        print(f"{'C':>4} {'case':>8} {'objective':>9} {'variables':>9} {'time s':>13}")
        trows = []
        for c in caps:
            for label, _, _ in cases:
                r, t = first[c, label], runner.time_stats(times[c, label])
                trows.append(dict(C=c, case=label, objective=objective(r), variables=r.summary.get("num_variables"),
                                  time=t["time_s"], time_std=t["time_std_s"] or 0, runs=reps))
                tt = f"{t['time_s']:.2f}" + (f" ± {t['time_std_s']:.2f}" if t["time_std_s"] != "" else "")
                print(f"{c:4d} {label:>8} {num(objective(r)) if r.ok else 'infeas.':>9} "
                      f"{r.summary.get('num_variables', ''):>9} {tt:>13}")
        plot_large(trows, [label for label, _, _ in cases], name, figdir)
    print(f"\nfigures saved in {rel(figdir)}")
    return 0


def compact(values):
    """[30, 31, 32, 34] -> '30-32, 34'"""
    out, start, prev = [], None, None
    for v in values:
        if start is None:
            start = prev = v
        elif v == prev + 1:
            prev = v
        else:
            out.append(f"{start}" if start == prev else f"{start}-{prev}")
            start = prev = v
    if start is not None:
        out.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(out)


# ----------------------------------------------------------------------------------------
# figures
# ----------------------------------------------------------------------------------------
def save_data(png_path, **data):
    """The data of a figure, next to it as JSON (e.g. to draw it again with another tool)."""
    import json
    with open(os.path.splitext(png_path)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)


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


XLABEL = "capacity of every link, C (wavelengths)"


def integer_axis(axis):
    from matplotlib.ticker import MaxNLocator
    axis.set_major_locator(MaxNLocator(integer=True, steps=[1, 2, 2.5, 5, 10]))


def plot_medium(rows, ks, name, figdir):
    """Optimal objective vs capacity: the flow formulation and the route formulation for each k."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8.5, 5))
    series = [("flow", "flow formulation")] + [(f"k{k}", f"route formulation, k = {k}") for k in ks]
    values = [r[key] for r in rows for key, _ in series if r[key] is not None]
    low = min(values) if values else 0
    for i, (key, label) in enumerate(series):
        style = plotting.series_style(i)
        ok = [r for r in rows if r[key] is not None]
        # a series without any solution still gets its legend entry (its crosses are at the bottom)
        ax.plot([r["C"] for r in ok], [r[key] for r in ok], **style,
                label=label if ok else f"{label} (infeasible for all C)")
        bad = [r["C"] for r in rows if r[key] is None]
        if bad:                         # crosses at the bottom: capacities without a solution
            ax.plot(bad, [0.03 * i] * len(bad), ls="none", marker="x", ms=8, mew=2, color=style["color"],
                    transform=ax.get_xaxis_transform(), clip_on=False)
    hi = max(values) if values else 1
    ax.set_ylim(low - 0.25 * (hi - low), hi + 0.05 * (hi - low))
    ax.set_xlabel(XLABEL)
    ax.set_ylabel("total wavelengths used\n(summed over the links)")
    ax.set_title(f"{name}: optimal objective (× at the bottom: infeasible)")
    integer_axis(ax.xaxis)
    integer_axis(ax.yaxis)
    ax.legend(loc="upper right")
    save(fig, os.path.join(figdir, "lab2r_objective_vs_k.png"), kind="route_k", network=name, ks=ks, rows=rows)


def plot_large(trows, labels, name, figdir):
    """Mean computation time with error bars of one standard deviation, for each case."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    for i, label in enumerate(labels):
        pts = [r for r in trows if r["case"] == label and r["objective"] is not None]
        if pts:
            ax.errorbar([r["C"] for r in pts], [r["time"] for r in pts], yerr=[r["time_std"] for r in pts],
                        label="flow formulation" if label == "flow" else f"route formulation, {label}",
                        **plotting.series_style(i))
    runs = trows[0]["runs"] if trows else 1
    ax.set_ylim(0, max([r["time"] + r["time_std"] for r in trows] + [0.01]) * 1.3)
    ax.set_xlabel(XLABEL)
    ax.set_ylabel("computation time (s)")
    ax.set_title(f"Computation time on {name}\n"
                 + (f"mean ± standard deviation of {runs} runs; feasible cases only" if runs > 1 else "one run"))
    integer_axis(ax.xaxis)
    ax.legend(loc="center right")
    save(fig, os.path.join(figdir, "lab2r_time_large.png"), kind="route_times", network=name, rows=trows)


if __name__ == "__main__":
    sys.exit(main())
