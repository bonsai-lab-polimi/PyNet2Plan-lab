#!/usr/bin/env python3
"""
Lab 2 - the unsplittable flow formulation, compared with the splittable one
===========================================================================

Run it after completing formulations/unsplittable_flow.py (its four TODOs):

  1. checks the formulation on the small test network of PyNet2Plan
  2. Spain-7 with C = 40 on every link: splittable and unsplittable side by side
  3. a capacity sweep, C = 30 ... 60, with both formulations
  4. the bottleneck: the links that every fewest-hop routing must use
  5. a larger network (GEANT2, 35 nodes): computation times, as the mean and
     the standard deviation of several runs

The traffic is data/traffic/spain7_traffic_split_vs_unsplit.csv (24 demands,
229 wavelengths), the same as in Lab 1. The runs of part 2 are saved in
results/ (open them in the GUI with Results > Browse results...), the figures
in results/lab2_unsplittable/ (PNG and PDF, with their data as JSON).

    python labs/lab2_unsplittable.py
    python labs/lab2_unsplittable.py --sweep 30-60:2 --skip-large
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import networkx as nx  # noqa: E402

from pynet2plan import network, plotting, results, runner, traffic  # noqa: E402

TOPOLOGY = os.path.join(ROOT, "data", "topologies", "spain7.json")
TRAFFIC = os.path.join(ROOT, "data", "traffic", "spain7_traffic_split_vs_unsplit.csv")
LARGE = "top22_geant2"
LARGE_TOPOLOGY = os.path.join(ROOT, "data", "topologies", "real", f"{LARGE}.json")
LARGE_TRAFFIC = os.path.join(ROOT, "data", "traffic", "real", f"{LARGE}_traffic.csv")
SPLIT = "splittable_flow"


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


def full_links(res):
    return [f"{l['origin']}->{l['destination']}" for l in res.tables["links"]
            if l.get("capacity") and l.get("used", 0) >= l["capacity"]]


def routes_of(res):
    out = {}
    for r in res.tables["routes"]:
        out.setdefault(r["demand_id"], []).append(r)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--formulation", default=os.path.join(ROOT, "formulations", "unsplittable_flow.py"),
                    help="the unsplittable formulation to test (default: your exercise file)")
    ap.add_argument("--capacity", type=int, default=40, help="capacity of every link in part 2")
    ap.add_argument("--sweep", default="30-60", help="capacities of part 3, e.g. 30-60 or 30-60:2")
    ap.add_argument("--large-sweep", default="18-23", help="capacities of part 5 (GEANT2)")
    ap.add_argument("--skip-large", action="store_true", help="skip part 5")
    ap.add_argument("--repetitions", type=int, default=5, help="runs of every case of part 5")
    ap.add_argument("--out", default=None, help="results folder (default: results/)")
    ap.add_argument("--figures", default=None, help="figures folder (default: results/lab2_unsplittable)")
    args = ap.parse_args(argv)
    figdir = args.figures or os.path.join(args.out or os.path.join(ROOT, "results"), "lab2_unsplittable")
    os.makedirs(figdir, exist_ok=True)
    UNSPLIT = args.formulation
    shown = rel(UNSPLIT) if os.path.isfile(UNSPLIT) else UNSPLIT

    # 1. check ------------------------------------------------------------------------------
    title("1. Check of the formulation")
    print(f"file: {shown}")
    chk = runner.check_formulation(UNSPLIT)
    print(f"test network: status {chk.status}, objective {num(chk.summary.get('objective'))}")
    if not chk.ok:
        print("\n" + chk.message.strip())
        print("\nComplete the formulation (see the message above), then run this script again.")
        return 1
    if abs(float(chk.summary["objective"]) - 21) > 1e-6:
        print("Warning: on the test network the optimum of the unsplittable formulation is 21 "
              "(splittable: 20). Check the objective function.")
    else:
        print("expected 21 (splittable: 20): ok")

    G0 = network.load_topology(TOPOLOGY)
    D = traffic.load_traffic(TRAFFIC, G0)
    hops = dict(nx.shortest_path_length(G0))
    lower = sum(d.traffic * hops[d.origin][d.destination] for d in D)

    # 2. one capacity -------------------------------------------------------------------------
    C = args.capacity
    title(f"2. Spain-7, C = {C} on every link")
    print(f"{len(D)} demands, {traffic.total_traffic(D)} wavelengths; lower bound (fewest hops) {lower}")
    G = with_capacity(G0, C)
    runs = {}
    for key, name in (("splittable", SPLIT), ("unsplittable", UNSPLIT)):
        runs[key] = runner.run_algorithm(G, D, name, {}, output_root=args.out,
                                         topology_file=TOPOLOGY, traffic_file=TRAFFIC)
    print(f"{'':13s} {'status':>10s} {'objective':>9s} {'extra':>6s} {'variables':>9s} "
          f"{'constraints':>11s} {'split':>5s}")
    for key, r in runs.items():
        s = r.summary
        obj = s.get("objective") if r.ok else None
        print(f"{key:13s} {r.status:>10s} {num(obj):>9s} {num(obj - lower if obj is not None else None):>6s} "
              f"{s.get('num_variables', ''):>9} "
              f"{s.get('num_constraints', ''):>11} {s.get('split_demands', '-') if r.ok else '-':>5}")
    if not all(r.ok for r in runs.values()):
        for key, r in runs.items():
            if not r.ok:
                print(f"\n{key}: {r.message}")
        return 1
    rs, ru = routes_of(runs["splittable"]), routes_of(runs["unsplittable"])
    print("demands that do not follow a fewest-hop path in at least one of the two solutions:")
    for d in D:
        best = hops[d.origin][d.destination]
        a, b = rs.get(d.id, []), ru.get(d.id, [])
        if all(r["hops"] == best for r in a + b):
            continue
        print(f"  demand {d.id:2d} {d.origin}->{d.destination} ({d.traffic} λ, fewest hops {best})")
        for key, rr in (("splittable", a), ("unsplittable", b)):
            for k, r in enumerate(rr):
                extra = f"  (+{r['hops'] - best} hop)" if r["hops"] > best else ""
                print(f"      {key if k == 0 else '':12s} {r['traffic']:2g} λ  {r['path']}{extra}")
    for key, r in runs.items():
        print(f"full links ({key}): {', '.join(full_links(r)) or 'none'}")
        print(f"saved in {rel(r.folder)}")
    plot_maps(runs, C, os.path.join(figdir, f"lab2_maps_c{C}.png"))

    # 3. capacity sweep --------------------------------------------------------------------
    title("3. Capacity sweep")
    caps = runner.parse_values(args.sweep)
    rows = []
    for c in caps:
        H = with_capacity(G0, c)
        a = runner.run_algorithm(H, D, SPLIT, {}, save=False)
        b = runner.run_algorithm(H, D, UNSPLIT, {}, save=False)
        rows.append(dict(C=c, split=a.summary.get("objective") if a.ok else None,
                         unsplit=b.summary.get("objective") if b.ok else None))
    print(f"{'C':>4} {'splittable':>10} {'unsplittable':>12} {'difference':>10}")
    for r in rows:
        diff = r["unsplit"] - r["split"] if None not in (r["split"], r["unsplit"]) else None
        print(f"{r['C']:4d} {num(r['split']) if r['split'] is not None else 'infeasible':>10} "
              f"{num(r['unsplit']) if r['unsplit'] is not None else 'infeasible':>12} {num(diff):>10}")
    both = [r["C"] for r in rows if r["split"] is None and r["unsplit"] is None]
    only = [r["C"] for r in rows if r["split"] is not None and r["unsplit"] is None]
    equal = [r["C"] for r in rows if None not in (r["split"], r["unsplit"]) and abs(r["split"] - r["unsplit"]) < 1e-6]
    print(f"both infeasible: {compact(both) or 'none'};  only the unsplittable one: {compact(only) or 'none'};"
          f"  same optimum: {compact(equal) or 'none'}")
    plot_sweep(rows, lower, figdir)

    # 4. the bottleneck ----------------------------------------------------------------------
    title("4. Links used by every fewest-hop routing")
    forced = {}
    for d in D:
        paths = list(nx.all_shortest_paths(G0, d.origin, d.destination))
        common = set(zip(paths[0][:-1], paths[0][1:]))
        for p in paths[1:]:
            common &= set(zip(p[:-1], p[1:]))
        for e in common:
            forced.setdefault(e, []).append(d)
    top = sorted(forced.items(), key=lambda kv: -sum(d.traffic for d in kv[1]))[:4]
    for (u, v), ds in top:
        print(f"  {u}->{v}: {sum(d.traffic for d in ds)} λ  (demands {', '.join(str(d.id) for d in ds)})")
    (u, v), ds = top[0]
    load = sum(d.traffic for d in ds)
    print(f"With C < {load}, at least {load} - C wavelengths must avoid {u}->{v}.")
    print(f"Shortest path of each of these demands without {u}->{v}:")
    H = G0.copy()
    H.remove_edge(u, v)
    for d in ds:
        try:
            alt = nx.shortest_path(H, d.origin, d.destination)
            extra = len(alt) - 1 - hops[d.origin][d.destination]
            print(f"  demand {d.id:2d} ({d.traffic} λ)  {' > '.join(alt)}: +{extra} hop{'s' if extra != 1 else ''}, "
                  f"{d.traffic * extra} extra λ")
        except nx.NetworkXNoPath:
            print(f"  demand {d.id:2d}: no other path")

    # 5. a larger network ----------------------------------------------------------------------
    if not args.skip_large:
        title("5. Computation time on a larger network")
        GL = network.load_topology(LARGE_TOPOLOGY)
        DL = traffic.load_traffic(LARGE_TRAFFIC, GL)
        print(f"{GL.graph['name']}: {GL.number_of_nodes()} nodes, {GL.number_of_edges()} links, "
              f"{len(DL)} demands, {traffic.total_traffic(DL)} wavelengths")
        # A computation time changes from run to run (other programs, caches, ...): every case
        # is solved several times and the mean and the standard deviation are reported. The
        # repetitions are interleaved (all the cases once, then all again, ...), so that a slow
        # period of the computer affects all the cases alike.
        reps = max(1, args.repetitions)
        caps = runner.parse_values(args.large_sweep)
        graphs = {c: with_capacity(GL, c) for c in caps}
        first, times = {}, {}
        for _ in range(reps):
            for c in caps:
                for name in (SPLIT, UNSPLIT):
                    r = runner.run_algorithm(graphs[c], DL, name, {}, save=False)
                    first.setdefault((c, name), r)
                    times.setdefault((c, name), []).append(r.summary.get("time_s", 0))
        print(f"time in seconds: mean ± standard deviation of {reps} runs" if reps > 1 else
              "time in seconds: one run")
        print(f"{'C':>4} {'splittable':>10} {'time s':>13} {'unsplittable':>12} {'time s':>13} {'variables':>9}")
        trows = []
        for c in caps:
            a, b = first[c, SPLIT], first[c, UNSPLIT]
            ta, tb = runner.time_stats(times[c, SPLIT]), runner.time_stats(times[c, UNSPLIT])
            trows.append(dict(C=c, splittable=ta["time_s"], splittable_std=ta["time_std_s"] or 0,
                              unsplittable=tb["time_s"], unsplittable_std=tb["time_std_s"] or 0, runs=reps))
            print(f"{c:4d} {num(a.summary.get('objective')) if a.ok else a.status:>10} {mean_std(ta):>13} "
                  f"{num(b.summary.get('objective')) if b.ok else b.status:>12} {mean_std(tb):>13} "
                  f"{b.summary.get('num_variables', ''):>9}")
        plot_times(trows, GL.graph["name"].split(" (")[0], figdir)
    print(f"\nfigures saved in {rel(figdir)}")
    return 0


def mean_std(t):
    """'0.49 ± 0.03' (seconds) from runner.time_stats."""
    return f"{t['time_s']:.2f}" + (f" ± {t['time_std_s']:.2f}" if t["time_std_s"] != "" else "")


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


XLABEL = "capacity of every link, C (wavelengths)"


def integer_axis(axis):
    from matplotlib.ticker import MaxNLocator
    axis.set_major_locator(MaxNLocator(integer=True, steps=[1, 2, 2.5, 5, 10]))


def plot_maps(runs, C, path):
    plt = _plt()
    old, plotting.FONT_SCALE = plotting.FONT_SCALE, 1.45      # two maps side by side: larger text
    fig, axes = plt.subplots(1, 2, figsize=(12, 6.4))
    data = {}
    for ax, (key, res) in zip(axes, runs.items()):
        run = results.load_run(res.folder)
        data[key] = dict(objective=res.summary["objective"], **map_data(run))
        plotting.draw_network(ax, run.G, link_used=plotting.used_from_rows(run.links),
                              title=f"{key.capitalize()}, C = {C}: {num(res.summary['objective'])} wavelengths")
    plotting.FONT_SCALE = old
    fig.tight_layout()
    save(fig, path, kind="maps", C=C, maps=data)


def plot_sweep(rows, lower, figdir):
    plt = _plt()
    gray = "#616161"
    split, unsplit = plotting.series_style(0), plotting.series_style(1)
    both = [r["C"] for r in rows if r["split"] is None and r["unsplit"] is None]
    fig, ax = plt.subplots(figsize=(8.5, 5))
    if both:
        ax.axvspan(min(both) - 0.5, max(both) + 0.5, color="#eeeeee", zorder=0)
        ax.text((min(both) + max(both)) / 2, 0.5, "both\ninfeasible", transform=ax.get_xaxis_transform(),
                ha="center", va="center", color=gray)
    ax.axhline(lower, color=gray, lw=1.2, ls=(0, (4, 3)), label=f"lower bound {lower} (fewest hops)")
    ok_s = [r for r in rows if r["split"] is not None]
    ok_u = [r for r in rows if r["unsplit"] is not None]
    ax.plot([r["C"] for r in ok_s], [r["split"] for r in ok_s], label="splittable", **split)
    ax.plot([r["C"] for r in ok_u], [r["unsplit"] for r in ok_u], label="unsplittable", **unsplit)
    only = [r["C"] for r in rows if r["split"] is not None and r["unsplit"] is None]
    if only:
        ax.plot(only, [lower - 4] * len(only), ls="none", marker="x", ms=9, mew=2.2,
                color=unsplit["color"], zorder=5, clip_on=False, label="unsplittable infeasible")
    ax.set_xlabel(XLABEL)
    ax.set_ylabel("total wavelengths used, summed over the links")
    ax.set_title("Optimal objective of the two formulations")
    integer_axis(ax.xaxis)
    integer_axis(ax.yaxis)
    ax.legend(loc="upper right")
    save(fig, os.path.join(figdir, "lab2_objective_vs_capacity.png"), kind="sweep2", lower_bound=lower,
         rows=rows)

    fig, ax = plt.subplots(figsize=(8.5, 3.8))
    diff = [(r["C"], r["unsplit"] - r["split"]) for r in rows if None not in (r["split"], r["unsplit"])]
    ax.bar([c for c, _ in diff], [v for _, v in diff], width=0.7, color=unsplit["color"])
    for c, v in diff:
        ax.text(c, v + 0.4, f"{v:g}", ha="center", va="bottom", fontsize=9, color="#263238")
    for c in only:
        ax.text(c, 0.5, "unsplittable infeasible", rotation=90, ha="center", va="bottom", fontsize=9,
                color=gray)
    shown = [c for c, _ in diff] + only
    if shown:
        ax.set_xlim(min(shown) - 0.8, max(shown) + 0.8)
    ax.set_ylim(0, max([v for _, v in diff] + [1]) * 1.15)
    ax.set_xlabel(XLABEL)
    ax.set_ylabel("extra wavelengths")
    ax.set_title("Unsplittable minus splittable optimum")
    ax.grid(axis="x", visible=False)
    integer_axis(ax.xaxis)
    save(fig, os.path.join(figdir, "lab2_difference.png"), kind="sweep2", lower_bound=lower, rows=rows)


def plot_times(trows, name, figdir):
    """Mean computation time with error bars of one standard deviation."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    cs = [r["C"] for r in trows]
    for i, key in enumerate(("splittable", "unsplittable")):
        ax.errorbar(cs, [r[key] for r in trows], yerr=[r[f"{key}_std"] for r in trows],
                    label=key, **plotting.series_style(i))
    runs = trows[0]["runs"] if trows else 1
    ax.set_ylim(0, max([r[k] + r[k + "_std"] for r in trows for k in ("splittable", "unsplittable")]
                       + [0.01]) * 1.25)
    ax.set_xlabel(XLABEL)
    ax.set_ylabel("computation time (s)")
    ax.set_title(f"Computation time on {name}\n"
                 + (f"mean ± standard deviation of {runs} runs" if runs > 1 else "one run"))
    integer_axis(ax.xaxis)
    ax.legend(loc="upper right", ncol=2)
    save(fig, os.path.join(figdir, "lab2_time_large.png"), kind="times", network=name, rows=trows)


if __name__ == "__main__":
    sys.exit(main())
