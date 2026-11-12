"""
pynet2plan.eon.plotting
======================

Matplotlib drawings of the EON part, shared by the EON window and the
scripts (no Tk needed)::

    import matplotlib.pyplot as plt
    from pynet2plan.eon import plotting, results
    run = results.load_run("results/eon/<run folder>")
    fig, ax = plt.subplots(figsize=(12, 4))
    plotting.plot_spectrum_grid(ax, run.spectrum, run.links, run.num_slots)

or ``python -m pynet2plan eon-plot results/eon/<run folder>``.
"""

from __future__ import annotations

import os

from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from .. import plotting as base

WORKING_COLOR = "#2e7d32"
BACKUP_COLOR = "#7b1fa2"
REGEN_COLOR = "#ffb300"
CUT_COLOR = "#c62828"
DOWN_COLOR = "#c62828"


#: one fixed color per data rate (Gb/s), the same in every chart (spectrum grid, transponders):
#: well apart from each other, not a gradient
RATE_COLORS = {100: "#1f77b4", 200: "#ff7f0e", 300: "#2ca02c", 400: "#d62728", 500: "#9467bd",
               600: "#8c564b", 700: "#e377c2", 800: "#17becf"}
_OTHER_RATE_COLORS = ["#7f7f7f", "#bcbd22", "#393b79", "#ad494a", "#637939", "#7b4173"]


def _rate_colors(rates):
    """{rate: RGBA}: the fixed color of RATE_COLORS, other rates (an edited table) in other colors."""
    from matplotlib.colors import to_rgba
    out, k = {}, 0
    for r in sorted(set(rates)):
        key = int(r) if float(r).is_integer() else r
        if key in RATE_COLORS:
            out[r] = RATE_COLORS[key]
        else:
            out[r] = _OTHER_RATE_COLORS[k % len(_OTHER_RATE_COLORS)]
            k += 1
    return {r: to_rgba(c) for r, c in out.items()}


def _overlay_path(ax, G, path, color, lw=5.0, ls="-", alpha=0.75, zorder=2.5):
    for u, v in zip(path[:-1], path[1:]):
        if u not in G or v not in G:
            continue
        a, b = G.nodes[u], G.nodes[v]
        rad = 0.12 if G.has_edge(v, u) else 0.0
        ax.annotate("", xy=(b["x"], b["y"]), xytext=(a["x"], a["y"]),
                    arrowprops=dict(arrowstyle="-", color=color, lw=lw, alpha=alpha, linestyle=ls,
                                    shrinkA=8, shrinkB=8, connectionstyle=f"arc3,rad={rad}"),
                    zorder=zorder)


def length_labels(ax, G, fontsize=base.fs(7)):
    """One 'km' label per fibre (not one per direction)."""
    done = set()
    for u, v, a in G.edges(data=True):
        key = frozenset((u, v))
        if key in done:
            continue
        done.add(key)
        x = (G.nodes[u]["x"] + G.nodes[v]["x"]) / 2
        y = (G.nodes[u]["y"] + G.nodes[v]["y"]) / 2
        ax.text(x, y, f"{a['length']:g} km", fontsize=fontsize, ha="center", va="center", zorder=4,
                color="#263238", bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="#cfd8dc", alpha=0.9))


def _cut_list(G, cut) -> list:
    """The cut entries of G: ``cut`` is None, one (u, v), or a list of (u, v) (a fibre) and
    (u, v, "oneway") (one direction)."""
    if not cut:
        return []
    if not isinstance(cut[0], (list, tuple)):
        cut = [cut]
    return [tuple(e) for e in cut if e[0] in G and e[1] in G]


def _cut_where(G, entry):
    """Where the X of a cut goes: the middle of the fibre, or of the arrow of one direction."""
    from .analysis import is_oneway
    u, v = entry[0], entry[1]
    if is_oneway(entry) and G.has_edge(v, u):
        return base.link_midpoint(G, u, v)
    return (G.nodes[u]["x"] + G.nodes[v]["x"]) / 2, (G.nodes[u]["y"] + G.nodes[v]["y"]) / 2


def _mark_cut(ax, G, entries):
    """The cut links dashed red, a red X on every cut fibre or direction."""
    from .analysis import cut_links
    for a, b in cut_links(entries):
        if G.has_edge(a, b):
            _overlay_path(ax, G, [a, b], CUT_COLOR, lw=2.5, ls=(0, (3, 2)), alpha=0.9, zorder=3)
    for e in entries:
        x, y = _cut_where(G, e)
        ax.text(x, y, "✗", color=CUT_COLOR, fontsize=base.fs(22), fontweight="bold", ha="center", va="center",
                zorder=7)


def draw_eon_network(ax, G, *, show_names=True, show_lengths=True, selected_node=None,
                     selected_link=None, title=None, map_background=False, cut=None):
    """The network for the design tab: km labels, failed elements dashed, the fibres
    ``cut`` after planning (one (u, v) or a list) in dashed red with a red X."""
    base.draw_network(ax, G, label_mode=None, show_names=show_names, selected_node=selected_node,
                      selected_link=selected_link, title=title, map_background=map_background)
    if show_lengths and G.number_of_edges() <= 80:
        length_labels(ax, G)
    _roomy(ax, G)
    fibres = _cut_list(G, cut)
    if fibres:
        from .analysis import cut_name
        _mark_cut(ax, G, fibres)
        names = ", ".join(cut_name(e) for e in fibres)
        note = "\n(A-B: both directions, A>B: one)" if any(">" in cut_name(e) for e in fibres) else ""
        ax.legend(handles=[Line2D([0], [0], marker="$✗$", color=CUT_COLOR, ls=(0, (3, 2)), lw=2,
                                  markerfacecolor=CUT_COLOR, markeredgecolor=CUT_COLOR, markersize=12,
                                  label=f"cut AFTER planning: {names}{note}")],
                  loc="lower right", fontsize=base.fs(7), framealpha=0.85)


def _roomy(ax, G):
    """A little more room around the nodes (labels and curved links stay inside)."""
    if G.number_of_nodes() > 1:
        ax.margins(0.13)
        ax.autoscale_view()
        y0, y1 = ax.get_ylim()                     # more room above and below: node names stay inside
        ax.set_ylim(y0 - 0.06 * (y1 - y0), y1 + 0.10 * (y1 - y0))
        if ax.get_adjustable() == "datalim":       # keep these limits (datalim would cut them back)
            ax.set_aspect("equal", adjustable="box")


def _wrap_title(title, width=46):
    """A long title (algorithm name + network + status) on two lines, not cut by the axes."""
    import textwrap
    return "\n".join(textwrap.wrap(str(title), width)) if title and len(str(title)) > width else title


def draw_eon_map(ax, G, link_rows=None, num_slots=320, *, working=(), backup=(), regenerators=(),
                 cut=None, down_paths=(), show_names=True, selected_link=None, title=None,
                 map_background=False):
    """Results map, drawn as in the wavelength tool (pynet2plan.plotting.draw_network): links colored
    by utilization (slots used / num_slots), the working paths highlighted, the backup paths in
    purple, the 3R nodes as squares "3R×n", the cut fibres dashed with a red X (0 % used); one legend
    ("link utilization") under the map."""
    from collections import Counter
    from .analysis import cut_links as _cut_links
    H = G.copy()
    for u, v in H.edges:
        H.edges[u, v]["capacity"] = int(num_slots)
        H.edges[u, v]["fibers"] = 1
    fibres = _cut_list(G, cut)
    for a, b in _cut_links(fibres):                             # a cut fibre carries nothing
        if H.has_edge(a, b):
            H.edges[a, b]["up"] = False
    used = {(r["origin"], r["destination"]): r.get("slots_used") or 0 for r in (link_rows or [])}
    regs = Counter(n for n in regenerators if n in G)
    base.draw_network(ax, H, link_used=used, highlight_paths=list(working), backup_paths=list(backup),
                      cut_fibres=[(e[0], e[1]) for e in fibres], regenerators=dict(regs),
                      selected_link=selected_link, show_names=show_names, label_mode="util",
                      title=title, map_background=map_background)


def _legend(ax, handles=None, ncol=3, title=None):
    """The legend of a chart. Alone in its figure (one chart per page, with constrained layout) it
    goes under the chart, in rows: the plot keeps the whole width and no line is hidden. Several
    charts in one figure: inside each chart."""
    fig = ax.figure
    if handles is None:
        handles, labels = ax.get_legend_handles_labels()
    else:
        labels = [h.get_label() for h in handles]
    if not handles:
        return None
    if len(fig.axes) == 1 and fig.get_layout_engine() is not None:
        return fig.legend(handles, labels, loc="outside lower center", ncol=min(ncol, len(handles)),
                          fontsize=base.fs(10.5), title=title, title_fontsize=base.fs(10.5), frameon=False)
    return ax.legend(handles, labels, fontsize=base.fs(9), loc="best", title=title, framealpha=0.85)


def plot_spectrum_grid(ax, spectrum_rows, link_rows, num_slots, *, highlight_lightpaths=(),
                       highlight_demand=None, max_links=80, only_used=False, slot_width=None):
    """One row per link, one column per slot: the color is the data rate of the
    lightpath using the slot (white = free); highlighted lightpaths are outlined."""
    import numpy as np
    from matplotlib.patches import Rectangle
    ax.clear()
    links = [(r["origin"], r["destination"]) for r in link_rows if r.get("up", True)]
    if only_used:
        used = {(r["origin"], r["destination"]) for r in spectrum_rows}
        links = [l for l in links if l in used] or links
    links = links[:max_links]
    if not links or num_slots <= 0:
        ax.text(0.5, 0.5, "No links", ha="center", va="center", transform=ax.transAxes)
        return
    index = {l: k for k, l in enumerate(links)}
    rates = sorted({int(r["rate_gbps"]) for r in spectrum_rows if r.get("rate_gbps") not in ("", None)})
    colors = _rate_colors(rates or [100])
    img = np.ones((len(links), num_slots, 4))
    for r in spectrum_rows:
        k = index.get((r["origin"], r["destination"]))
        if k is None or r.get("rate_gbps") in ("", None):
            continue
        s, n = int(r["start"]), int(r["slots"])
        img[k, max(0, s):min(num_slots, s + n)] = colors[int(r["rate_gbps"])]
        if r.get("role") == "backup":
            img[k, max(0, s):min(num_slots, s + n), 3] = 0.55
    ax.imshow(img, aspect="auto", interpolation="nearest", extent=(-0.5, num_slots - 0.5, len(links) - 0.5, -0.5))
    hl = set(highlight_lightpaths)
    for r in spectrum_rows:
        k = index.get((r["origin"], r["destination"]))
        if k is None:
            continue
        if r.get("lightpath_id") in hl or (highlight_demand is not None
                                          and str(r.get("demand_id")) == str(highlight_demand)):
            ax.add_patch(Rectangle((int(r["start"]) - 0.5, k - 0.5), int(r["slots"]), 1, fill=False,
                                   ec="red", lw=1.8, zorder=5))
    _link_ticks(ax, [f"{u}→{v}" for u, v in links])
    ax.set_xlim(-0.5, num_slots - 0.5)
    if slot_width:                                    # the same picture, the axis in GHz
        total = num_slots * slot_width
        step = next((s for s in (50, 100, 250, 500, 1000, 2000, 5000) if total / s <= 9), 10000)
        ghz = [k * step for k in range(int(total // step) + 1)]
        ax.set_xticks([g / slot_width - 0.5 for g in ghz])
        ax.set_xticklabels([f"{g:g}" for g in ghz])
        ax.set_xlabel(f"frequency (GHz, 0..{total:g})", fontsize=base.fs(12.5))
    else:
        ax.set_xlabel(f"frequency slot (0..{num_slots - 1})", fontsize=base.fs(12.5))
    ax.set_ylabel("link", fontsize=base.fs(12.5))
    ax.tick_params(axis="x", labelsize=base.fs(11))
    ax.set_title("Spectrum of every link", fontsize=base.fs(13))
    _legend(ax, [Patch(color=colors[r], label=f"{r}G") for r in rates], ncol=min(len(rates), 5),
            title="data rate of the lightpath (white = free slot, faded = backup)")


def _link_ticks(ax, labels):
    """One y label per link, but only every k-th one when the rows are too thin
    to read (many links in a small window): no overlapping text."""
    fig = ax.figure
    height_px = ax.get_position().height * fig.get_figheight() * fig.dpi
    row_px = height_px / max(1, len(labels))
    step = 1 if row_px >= 11 else -(-11 // max(1, int(row_px)))
    ys = list(range(0, len(labels), step))
    ax.set_yticks(ys)
    ax.set_yticklabels([labels[i] for i in ys], fontsize=base.fs(11) if row_px >= 15 else base.fs(9))


def plot_link_occupancy(ax, link_rows, num_slots, max_bars=60, slot_width=None):
    """Bars: the slots used on every link (most used first), and the end of the band;
    with ``slot_width`` the same in GHz."""
    ax.clear()
    w = slot_width or 1
    rows = sorted([r for r in link_rows if r.get("up", True)], key=lambda r: -(r.get("slots_used") or 0))
    rows = rows[:max_bars]
    ys = list(range(len(rows)))
    ax.barh(ys, [(r.get("slots_used") or 0) * w for r in rows],
            color=[base.util_color((r.get("slots_used") or 0) / num_slots if num_slots else 0) for r in rows])
    _link_ticks(ax, [f"{r['origin']}→{r['destination']}" for r in rows])
    ax.invert_yaxis()
    ax.axvline(num_slots * w, color="#c62828", ls="--", lw=1)
    ax.set_xlim(0, num_slots * w * 1.05)
    ax.set_xlabel(f"spectrum used on the link (GHz, of {num_slots * w:g})" if slot_width
                  else f"slots used on the link (of {num_slots})", fontsize=base.fs(12.5))
    ax.set_ylabel("link (most used first)", fontsize=base.fs(12.5))
    ax.tick_params(axis="x", labelsize=base.fs(11))
    ax.set_title("Spectrum occupancy per link (red dashes: end of the band)", fontsize=base.fs(13))
    ax.grid(axis="x", alpha=0.3)


def plot_cuts(ax, cut_rows, served, selected=None):
    """One horizontal bar per fibre: what happens to the served demands when that fibre alone is
    cut (not affected, switched to the backup path, DOWN). The fibre names are on the y axis,
    where long names (cities) stay readable."""
    ax.clear()
    if not cut_rows:
        ax.text(0.5, 0.5, "No fibres", ha="center", va="center", transform=ax.transAxes)
        return
    ys = list(range(len(cut_rows)))
    down = [r["demands_down"] for r in cut_rows]
    sw = [r["demands_switched"] for r in cut_rows]
    alive = [served - d for d in down]
    chosen = {selected} if isinstance(selected, str) else set(selected or ())     # one fibre or several
    alpha = [1.0 if not chosen or r["fibre"] in chosen else 0.35 for r in cut_rows]
    for y, a, d, s_, al in zip(ys, alive, down, sw, alpha):
        ax.barh(y, a - s_, color="#1565c0", alpha=al)
        ax.barh(y, s_, left=a - s_, color=BACKUP_COLOR, alpha=al)
        ax.barh(y, d, left=a, facecolor="white", edgecolor=DOWN_COLOR, hatch="///", alpha=al)
    ax.axvline(served, color="#424242", ls="--", lw=1.2)
    _link_ticks(ax, [r["fibre"] for r in cut_rows])
    ax.invert_yaxis()
    ax.set_xlabel("number of demands", fontsize=base.fs(12.5))
    ax.set_ylabel("fibre cut", fontsize=base.fs(12.5))
    ax.tick_params(axis="x", labelsize=base.fs(11))
    ax.set_title("After each fibre cut (one at a time)", fontsize=base.fs(13))
    _legend(ax, [Patch(color="#1565c0", label="not affected"),
                 Patch(color=BACKUP_COLOR, label="switched to the backup path"),
                 Patch(facecolor="white", edgecolor=DOWN_COLOR, hatch="///", label="DOWN"),
                 Line2D([0], [0], color="#424242", ls="--", lw=1.2, label=f"served before the cut ({served})")],
            ncol=2)
    ax.set_xlim(0, max(served, 1) * 1.05)
    ax.grid(axis="x", alpha=0.3)


def plot_reach(ax, table, longest_km=None, title=None):
    """One bar per transponder type, as long as its reach (the notebook's §4)."""
    ax.clear()
    ys = list(range(len(table)))
    color = [("#2e7d32" if longest_km is None or tp.reach >= longest_km else "#c62828") for tp in table]
    ax.barh(ys, [tp.reach for tp in table], color=color, height=0.62)
    for y, tp in zip(ys, table):
        ax.text(tp.reach, y, f" {tp.reach:g} km", va="center", fontsize=base.fs(11))
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{tp.name} ({tp.slots} slots, {tp.gbps_per_slot:g} Gb/s per slot)" for tp in table],
                       fontsize=base.fs(11))
    ax.invert_yaxis()
    if longest_km:
        ax.axvline(longest_km, color="#263238", lw=1.4)
        ax.set_xlim(0, max([tp.reach for tp in table] + [longest_km]) * 1.18)
        right = longest_km > 0.6 * ax.get_xlim()[1]          # keep the label inside the axes
        ax.text(longest_km, len(table) - 0.45, (f"longest shortest path: {longest_km:.0f} km "
                                                if right else f" longest shortest path: {longest_km:.0f} km"),
                fontsize=base.fs(11), fontweight="bold", va="top", ha="right" if right else "left")
    else:
        ax.set_xlim(0, max(tp.reach for tp in table) * 1.18)
    ax.set_xlabel("reach (km)", fontsize=base.fs(12.5))
    ax.set_ylabel("transponder type", fontsize=base.fs(12.5))
    ax.tick_params(axis="x", labelsize=base.fs(11))
    ax.set_title(title or "Reach of each transponder type\n(green: reaches every shortest path without 3R)",
                 fontsize=base.fs(13))
    ax.grid(axis="x", alpha=0.3)


def plot_reach_islands(ax, G, transponder, islands):
    """The network as one transponder type sees it: usable links (length <=
    reach) in green; node color = island."""
    import matplotlib
    ax.clear()
    ax.set_xticks([])
    ax.set_yticks([])
    tab = matplotlib.colormaps["tab10"]
    color_of = {n: tab(k % 10) for k, isl in enumerate(islands) for n in isl}
    done = set()
    for u, v, a in G.edges(data=True):
        if frozenset((u, v)) in done:
            continue
        done.add(frozenset((u, v)))
        ok = float(a["length"]) <= transponder.reach
        pu, pv = G.nodes[u], G.nodes[v]
        ax.plot([pu["x"], pv["x"]], [pu["y"], pv["y"]], color="#2e7d32" if ok else "#c62828",
                lw=4 if ok else 1.5, ls="-" if ok else "--", zorder=1)
        if G.number_of_edges() <= 80:
            ax.text((pu["x"] + pv["x"]) / 2, (pu["y"] + pv["y"]) / 2, f"{float(a['length']):.0f}", fontsize=base.fs(11),
                    ha="center", va="center", bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none"))
    xs = [a["x"] for _, a in G.nodes(data=True)]
    ys = [a["y"] for _, a in G.nodes(data=True)]
    short = all(len(str(n)) <= 2 for n in G.nodes)              # A..F fit inside the circle
    ax.scatter(xs, ys, s=300 if short else 120, c=[color_of.get(n, "#9e9e9e") for n in G.nodes],
               edgecolors="white", zorder=3)
    for n, a in G.nodes(data=True):
        if short:
            ax.annotate(str(n), (a["x"], a["y"]), ha="center", va="center", fontsize=base.fs(12), color="white",
                        fontweight="bold", zorder=4)
        elif G.number_of_nodes() <= 40:
            ax.annotate(str(n), (a["x"], a["y"]), textcoords="offset points", xytext=(0, 8), ha="center",
                        fontsize=base.fs(11), zorder=4, bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.7))
    pairs = sum(len(i) * (len(i) - 1) // 2 for i in islands)
    n = G.number_of_nodes()
    ax.set_title(f"{transponder.name}, reach {transponder.reach:g} km: {len(islands)} island(s)\n"
                 f"{pairs}/{n * (n - 1) // 2} node pairs reachable even with unlimited 3R", fontsize=base.fs(13))
    ax.set_aspect("equal", adjustable="datalim")
    ax.margins(0.1)


# ----------------------------------------------------------------------
# Sweeps and cost
# ----------------------------------------------------------------------
SWEEP_METRICS = [("served_demands", "demands served"), ("total_slots_used", "total slots used (summed over the links)"),
                 ("hardware_cost", "hardware cost (in transponder prices)"), ("regenerators", "3R regenerators")]

#: y axis of each metric of the sweep charts
SWEEP_Y = {"served_demands": "demands served", "served_after_cut": "demands served",
           "total_slots_used": "slots used", "hardware_cost": "cost (transponders)",
           "regenerators": "number of 3R", "transponders": "transponders",
           "blocked_demands": "blocked demands", "max_slot_index": "highest slot + 1"}
#: x axis of the sweeps
SWEEP_X = {"num_demands": "number of demands", "num_slots": "capacity of every link, C (slots of 12.5 GHz)",
           "reach_scale": "every reach × factor", "none": "run", "run": "run",
           "max_cost": "transponder budget (3R = 2 transponders; cost 1 each)"}


def sweep_metrics(rows, slot_width=None) -> list:
    """The charts of a sweep: (key, title, y label), one chart per metric."""
    cut = next((r.get("cut_fibre") for r in rows if r.get("cut_fibre")), None)
    metrics = SWEEP_METRICS if not cut else [
        ("served_demands", "demands served (as planned)"),
        ("served_after_cut", f"demands served after the cut{'s' if ',' in str(cut) else ''} {cut}"),
        ("total_slots_used", "total slots used (summed over the links)"),
        ("hardware_cost", "hardware cost (in transponder prices)"), ("regenerators", "3R regenerators")]
    out = []
    for key, title in metrics:
        y = SWEEP_Y.get(key, title)
        if slot_width and key == "total_slots_used":
            title, y = "total spectrum used (GHz × links)", "GHz (× links)"
        out.append((key, title, y))
    return out


def series_key(row) -> str:
    f = str(row.get("algorithm_file") or "")
    stem = os.path.splitext(os.path.basename(f))[0] if f else str(row.get("algorithm", "?"))
    if row.get("algorithm_origin") == "solutions":
        stem += " [ref]"
    params = row.get("parameters") or ""
    axis = row.get("sweep_axis") or ""             # the parameter swept (max_cost): the x, not a series
    return f"{stem} {' '.join(p for p in params.split('; ') if p and not p.startswith(axis + '='))}".strip()


#: Legend names of the given algorithms (the others keep the name of their file).
#: The same names as in the legends of the wavelength tool (protection lab, pynet2plan).
LEGEND_NAMES = {"rsa_greedy": "greedy no protection", "rsa_1plus1_two_step": "greedy 1+1 protection",
                "rsa_1plus1_ilp": "protection route formulation", "rsa_3r": "greedy 3R",
                "rsa_3r_budget": "greedy 3R budget"}


def _short_labels(keys):
    """Legend names: the name of the algorithm, with only the parameters that differ between the
    series of the same algorithm (k = 2 and k = 4 of greedy), not those that every series shares."""
    split = {}
    for k in keys:
        words = k.split(" ")
        name = [w for w in words if "=" not in w]
        name[0] = LEGEND_NAMES.get(name[0], name[0])
        split[k] = (" ".join(name), [w for w in words if "=" in w])
    out = {}
    for k, (name, params) in split.items():
        same = [p for n, p in split.values() if n == name]
        common = set.intersection(*(set(p) for p in same))
        shown = [w for w in params if w not in common]
        out[k] = name + (f" ({', '.join(shown)})" if shown else "")      # as in the wavelength tool
    return out


def plot_sweep(axes, rows, axis_label=None, metrics=None, slot_width=None):
    """One chart per metric (one Axes each), one line per algorithm/parameters.
    ``metrics``: (key, title) or (key, title, y label); default :func:`sweep_metrics`."""
    for ax in axes:
        ax.clear()
    metrics = [m if len(m) == 3 else (m[0], m[1], SWEEP_Y.get(m[0], m[1]))
               for m in (metrics or sweep_metrics(rows, slot_width))]
    axis = axis_label or (rows[0].get("sweep_axis") if rows else "") or "run"
    xlabel = SWEEP_X.get(axis, axis)
    series: dict = {}
    for i, r in enumerate(rows):
        if r.get("status") not in ("FEASIBLE", "BLOCKING", "OPTIMAL"):
            continue
        x = r.get("sweep_value")
        x = i if x in ("", None) else float(x)
        series.setdefault(series_key(r), []).append((x, r))
    markers = "osD^vP*Xh"
    short = _short_labels(list(series)) if series else {}
    for ax, (key, label, ylabel) in zip(axes, metrics):
        for k, (name, pts) in enumerate(series.items()):
            pts = sorted(pts, key=lambda p: p[0])
            scale = slot_width if (slot_width and key == "total_slots_used") else 1
            ax.plot([p[0] for p in pts], [float(p[1].get(key) or 0) * scale for p in pts], marker=markers[k % 9],
                    ms=4, lw=1.5, color=f"C{k % 10}", label=short.get(name, name))
        if key in ("served_demands", "served_after_cut") and rows and axis == "num_demands":
            xs = sorted({float(r["sweep_value"]) for r in rows if r.get("sweep_value") not in ("", None)})
            ax.plot(xs, xs, ":", color="#9e9e9e", label="offered (all demands)")
        ax.set_title(label, fontsize=base.fs(13))
        ax.set_xlabel(xlabel, fontsize=base.fs(12.5))
        ax.set_ylabel(ylabel, fontsize=base.fs(12.5))
        ax.grid(alpha=0.3)
        ax.tick_params(labelsize=base.fs(11))
        if series:
            _legend(ax, ncol=2)


#: the metrics of the sweep chart (the combobox of the Sweep tab, as in the wavelength tool)
SWEEP_CHOICES = [("total_slots_used", "slots used"), ("blocked_demands", "blocked demands"),
                 ("served_demands", "demands served"), ("served_after_cut", "demands served after the cut"),
                 ("hardware_cost", "hardware cost"), ("transponders", "transponders used by the plan"),
                 ("regenerators", "3R regenerators")]


def plot_sweep_metric(ax, rows, metric="total_slots_used", metric_label=None, slot_width=None, compact=True):
    """The sweep chart of the wavelength tool (pynet2plan.plotting.plot_sweep), for the EON sweeps:
    one metric against the sweep axis, one curve per algorithm/parameters (color, marker and line
    style of base.series_style), x on the axis where a run has no valid solution, the legend above
    the chart."""
    ax.clear()
    for old in list(ax.figure.legends):
        old.remove()
    if metric == "transponders" and any(r.get("transponders_by_rate") for r in rows):
        return _plot_transponder_bars(ax, rows, metric_label, slot_width, compact)
    axis = (rows[0].get("sweep_axis") if rows else "") or "run"
    xlabel = SWEEP_X.get(axis, axis)
    series, infeasible = {}, {}
    for i, r in enumerate(rows):
        key = series_key(r)
        x = r.get("sweep_value")
        x = float(i) if x in ("", None) else float(x)
        if axis == "num_slots" and slot_width:          # Lab 4, part 1: the capacity in GHz
            x *= slot_width
        series.setdefault(key, [])
        if r.get("status") in ("FEASIBLE", "BLOCKING", "OPTIMAL") and r.get(metric) not in ("", None):
            y = float(r.get(metric) or 0)
            if slot_width and metric == "total_slots_used":
                y *= slot_width
            series[key].append((x, y))
        else:
            infeasible.setdefault(key, []).append(x)
    keys = list(series)
    names = _short_labels(keys) if keys else {}
    style = {k: base.series_style(i) for i, k in enumerate(keys)}
    small = 0.9 if compact else 1.0
    f_title, f_label, f_tick, f_legend = (base.fs(12 * small), base.fs(11 * small), base.fs(10 * small),
                                          base.fs(9.5 * small))
    with_bad = [k for k in keys if infeasible.get(k)]
    for key in keys:
        pts = sorted(series[key])
        if pts:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], ms=6.5, lw=2, mew=1.4, label=names[key], **style[key])
        bad = infeasible.get(key, [])
        if bad:
            ax.plot(bad, [0.03 * with_bad.index(key)] * len(bad), ls="none", marker="x", ms=7.5, mew=2,
                    color=style[key]["color"], transform=ax.get_xaxis_transform(), clip_on=False, zorder=5,
                    label=None if pts else f"{names[key]} (no valid solution)")
    if metric in ("served_demands", "served_after_cut") and axis == "num_demands" and rows:
        xs = sorted({float(r["sweep_value"]) for r in rows if r.get("sweep_value") not in ("", None)})
        ax.plot(xs, xs, ":", color="#9e9e9e", label="offered (all demands)")
    if axis == "num_slots" and slot_width:
        xlabel = "capacity of every link, C (GHz)"
    ax.set_xlabel(xlabel, fontsize=f_label)
    ylabel = metric_label or dict(SWEEP_CHOICES).get(metric, metric)
    if slot_width and metric == "total_slots_used":
        ylabel = "GHz used (× links)"
    ax.set_ylabel(ylabel, fontsize=f_label)
    title = ("Objective vs. link capacity" if axis == "num_slots" else
             "Objective vs. transponder budget" if axis == "max_cost" else f"Objective vs. {xlabel}")
    budget = next((r.get("cost_budget") for r in rows if r.get("cost_budget") not in ("", None)), None)
    if budget is not None and axis != "max_cost":
        title += f" (transponder budget {float(budget):g})"
    ax.set_title(title, fontsize=f_title)
    ax.tick_params(labelsize=f_tick)
    handles, labels = ax.get_legend_handles_labels()
    if infeasible:
        handles.append(Line2D([0], [0], ls="none", marker="x", color="#424242", mew=2, ms=8))
        labels.append("× on the axis: no valid solution")
    if labels:
        ncol = 2 if len(labels) > 2 else len(labels)
        nrows = -(-len(labels) // ncol)
        ax.legend(handles, labels, fontsize=f_legend, loc="lower left", bbox_to_anchor=(0.0, 1.01), ncol=ncol,
                  frameon=False, borderaxespad=0.0, handlelength=2.6, columnspacing=1.5)
        ax.set_title(title, fontsize=f_title, pad=6 + nrows * 2.0 * f_legend)
    ax.grid(alpha=0.3)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


HATCHES = ["", "//", "..", "xx", "\\\\", "oo", "--", "++"]


def _plot_transponder_bars(ax, rows, metric_label=None, slot_width=None, compact=True):
    """The transponders used by every plan of the sweep: one bar per algorithm at every x, its
    height the number of transponders, split by data rate (one color per rate, RATE_COLORS);
    the algorithms are told apart by their place and hatching."""
    axis = (rows[0].get("sweep_axis") if rows else "") or "run"
    xlabel = SWEEP_X.get(axis, axis)
    if axis == "num_slots" and slot_width:
        xlabel = "capacity of every link, C (GHz)"
    keys, xs, data = [], [], {}
    for i, r in enumerate(rows):
        key = series_key(r)
        if key not in keys:
            keys.append(key)
        x = r.get("sweep_value")
        x = float(i) if x in ("", None) else float(x)
        if axis == "num_slots" and slot_width:
            x *= slot_width
        if x not in xs:
            xs.append(x)
        if r.get("status") in ("FEASIBLE", "BLOCKING", "OPTIMAL"):
            data[key, x] = {float(k): v for k, v in (r.get("transponders_by_rate") or {}).items()}
    xs.sort()
    names = _short_labels(keys)
    rates = sorted({k for v in data.values() for k in v})
    colors = _rate_colors(rates)
    n = len(keys)
    pos = range(len(xs))                                   # one group of bars per x, evenly spaced
    width = 0.8 / max(n, 1)
    small = 0.9 if compact else 1.0
    f_title, f_label, f_tick, f_legend = (base.fs(12 * small), base.fs(11 * small), base.fs(10 * small),
                                          base.fs(9 * small))
    for j, key in enumerate(keys):
        offs = [p - 0.4 + width * (j + 0.5) for p in pos]
        bottom = [0.0] * len(xs)
        for rate in rates:
            h = [data.get((key, x), {}).get(rate, 0) for x in xs]
            ax.bar(offs, h, width * 0.92, bottom=bottom, color=colors[rate], edgecolor="white", linewidth=0.6,
                   hatch=HATCHES[j % len(HATCHES)])
            bottom = [b + v for b, v in zip(bottom, h)]
        for o, x, b in zip(offs, xs, bottom):
            if (key, x) not in data:
                ax.text(o, 0, "×", ha="center", va="bottom", color="#424242", fontsize=f_label)
            elif n <= 4 and len(xs) <= 8:
                ax.text(o, b, f"{b:g}", ha="center", va="bottom", fontsize=f_tick * 0.85, color=base.TEXT_COLOR)
    ax.set_xticks(list(pos))
    ax.set_xticklabels([f"{x:g}" for x in xs], fontsize=f_tick)
    ax.set_xlabel(xlabel, fontsize=f_label)
    ax.set_ylabel(metric_label or "transponders used by the plan", fontsize=f_label)
    ax.tick_params(labelsize=f_tick)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    handles = [Patch(facecolor=colors[r], label=f"{r:g}G") for r in rates]
    if n > 1:
        handles += [Patch(facecolor="white", edgecolor="#424242", hatch=HATCHES[j % len(HATCHES)], label=names[k])
                    for j, k in enumerate(keys)]
    if any((k, x) not in data for k in keys for x in xs):
        handles.append(Line2D([0], [0], ls="none", marker="x", color="#424242", label="× no valid solution"))
    title = "Transponders used by the plan, by data rate"
    ax.set_title(title, fontsize=f_title)
    if handles:
        ncol = 4 if len(handles) > 6 else 3
        nrows = -(-len(handles) // ncol)
        ax.legend(handles=handles, fontsize=f_legend, loc="lower left", bbox_to_anchor=(0.0, 1.01), ncol=ncol,
                  frameon=False, borderaxespad=0.0, handlelength=2.0, columnspacing=1.2)
        ax.set_title(title, fontsize=f_title, pad=6 + nrows * 2.0 * f_legend)


def plot_cost_lines(ax, options, c_max=0.5):
    """Total cost = hardware + C_SLOT × slots, for each option (label, hardware, slots),
    as the price of a slot goes from 0 to ``c_max``; break-even points marked."""
    import numpy as np
    from .analysis import break_even
    ax.clear()
    prices = np.linspace(0, c_max, 101)
    for k, (label, hw, slots) in enumerate(options):
        ax.plot(prices, hw + prices * slots, lw=2.2, color=f"C{k % 10}",
                label=f"{label}: {hw:g} + C_SLOT × {slots:g}")
    for i in range(len(options)):
        for j in range(i + 1, len(options)):
            be = break_even(options[i][1], options[i][2], options[j][1], options[j][2])
            if be is not None and be <= c_max:
                ax.axvline(be, color="#616161", ls="--", lw=1)
                ax.text(be, ax.get_ylim()[0], f" break-even {be:.3g}", fontsize=base.fs(11), va="bottom", rotation=90)
    ax.set_xlabel("C_SLOT: price of one slot (in transponders)", fontsize=base.fs(12.5))
    ax.set_ylabel("total cost (transponders)", fontsize=base.fs(12.5))
    ax.tick_params(labelsize=base.fs(11))
    ax.set_title("Total cost = hardware + C_SLOT × slots", fontsize=base.fs(13))
    ax.grid(alpha=0.3)
    ax.legend(fontsize=base.fs(11), loc="upper left")


def plot_chain(ax_hw, ax_slots, rows):
    """Long reach vs fast types + 3R over growing distances: hardware cost on ``ax_hw``, slots
    on ``ax_slots`` (either may be None: one chart per page)."""
    km = [r["km"] for r in rows]
    charts = [(ax, key, title, ylabel) for ax, key, title, ylabel in (
        (ax_hw, "hw", "hardware cost: 3R costs more", "cost (transponders)"),
        (ax_slots, "slots", "slots used: long reach costs more", "slots (× links)"))
        if ax is not None]
    for ax, key, title, ylabel in charts:
        ax.clear()
        for suffix, label, color in (("long_reach", "long reach, no 3R", "#c62828"),
                                     ("3r", "fast types + 3R", "#2e7d32")):
            k = f"{key}_{suffix}"
            ax.plot(km, [r[k] if r[k] is not None else float("nan") for r in rows], "o-",
                    color=color, label=label, ms=4)
        ax.set_title(title, fontsize=base.fs(13))
        ax.set_xlabel("path length (km)", fontsize=base.fs(12.5))
        ax.tick_params(labelsize=base.fs(11))
        ax.set_ylabel(ylabel, fontsize=base.fs(12.5))
        ax.grid(alpha=0.3)
        ax.legend(fontsize=base.fs(11))


def save_run_figures(folder: str, dpi: int = 130) -> list:
    """map.png, spectrum.png, cuts.png (or sweep.png) in an EON result folder."""
    import matplotlib
    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    from .results import is_eon_sweep_folder, load_run, load_sweep
    out = []
    if is_eon_sweep_folder(folder):
        sw = load_sweep(folder)
        ms = sweep_metrics(sw.rows)
        nrows = -(-len(ms) // 2)
        fig, axes = plt.subplots(nrows, 2, figsize=(12, 4 * nrows), squeeze=False)
        plot_sweep(list(axes.flat), sw.rows, metrics=ms)
        for ax in list(axes.flat)[len(ms):]:
            ax.set_axis_off()
        fig.tight_layout()
        p = os.path.join(folder, "sweep.png")
        fig.savefig(p, dpi=dpi)
        plt.close(fig)
        return [p]
    run = load_run(folder)
    fig, ax = plt.subplots(figsize=(9, 8))
    draw_eon_map(ax, run.G, run.links, run.num_slots, title=run.title)
    p = os.path.join(folder, "map.png")
    fig.savefig(p, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    out.append(p)
    fig, ax = plt.subplots(figsize=(13, max(3, 0.22 * len(run.links) + 1.2)))
    plot_spectrum_grid(ax, run.spectrum, run.links, run.num_slots)
    fig.tight_layout()
    p = os.path.join(folder, "spectrum.png")
    fig.savefig(p, dpi=dpi)
    plt.close(fig)
    out.append(p)
    fig, ax = plt.subplots(figsize=(9, 4))
    plot_cuts(ax, run.cuts, int(run.summary.get("served_demands") or 0))
    fig.tight_layout()
    p = os.path.join(folder, "cuts.png")
    fig.savefig(p, dpi=dpi)
    plt.close(fig)
    out.append(p)
    return out
