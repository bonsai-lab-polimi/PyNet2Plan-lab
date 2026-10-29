"""
pynet2plan.plotting
==================

Matplotlib drawings shared by the GUI and the scripts (no Tk needed)::

    import matplotlib.pyplot as plt
    from pynet2plan import plotting, results

    run = results.load_run("results/<run folder>")
    fig, ax = plt.subplots(figsize=(8, 8))
    plotting.draw_network(ax, run.G, link_used=plotting.used_from_rows(run.links))
    fig.savefig("occupancy.png")

or simply ``python -m pynet2plan plot results/<run folder>``.
"""

from __future__ import annotations

import math
import os

from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from . import geo

# link utilization classes: (upper bound, color, legend label)
UTIL_CLASSES = [
    (0.0, "#bdbdbd", "unused"),
    (0.5, "#2e7d32", "≤ 50%"),
    (0.8, "#f9a825", "50–80%"),
    (0.999999, "#ef6c00", "80–100%"),
    (1.000001, "#c62828", "100% (full)"),
    (math.inf, "#7b1fa2", "> 100% (over capacity!)"),
]
DESIGN_LINK_COLOR = "#455a64"
#: categorical colors of the series in the sweep charts (fixed order, colorblind-checked)
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SERIES_MARKERS = "osD^vP*X"
#: line styles of the series: solid, dashed, dash-dot, dotted, then longer patterns
SERIES_LINESTYLES = ["-", (0, (5, 2)), (0, (6, 2, 1.5, 2)), (0, (1.5, 1.5)), (0, (9, 2.5)),
                     (0, (6, 2, 1.5, 2, 1.5, 2)), (0, (3, 1.5)), (0, (1, 3))]
TEXT_COLOR = "#263238"

#: multiplies every font size of the charts (GUI: View > Text size)
FONT_SCALE = 1.0


def fs(size: float) -> float:
    """A font size in points, scaled by FONT_SCALE."""
    return size * FONT_SCALE
DOWN_COLOR = "#9e9e9e"
NODE_COLOR = "#1565c0"
NODE_DOWN_COLOR = "#c62828"
HIGHLIGHT_COLOR = "#00acc1"
SELECT_COLOR = "#ffb300"


def util_color(util) -> str:
    if util is None:
        return UTIL_CLASSES[-1][1]
    if util <= 1e-9:
        return UTIL_CLASSES[0][1]
    for bound, color, _ in UTIL_CLASSES[1:]:
        if util <= bound:
            return color
    return UTIL_CLASSES[-1][1]


def used_from_rows(link_rows: list) -> dict:
    """``{(origin, destination): used}`` from the rows of links.csv."""
    return {(r["origin"], r["destination"]): (r.get("used") or 0) for r in link_rows}


def _curve(G, u, v) -> float:
    return 0.12 if G.has_edge(v, u) else 0.0


def _span(G) -> float:
    xs = [a.get("x", 0.0) for _, a in G.nodes(data=True)] or [0.0]
    ys = [a.get("y", 0.0) for _, a in G.nodes(data=True)] or [0.0]
    return max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0


def link_midpoint(G, u, v) -> tuple:
    """Position of the label of the drawn (possibly curved) link u->v: the middle of
    the arc, pushed a bit further out for short links so that the labels of the two
    directions do not overlap."""
    a, b = G.nodes[u], G.nodes[v]
    x1, y1, x2, y2 = a["x"], a["y"], b["x"], b["y"]
    rad = _curve(G, u, v)
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    if not rad:
        return mx, my
    length = math.hypot(dx, dy) or 1.0
    off = max(0.5 * rad * length, 0.035 * _span(G))      # distance from the straight line
    return mx + off * dy / length, my - off * dx / length


def draw_network(ax, G, *, link_used: dict | None = None, highlight_paths: list | None = None,
                 highlight_links: set | None = None, selected_node=None, selected_link=None,
                 show_names: bool = True, label_mode: str | None = "util",
                 title: str | None = None, legend: bool = True, map_background: bool = False,
                 node_size: float | None = None) -> None:
    """Draw the network on ``ax``.

    link_used        {(u, v): wavelengths used}; if given, links are colored by
                     utilization (results view), otherwise in a neutral color
    highlight_paths  list of node paths drawn as a thick colored overlay
    label_mode       "util" (percentage), "used" (used/capacity), "capacity" or None
                     ("capacity" shows "2×40" for a link with 2 fibers of 40 wavelengths)
    """
    ax.clear()
    ax.set_xticks([])
    ax.set_yticks([])
    if title:
        ax.set_title(title, fontsize=fs(12))
    n = G.number_of_nodes()
    if n == 0:
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(0, 1000)
        ax.set_ylim(0, 1000)
        ax.text(500, 500, "Empty network\nuse the 'Add node' mode, File > Open topology,\n"
                "or File > Add cities", ha="center", va="center", color="#777777", fontsize=fs(10))
        return
    # 'datalim' fills the panel; limits are then computed automatically from the nodes
    ax.set_aspect("equal", adjustable="box" if map_background else "datalim")
    xs = [a["x"] for _, a in G.nodes(data=True)]
    ys = [a["y"] for _, a in G.nodes(data=True)]
    if n == 1 or (max(xs) == min(xs) and max(ys) == min(ys)):
        ax.update_datalim([(xs[0] - 50, ys[0] - 50), (xs[0] + 50, ys[0] + 50)])
    many = n > 40
    size = node_size if node_size is not None else (60 if many else (180 if n > 15 else 320))
    shrink = 4 if many else (7 if n > 15 else 10)

    highlight_links = set(highlight_links or ())
    hl_path_links = set()
    for p in highlight_paths or []:
        hl_path_links.update(zip(p[:-1], p[1:]))

    for u, v, a in G.edges(data=True):
        pu, pv = G.nodes[u], G.nodes[v]
        up = a.get("up", True) and pu.get("up", True) and pv.get("up", True)
        fibers = a.get("fibers", 1)
        cap = fibers * a.get("capacity", 0)
        if not up:
            color, lw, ls = DOWN_COLOR, 1.2, (0, (3, 3))
        elif link_used is not None:
            used = link_used.get((u, v), 0) or 0
            util = (used / cap) if cap > 0 else (0.0 if used == 0 else None)
            color = util_color(util)
            lw = 1.0 + 3.0 * min(util if util is not None else 1.0, 1.0) if used else 0.9
            ls = "-"
        else:
            color, lw, ls = DESIGN_LINK_COLOR, 1.4 + 1.2 * min(fibers - 1, 3), "-"
        rad = _curve(G, u, v)
        if (u, v) in hl_path_links or (u, v) in highlight_links:
            ax.annotate("", xy=(pv["x"], pv["y"]), xytext=(pu["x"], pu["y"]),
                        arrowprops=dict(arrowstyle="-", color=HIGHLIGHT_COLOR, lw=lw + 6, alpha=0.55,
                                        shrinkA=shrink, shrinkB=shrink,
                                        connectionstyle=f"arc3,rad={rad}"), zorder=2)
        if selected_link == (u, v):
            ax.annotate("", xy=(pv["x"], pv["y"]), xytext=(pu["x"], pu["y"]),
                        arrowprops=dict(arrowstyle="-", color=SELECT_COLOR, lw=lw + 7, alpha=0.8,
                                        shrinkA=shrink, shrinkB=shrink,
                                        connectionstyle=f"arc3,rad={rad}"), zorder=2)
        ax.annotate("", xy=(pv["x"], pv["y"]), xytext=(pu["x"], pu["y"]),
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=lw, linestyle=ls,
                                    shrinkA=shrink, shrinkB=shrink, mutation_scale=8 if many else 11,
                                    connectionstyle=f"arc3,rad={rad}"), zorder=3)
        if label_mode and not many and up:
            used = (link_used or {}).get((u, v), 0) or 0
            if label_mode == "util" and link_used is not None and used:
                text = f"{100 * used / cap:.0f}%" if cap else "∞"
            elif label_mode == "used" and link_used is not None:
                text = f"{used:g}/{cap}"
            elif label_mode == "capacity":
                text = f"{fibers}×{a.get('capacity', 0)}" if fibers > 1 else f"{cap}"
            else:
                text = ""
            if text:
                mx, my = link_midpoint(G, u, v)
                ax.text(mx, my, text, fontsize=fs(8), color=TEXT_COLOR, ha="center", va="center",
                        zorder=4, bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none",
                                            alpha=0.85))

    colors, edgecolors, lws = [], [], []
    for name, a in G.nodes(data=True):
        colors.append(NODE_COLOR if a.get("up", True) else NODE_DOWN_COLOR)
        edgecolors.append(SELECT_COLOR if name == selected_node else "white")
        lws.append(3.0 if name == selected_node else 1.2)
    ax.scatter(xs, ys, s=size, c=colors, edgecolors=edgecolors, linewidths=lws, zorder=5)
    if show_names:
        ax.margins(x=0.1, y=0.16)
    else:
        ax.margins(0.08)
    ax.autoscale_view()
    if show_names:
        offset = (math.sqrt(size) / 2 + 3)
        for name, a in G.nodes(data=True):
            ax.annotate(str(name), (a["x"], a["y"]), textcoords="offset points",
                        xytext=(0, offset), ha="center", fontsize=fs(7.5 if many else 9.5), zorder=6,
                        color=TEXT_COLOR, fontweight="bold" if not many else "normal",
                        bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.7))

    if legend:
        handles = []
        any_down = any(not a.get("up", True) for _, _, a in G.edges(data=True)) or \
            any(not a.get("up", True) for _, a in G.nodes(data=True))
        if link_used is not None:
            present = set()
            for u, v, a in G.edges(data=True):
                if a.get("up", True) and G.nodes[u].get("up", True) and G.nodes[v].get("up", True):
                    used = link_used.get((u, v), 0) or 0
                    cap = a.get("fibers", 1) * a.get("capacity", 0)
                    present.add(util_color((used / cap) if cap > 0 else (0.0 if used == 0 else None)))
            handles = [Line2D([0], [0], color=c, lw=3, label=lab) for _, c, lab in UTIL_CLASSES
                       if c in present]
            if any_down:
                handles.append(Line2D([0], [0], color=DOWN_COLOR, lw=1.5, ls="--", label="failed"))
            title_ = "link utilization"
        elif any_down:
            handles = [Line2D([0], [0], color=DESIGN_LINK_COLOR, lw=2, label="link up"),
                       Line2D([0], [0], color=DOWN_COLOR, lw=1.5, ls="--", label="link failed"),
                       Line2D([0], [0], marker="o", color="w", markerfacecolor=NODE_DOWN_COLOR,
                              markersize=8, label="node failed")]
            title_ = None
        if handles:
            # below the map, outside the drawing: it never hides nodes or links
            ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.005),
                      ncol=min(len(handles), 4), fontsize=fs(9.5), frameon=False,
                      title=title_, title_fontsize=fs(10), handlelength=1.6, columnspacing=1.2,
                      borderaxespad=0.2)

    if map_background:
        draw_map_background(ax, G)


def draw_map_background(ax, G) -> str:
    """Add a map behind the network. Returns a short description of what was drawn."""
    if not all(a.get("lat") is not None for _, a in G.nodes(data=True)):
        ax.text(0.5, 0.02, "map background: needs geographic nodes (File > Add cities)",
                transform=ax.transAxes, ha="center", va="bottom", fontsize=fs(8), color="#555555")
        return "not geographic"
    try:
        import contextily as cx  # optional, needs internet
        cx.add_basemap(ax, crs="EPSG:3857", attribution_size=5)
        return "OpenStreetMap"
    except Exception:  # noqa: BLE001 - not installed or no internet
        geo.draw_offline_graticule(ax)
        return "offline grid"


# ----------------------------------------------------------------------
def plot_utilization_bars(ax, link_rows: list, max_bars: int = 60) -> None:
    """Horizontal bars: utilization of every (up) link, most loaded first."""
    ax.clear()
    rows = [r for r in link_rows if r.get("up", True)]
    rows.sort(key=lambda r: -(r.get("utilization") if r.get("utilization") not in (None, "") else 9))
    if len(rows) > max_bars:
        rows = rows[:max_bars]
    labels = [f"{r['origin']} → {r['destination']}" for r in rows]
    vals = [(r.get("utilization") if r.get("utilization") not in (None, "") else 1.5) for r in rows]
    ys = list(range(len(rows)))
    ax.barh(ys, [100 * v for v in vals], height=0.72, color=[util_color(v) for v in vals])
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=fs(7.5 if len(rows) > 30 else 10))
    ax.tick_params(axis="x", labelsize=fs(10))
    ax.invert_yaxis()
    ax.axvline(100, color="#c62828", lw=1.2)
    ax.text(100, -0.9, "capacity", color="#c62828", fontsize=fs(8.5), ha="center", va="bottom")
    ax.set_xlabel("utilization = used / capacity (%)", fontsize=fs(11))
    small = len(rows) > 30
    for y, r in zip(ys, rows):
        ax.text(100 * vals[y] + 1.5, y, f"{r.get('used', 0):g}/{r.get('capacity', 0):g}",
                va="center", fontsize=fs(7.5 if small else 9), color=TEXT_COLOR)
    ax.set_xlim(0, max([118] + [100 * v + 18 for v in vals]))
    ax.set_ylim(len(rows) - 0.5, -1.4)
    title = "Link occupancy, most loaded first"
    if len(link_rows) > len(rows):
        title += f" - {len(rows)} links shown"
    ax.set_title(title, fontsize=fs(12))
    ax.grid(axis="x", alpha=0.3)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def plot_wavelength_grid(ax, wavelength_rows: list, link_rows: list, max_links: int = 80) -> None:
    """Which wavelength is used by which demand on every link (WP formulations).

    A link with several fibers gets one row per fiber: the routes that use the
    same wavelength on the link are shown on fibers 1, 2, ... in order.
    """
    import matplotlib
    import matplotlib.colors as mcolors
    import numpy as np
    ax.clear()
    links = []
    for r in link_rows:
        if not r.get("up", True):
            continue
        fibers = int(r.get("fibers") or 1)
        per_fiber = r.get("wavelengths_per_fiber")
        per_fiber = int(per_fiber) if per_fiber not in (None, "") else int(r.get("capacity") or 0) // fibers
        links.append((r["origin"], r["destination"], per_fiber, fibers))
    used_links = {(r["origin"], r["destination"]) for r in wavelength_rows}
    links = [l for l in links if (l[0], l[1]) in used_links] or links
    rows = [(u, v, cap, f, fibers) for (u, v, cap, fibers) in links for f in range(fibers)]
    rows = rows[:max_links]
    if not rows:
        ax.text(0.5, 0.5, "No links", ha="center", va="center", transform=ax.transAxes)
        return
    W = max(max(r[2] for r in rows), 1)
    index = {(u, v, f): k for k, (u, v, _, f, _) in enumerate(rows)}
    grid = np.full((len(rows), W), np.nan)
    for k, (_, _, cap, _, _) in enumerate(rows):
        grid[k, cap:] = -1          # wavelength does not exist on this link
    fiber_of: dict = {}
    for r in wavelength_rows:
        u, v, w = r["origin"], r["destination"], int(r["wavelength"])
        f = fiber_of.get((u, v, w), 0)            # next free fiber for this wavelength
        fiber_of[u, v, w] = f + 1
        k = index.get((u, v, f))
        if k is not None and 0 <= w < W:
            grid[k, w] = int(r["demand_id"]) % 20
    tab20 = matplotlib.colormaps["tab20"]
    cmap = mcolors.ListedColormap(["#e0e0e0"] + [mcolors.to_hex(tab20(i)) for i in range(20)])
    # 0 = free / not available (drawn dark below), 1..20 = demand id % 20 + 1
    disp = np.where(np.isnan(grid) | (grid < 0), 0, grid + 1)
    ax.imshow(disp, aspect="auto", cmap=cmap, vmin=-0.5, vmax=20.5, interpolation="nearest")
    for k, (_, _, cap, _, _) in enumerate(rows):
        if cap < W:
            ax.fill_between([cap - 0.5, W - 0.5], k - 0.5, k + 0.5, color="#424242", alpha=0.6, lw=0)
    for k, (_, _, _, f, fibers) in enumerate(rows):         # white lines around the fibers of a link
        if fibers > 1 and f == 0 and k > 0:
            ax.axhline(k - 0.5, color="white", lw=2)
        if fibers > 1 and f == fibers - 1 and k < len(rows) - 1:
            ax.axhline(k + 0.5, color="white", lw=2)
    from matplotlib.ticker import MaxNLocator
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, steps=[1, 2, 2.5, 5, 10]))
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"{u} → {v}" + (f", fiber {f + 1}" if fibers > 1 else "")
                        for u, v, _, f, fibers in rows], fontsize=fs(7.5 if len(rows) > 30 else 10))
    ax.tick_params(axis="x", labelsize=fs(10))
    ax.set_xlabel("wavelength index", fontsize=fs(11))
    ax.set_title("Wavelength assignment (color = demand id; gray = free; dark = not available)",
                 fontsize=fs(12))
    ax.legend(handles=[Patch(color="#e0e0e0", label="free"), Patch(color="#424242", label="n/a")],
              loc="upper right", fontsize=fs(9.5))


# ----------------------------------------------------------------------
def series_key(row: dict) -> str:
    """Short label of an algorithm + its parameters, e.g. 'route_formulation_vwp k=2'."""
    f = str(row.get("algorithm_file") or "")
    stem = os.path.splitext(os.path.basename(f))[0] if f else str(row.get("algorithm", "?"))
    if row.get("algorithm_origin") == "solutions":
        stem += " [ref]"
    params = row.get("parameters") or ""
    shown = " ".join(p for p in params.split("; ") if p and not p.startswith("time_limit"))
    return f"{stem} {shown}".strip()


def series_name(stem: str) -> str:
    """Readable name of an algorithm file: 'route_formulation_vwp' -> 'route formulation VWP'
    (words without vowels, i.e. acronyms, in capitals)."""
    return " ".join(w.upper() if w and not set(w.lower()) & set("aeiouy") else w
                    for w in stem.split("_"))


def series_labels(rows: list) -> dict:
    """Readable legend label for every series_key of ``rows``: the name of the algorithm
    file, plus only the parameters whose value changes between the series of that file
    (e.g. 'KSP first fit (k=2)', not every parameter); '(reference)' marks a reference
    solution only when the exercise of the same name is also in the chart."""
    info = {}
    for r in rows:
        key = series_key(r)
        stem, _, rest = key.partition(" ")
        ref = rest.startswith("[ref]")
        rest = rest[5:].strip() if ref else rest
        info[key] = (stem, ref, dict(p.split("=", 1) for p in rest.split() if "=" in p))
    labels = {}
    for key, (stem, ref, params) in info.items():
        same = [v for v in info.values() if v[0] == stem]
        shown = [f"{k}={v}" for k, v in params.items() if len({s[2].get(k) for s in same}) > 1]
        if ref and any(not s[1] for s in same):
            shown.insert(0, "reference")
        labels[key] = series_name(stem) + (f" ({', '.join(shown)})" if shown else "")
    return labels


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def series_style(i: int) -> dict:
    """Color, marker and line style of the i-th series of a chart.

    The three change together, so that the series can be told apart also in a
    black-and-white print and by readers with a color vision deficiency; every
    second series has hollow markers, which stay visible where two curves overlap.
    """
    color = SERIES_COLORS[i % len(SERIES_COLORS)]
    return dict(color=color, marker=SERIES_MARKERS[i % len(SERIES_MARKERS)],
                linestyle=SERIES_LINESTYLES[i % len(SERIES_LINESTYLES)],
                markerfacecolor=color if i % 2 == 0 else "white", markeredgecolor=color)


def plot_sweep(ax_obj, ax_time, rows: list, metric: str = "wavelength_links",
               compact: bool = False) -> None:
    """Objective vs capacity and computation time vs capacity: one curve per
    algorithm/parameters, × on the axis where there is no valid solution. The
    time is the mean of the repetitions of each run, with error bars of one
    standard deviation. ``ax_time`` may be None (objective only); ``compact`` =
    small panel of the GUI."""
    ax_obj.clear()
    if ax_time is not None:
        ax_time.clear()
    for old in list(ax_obj.figure.legends):    # the legend of a previous drawing of the figure
        old.remove()
    series: dict = {}
    infeasible: dict = {}
    times: dict = {}
    runs = set()
    for r in rows:
        key = series_key(r)
        cap = _num(r.get("capacity"))
        st = r.get("status")
        series.setdefault(key, [])
        if st in ("OPTIMAL", "FEASIBLE") and cap is not None and r.get(metric) not in ("", None):
            series[key].append((cap, float(r[metric])))
            t = _num(r.get("time_s"))
            if t is not None:
                sd = _num(r.get("time_std_s")) or 0.0
                times.setdefault(key, []).append((cap, 1000 * t, 1000 * sd))
                runs.add(int(_num(r.get("time_runs")) or 1))
        elif cap is not None:
            infeasible.setdefault(key, []).append(cap)
    keys = list(series)
    names = series_labels(rows)
    style = {k: series_style(i) for i, k in enumerate(keys)}
    small = 0.9 if compact else 1.0
    f_title, f_label, f_tick, f_legend = (fs(12 * small), fs(11 * small), fs(10 * small),
                                          fs(9.5 * small))
    xlabel = "capacity of every link, C (wavelengths)"
    with_bad = [k for k in keys if infeasible.get(k)]
    for key in keys:
        pts = sorted(series[key])
        if pts:
            ax_obj.plot([p[0] for p in pts], [p[1] for p in pts], ms=6.5, lw=2, mew=1.4,
                        label=names[key], **style[key])
        bad = infeasible.get(key, [])
        if bad:
            # crosses on the x axis: capacities without a valid solution (one row per series,
            # so that the crosses of different series do not hide each other)
            ax_obj.plot(bad, [0.03 * with_bad.index(key)] * len(bad), ls="none", marker="x",
                        ms=7.5, mew=2,
                        color=style[key]["color"], transform=ax_obj.get_xaxis_transform(),
                        clip_on=False, zorder=5,
                        label=None if pts else f"{names[key]} (no valid solution)")
    ys = [y for k in keys for _, y in series[k]]
    if with_bad and ys:            # room for the crosses below the lowest point
        lo, hi = min(ys), max(ys)
        span = (hi - lo) or max(1.0, abs(hi) * 0.05)
        band = 0.03 * len(with_bad) + 0.04
        ax_obj.set_ylim(lo - span * band / (1 - band), hi + 0.06 * span)
    ax_obj.set_xlabel(xlabel, fontsize=f_label)
    if metric != "wavelength_links":
        ylabel = metric
    elif compact:                  # small panel of the GUI: a short label
        ylabel = "wavelengths used"
    else:
        ylabel = "total wavelengths used\n(summed over the links)"
    ax_obj.set_ylabel(ylabel, fontsize=f_label)
    ax_obj.set_title("Objective vs. link capacity", fontsize=f_title)
    ax_obj.tick_params(labelsize=f_tick)
    if keys:
        handles, labels = ax_obj.get_legend_handles_labels()
        if infeasible:
            handles.append(Line2D([0], [0], ls="none", marker="x", color="#424242", mew=2, ms=8))
            labels.append("× on the axis: no valid solution")
        if ax_time is not None:
            # one legend for both charts, below them: it never hides the curves
            _figure_legend(ax_obj, handles, labels, f_legend)
        else:
            # small panel: above the chart, under the title, outside the plotting area
            ncol = 2 if len(labels) > 2 else len(labels)
            nrows = -(-len(labels) // ncol)
            ax_obj.legend(handles, labels, fontsize=f_legend, loc="lower left",
                          bbox_to_anchor=(0.0, 1.01), ncol=ncol, frameon=False, borderaxespad=0.0,
                          handlelength=2.6, columnspacing=1.5)
            ax_obj.set_title("Objective vs. link capacity", fontsize=f_title,
                             pad=6 + nrows * 2.0 * f_legend)
    _integer_ticks(ax_obj)
    if metric == "wavelength_links":
        _integer_ticks(ax_obj, "y", nbins=4 if compact else "auto")
    _style(ax_obj)

    if ax_time is None:
        return
    vals = [t for k in keys for _, t, _ in times.get(k, []) if t > 0]
    log = bool(vals) and max(vals) / min(vals) > 30
    for key in keys:
        pts = sorted(times.get(key, []))
        if not pts:
            continue
        xs, ys, sds = [p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts]
        low = [min(sd, 0.95 * y) for y, sd in zip(ys, sds)] if log else sds
        ax_time.errorbar(xs, ys, yerr=[low, sds] if any(sds) else None, ms=6, lw=1.8, mew=1.4,
                         capsize=3.5, elinewidth=1.2, capthick=1.2, label=names[key], **style[key])
    ax_time.set_xlabel(xlabel, fontsize=f_label)
    ax_time.set_ylabel("computation time (ms" + (", log scale)" if log else ")"), fontsize=f_label)
    n = sorted(runs)
    if not n or n == [1]:
        sub = "one run per point"
    else:
        sub = (f"mean ± standard deviation of {n[0]} runs" if len(n) == 1 else
               f"mean ± standard deviation of {n[0]}-{n[-1]} runs")
    ax_time.set_title(f"Computation time vs. link capacity\n{sub}", fontsize=f_title,
                      linespacing=1.5)
    ax_time.tick_params(labelsize=f_tick)
    if log:
        ax_time.set_yscale("log")
    else:
        ax_time.set_ylim(bottom=0)
    _integer_ticks(ax_time)
    ax_time.set_xlim(ax_obj.get_xlim())        # the same capacities on both charts
    _style(ax_time)


def _figure_legend(ax, handles, labels, fontsize) -> None:
    """A legend centred below all the charts of the figure of ``ax``, in up to 3 columns."""
    fig = ax.figure
    ncol = min(3, len(labels))
    opts = dict(ncol=ncol, fontsize=fontsize, frameon=False, handlelength=2.6, columnspacing=2.2)
    if getattr(fig, "get_layout_engine", lambda: None)() is not None:
        try:                                   # matplotlib >= 3.7: room made by the layout
            fig.legend(handles, labels, loc="outside lower center", **opts)
            return
        except (ValueError, TypeError):
            pass
    ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.0, -0.16), **opts)


def use_report_style() -> None:
    """Matplotlib settings for the figures of a report (used by the lab scripts).

    Fonts large enough to be read when the figure is reduced to the width of a
    column, curves that differ in color, marker and line style (see
    :func:`series_style`), light grid, no frame around legends, error bars with
    caps, and PDF files with embedded fonts.
    """
    import matplotlib as mpl
    from cycler import cycler
    mpl.rcParams.update({
        "font.size": 11, "axes.titlesize": 12.5, "axes.labelsize": 11.5,
        "xtick.labelsize": 10.5, "ytick.labelsize": 10.5, "legend.fontsize": 10.5,
        "lines.linewidth": 2.0, "lines.markersize": 6.5, "lines.markeredgewidth": 1.3,
        "errorbar.capsize": 3.5,
        "axes.grid": True, "grid.alpha": 0.3, "axes.axisbelow": True,
        "axes.spines.top": False, "axes.spines.right": False,
        "legend.frameon": False, "legend.handlelength": 2.6,
        "axes.prop_cycle": (cycler(color=SERIES_COLORS) + cycler(marker=list(SERIES_MARKERS))
                            + cycler(linestyle=SERIES_LINESTYLES)),
        "savefig.dpi": 150, "savefig.bbox": "tight", "pdf.fonttype": 42,
    })


def save_figure(fig, png_path: str) -> list:
    """Save a figure as PNG (for the screen) and as PDF next to it (vector, for a report)."""
    pdf = os.path.splitext(png_path)[0] + ".pdf"
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    import matplotlib
    with matplotlib.rc_context({"pdf.fonttype": 42}):
        fig.savefig(pdf, bbox_inches="tight")
    return [png_path, pdf]


def _integer_ticks(ax, axis="x", nbins="auto") -> None:
    """Capacities and wavelengths are whole numbers: no ticks at 20.5."""
    from matplotlib.ticker import MaxNLocator
    locator = MaxNLocator(nbins=nbins, integer=True, steps=[1, 2, 2.5, 5, 10])
    (ax.xaxis if axis == "x" else ax.yaxis).set_major_locator(locator)


def _style(ax) -> None:
    ax.grid(alpha=0.3)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def save_run_figures(folder: str, dpi: int = 130) -> list:
    """Write map.png, utilization.png (and wavelengths.png) in a run folder."""
    import matplotlib
    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    from .results import is_sweep_folder, load_run, load_sweep
    out = []
    if is_sweep_folder(folder):
        sw = load_sweep(folder)
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5.5), constrained_layout=True)
        plot_sweep(a1, a2, sw.rows)
        p = os.path.join(folder, "sweep.png")
        fig.savefig(p, dpi=dpi)
        plt.close(fig)
        return [p]
    run = load_run(folder)
    fig, ax = plt.subplots(figsize=(9, 8))
    draw_network(ax, run.G, link_used=used_from_rows(run.links), title=run.title)
    p = os.path.join(folder, "map.png")
    fig.savefig(p, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    out.append(p)
    fig, ax = plt.subplots(figsize=(9, max(3, 0.18 * len(run.links) + 1)))
    plot_utilization_bars(ax, run.links)
    fig.tight_layout()
    p = os.path.join(folder, "utilization.png")
    fig.savefig(p, dpi=dpi)
    plt.close(fig)
    out.append(p)
    if run.wavelengths:
        fig, ax = plt.subplots(figsize=(10, max(3, 0.2 * len(run.links) + 1)))
        plot_wavelength_grid(ax, run.wavelengths, run.links)
        fig.tight_layout()
        p = os.path.join(folder, "wavelengths.png")
        fig.savefig(p, dpi=dpi)
        plt.close(fig)
        out.append(p)
    return out
