#!/usr/bin/env python3
"""
Figures of the lab handouts drawn with TikZ and PGFPlots
========================================================

Writes one standalone LaTeX file per figure of the handouts. The data come
from the files in data/ (handout 2) and from the JSON files that the lab
scripts save next to their own figures (handouts 3 and 4, in
results/lab1_first_ilp/ and results/lab2_unsplittable/), so that the printed
figures show the same values as the console output of the scripts.

Run it from the root of the project, after the lab scripts:

    python tools/lab_docs/tikz_figures.py --out docs/lab/build/tikz

tools/lab_docs/build.py compiles the files with pdflatex and converts them to
SVG for the handouts; the .tex and .pdf files are kept in
docs/lab/figures/tikz/ (e.g. for slides).
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import sys
from itertools import islice

ROOT = os.getcwd()
sys.path.insert(0, ROOT)

PREAMBLE = r"""\documentclass[border=2pt]{standalone}
% Computer Modern, the font of the handouts (pdflatex)
\usepackage{amsmath}
\usepackage{tikz}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
\usetikzlibrary{arrows.meta,calc}
\definecolor{cA}{HTML}{2A78D6}
\definecolor{cB}{HTML}{EB6834}
\definecolor{cC}{HTML}{1BAF7A}
\definecolor{cD}{HTML}{EDA100}
\definecolor{cE}{HTML}{E87BA4}
\definecolor{nodeblue}{HTML}{1565C0}
\definecolor{linkgray}{HTML}{546E7A}
\definecolor{lightgray}{HTML}{CFD8DC}
\definecolor{txt}{HTML}{263238}
\definecolor{band}{HTML}{EEEEEE}
\definecolor{uUnused}{HTML}{BDBDBD}
\definecolor{uLow}{HTML}{2E7D32}
\definecolor{uMid}{HTML}{F9A825}
\definecolor{uHigh}{HTML}{EF6C00}
\definecolor{uFull}{HTML}{C62828}
\definecolor{uOver}{HTML}{7B1FA2}
\tikzset{
  nd/.style={circle, fill=nodeblue, draw=white, line width=0.7pt, minimum size=#1, inner sep=0pt},
  nd/.default=3.2mm,
  nlab/.style={font=\footnotesize\bfseries, text=txt, inner sep=1pt},
  lbl/.style={font=\scriptsize, text=txt, fill=white, fill opacity=0.85, text opacity=1, inner sep=0.7pt},
  arr/.style={-{Stealth[length=1.9mm, width=1.5mm]}},
}
\pgfplotsset{
  lab/.style={
    scale only axis, axis lines*=left, grid=major, grid style={black!12},
    tick label style={font=\small}, label style={font=\normalsize},
    ylabel style={align=center},
    legend style={draw=none, fill=none, font=\small},
    legend cell align=left, tick align=outside, axis line style={black!60},
    every axis plot/.append style={line width=1.1pt},
  },
  % the series differ in color, marker and line style (readable in black and white);
  % the second series has hollow markers, visible where the two curves overlap
  s1/.style={cA, solid, mark=*, mark size=1.7pt},
  s2/.style={cB, densely dashed, mark=square*, mark size=1.6pt, mark options={solid, fill=white}},
  s3/.style={cC, dashdotted, mark=diamond*, mark size=2.1pt, mark options={solid}},
  s4/.style={cD, densely dotted, mark=triangle*, mark size=2.1pt, mark options={solid, fill=white}},
  s5/.style={cE, dashed, mark=triangle*, mark size=2.1pt, mark options={solid, rotate=180}},
  ebars/.style={error bars/.cd, y dir=both, y explicit,
    error bar style={solid, line width=0.9pt}, error mark options={solid, rotate=90, mark size=2.2pt}},
}
\begin{document}
"""
END = "\n\\end{document}\n"

#: link utilization classes of the GUI (pynet2plan.plotting.UTIL_CLASSES)
UTIL = [(0.5, "uLow", r"$\le 50\,\%$"), (0.8, "uMid", r"50--80\,\%"), (0.999999, "uHigh", r"80--100\,\%"),
        (1.000001, "uFull", r"100\,\% (full)"), (math.inf, "uOver", r"$>100\,\%$")]


def tex(s) -> str:
    """Text for LaTeX (city names, titles)."""
    s = str(s)
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#"),
                 ("λ", r"$\lambda$"), ("≥", r"$\geq$"), ("–", "--"), ("→", r"$\to$")):
        s = s.replace(a, b)
    return s


def num(v) -> str:
    return f"{round(float(v), 6):g}"


def util_class(used, cap):
    if not used:
        return "uUnused", None
    u = used / cap if cap else math.inf
    for bound, color, _ in UTIL:
        if u <= bound:
            return color, u
    return "uOver", u


# ----------------------------------------------------------------------
# networks
# ----------------------------------------------------------------------
def layout(nodes, width, height):
    """Node name -> (X, Y) in cm, fitted in width x height (cm) keeping the proportions."""
    xs = [n["x"] for n in nodes]
    ys = [n["y"] for n in nodes]
    dx, dy = (max(xs) - min(xs)) or 1.0, (max(ys) - min(ys)) or 1.0
    s = min(width / dx, height / dy)
    return {n["name"]: ((n["x"] - min(xs)) * s, (n["y"] - min(ys)) * s) for n in nodes}


def node_ids(pos):
    return {name: f"n{k}" for k, name in enumerate(pos)}


def label_angle(pos, name):
    cx = sum(p[0] for p in pos.values()) / len(pos)
    cy = sum(p[1] for p in pos.values()) / len(pos)
    x, y = pos[name]
    a = math.degrees(math.atan2(y - cy, x - cx))
    return round(a / 15) * 15


def draw_nodes(pos, ids, *, names=True, size="3.2mm", fill=None, abbrev=False, font=None):
    out = []
    for name, (x, y) in pos.items():
        style = f"nd={size}" + (f", fill={fill[name]}" if fill and name in fill else "")
        label = ""
        if names and not abbrev:
            label = (f", label={{[nlab{', font=' + font if font else ''}]{label_angle(pos, name)}:"
                     f"{tex(name)}}}")
        text = f"\\textcolor{{white}}{{\\scriptsize\\bfseries {tex(name[:3])}}}" if abbrev else ""
        out.append(f"\\node[{style}{label}] ({ids[name]}) at ({x:.3f},{y:.3f}) {{{text}}};")
    return out


def undirected(links):
    seen, out = set(), []
    for l in links:
        key = frozenset((l["origin"], l["destination"]))
        if key not in seen:
            seen.add(key)
            out.append(l)
    return out


def bend_for(pos, u, v):
    L = math.dist(pos[u], pos[v])
    return max(12, min(40, math.degrees(math.atan(0.30 / (0.375 * max(L, 0.1))))))


def utilization_map(data, width, height, title=None):
    """Directed network: one arc per link, colored by utilization (as in the GUI)."""
    pos = layout(data["nodes"], width, height)
    ids = node_ids(pos)
    lines = [r"\begin{tikzpicture}"]
    lines += draw_nodes(pos, ids)
    present = set()
    for l in data["links"]:
        u, v = l["origin"], l["destination"]
        if not l.get("up", True):
            lines.append(f"\\draw[arr, black!35, densely dashed, line width=0.6pt] ({ids[u]}) to[bend left=14] ({ids[v]});")
            continue
        color, util = util_class(l.get("used", 0), l.get("capacity") or 0)
        present.add(color)
        lw = 0.5 + 1.7 * min(util, 1.0) if util is not None else 0.5
        lab = f" node[lbl, midway] {{{100 * util:.0f}\\%}}" if util else ""
        lines.append(f"\\draw[arr, {color}, line width={lw:.2f}pt] ({ids[u]}) to[bend left={bend_for(pos, u, v):.0f}]"
                     f"{lab} ({ids[v]});")
    if title:
        lines.append(f"\\node[font=\\small, text=txt, anchor=south] at ($(current bounding box.north)+(0,1mm)$) "
                     f"{{{title}}};")
    # legend below the map
    items = [(c, lab) for _, c, lab in UTIL if c in present]
    if items:
        lines.append(r"\coordinate (lg) at ($(current bounding box.south)+(0,-3mm)$);")
        widths = [6 + 1.5 * len(lab.replace("\\", "").replace("$", "")) for _, lab in items]   # mm
        x = -sum(widths) / 2
        for (c, lab), w in zip(items, widths):
            lines.append(f"\\draw[{c}, line width=1.6pt] ($(lg)+({x:.1f}mm,0)$) -- ++(4.5mm,0) "
                         f"node[right, font=\\scriptsize, text=txt, inner sep=1pt] {{{lab}}};")
            x += w
    lines.append(r"\end{tikzpicture}")
    return "\n".join(lines)


def plain_map(nodes, links, width, height, *, edge_labels=None, highlight=(), node_fill=None,
              size="3.2mm", names=True, font=None, title=None, base="linkgray", base_width="1.1pt",
              abbrev=False):
    """Undirected drawing (one line per pair of links), optional highlighted links."""
    pos = layout(nodes, width, height)
    ids = node_ids(pos)
    lines = [r"\begin{tikzpicture}"]
    for name, (x, y) in pos.items():                     # the lines go from centre to centre,
        lines.append(f"\\coordinate (c{ids[name]}) at ({x:.3f},{y:.3f});")   # the nodes are drawn on top
    hl = {frozenset(e[:2]): e[2] for e in highlight}
    for l in undirected(links):
        u, v = l["origin"], l["destination"]
        key = frozenset((u, v))
        if key in hl:
            lines.append(f"\\draw[{hl[key]}, line width=3.2pt, line cap=round] (c{ids[u]}) -- (c{ids[v]});")
        else:
            lab = f" node[lbl, midway] {{{edge_labels[key]}}}" if edge_labels and key in edge_labels else ""
            lines.append(f"\\draw[{base}, line width={base_width}] (c{ids[u]}) --{lab} (c{ids[v]});")
    lines += draw_nodes(pos, ids, size=size, fill=node_fill, names=names, font=font, abbrev=abbrev)
    if title:
        lines.append(f"\\node[font=\\small, text=txt, anchor=south, align=center] at "
                     f"($(current bounding box.north)+(0,0.5mm)$) {{{title}}};")
    lines.append(r"\end{tikzpicture}")
    return "\n".join(lines)


def side_by_side(pictures, gap="6mm"):
    return f"\n\\hspace{{{gap}}}\n".join(pictures)


# ----------------------------------------------------------------------
# handout 2: the NetworkX tour (computed from data/, as in labs/lab1_networkx_tour.py)
# ----------------------------------------------------------------------
def tour_figures():
    import networkx as nx
    from pynet2plan import network, traffic
    G = network.load_topology(os.path.join(ROOT, "data", "topologies", "spain7.json"))
    nodes = [dict(name=n, x=a["x"], y=a["y"]) for n, a in G.nodes(data=True)]
    links = [dict(origin=u, destination=v, length=a["length"]) for u, v, a in G.edges(data=True)]
    figs = {}
    km = {frozenset((l["origin"], l["destination"])): f"{l['length']:.0f}\\,km" for l in links}
    figs["nx_spain7"] = plain_map(nodes, links, 9.0, 7.0, edge_labels=km, size="3.6mm")

    s, t = "Sevilla", "Valencia"
    p_hops = nx.shortest_path(G, s, t)
    p_km = nx.shortest_path(G, s, t, weight="length")
    km_len = nx.path_weight(G, p_km, weight="length")

    def path_edges(p, color):
        return [(a, b, color) for a, b in zip(p[:-1], p[1:])]
    pics = [plain_map(nodes, links, 5.2, 4.4, highlight=path_edges(p_hops, "cB"), base="lightgray",
                      title=f"(a) fewest hops: {len(p_hops) - 1} hops"),
            plain_map(nodes, links, 5.2, 4.4, highlight=path_edges(p_km, "cC"), base="lightgray",
                      title=f"(b) shortest length: {km_len:.0f}\\,km")]
    figs["nx_shortest_paths"] = side_by_side(pics, "10mm")

    s, t, k = "Zaragoza", "Malaga", 3
    paths = list(islice(nx.shortest_simple_paths(G, s, t, weight="length"), k))
    pics = []
    for i, (p, c) in enumerate(zip(paths, ["cA", "cB", "cC"]), 1):
        pics.append(plain_map(nodes, links, 4.9, 4.2, highlight=path_edges(p, c), base="lightgray",
                              size="6mm", abbrev=True,
                              title=f"({'abc'[i - 1]}) path {i}: {len(p) - 1} hops, "
                                    f"{nx.path_weight(G, p, weight='length'):.0f}\\,km"))
    figs["nx_k_shortest_paths"] = side_by_side(pics, "5mm")

    D = traffic.load_traffic(os.path.join(ROOT, "data", "traffic", "spain7_traffic_split_vs_unsplit.csv"), G)
    best = None
    for size in range(1, G.number_of_nodes()):
        for S in itertools.combinations(G.nodes, size):
            S = set(S)
            nl = len(list(nx.edge_boundary(G, S)))
            need = sum(d.traffic for d in D if d.origin in S and d.destination not in S)
            if nl and (best is None or math.ceil(need / nl) > best[0]):
                best = (math.ceil(need / nl), need, nl, S)
    c_min, need, nl, S = best
    inside = set(G) - S
    cut = [(u, v, "cB") for u, v in nx.edge_boundary(G, S)]
    fill = {n: "cC" for n in inside}
    figs["nx_cut"] = plain_map(nodes, links, 9.0, 7.0, highlight=cut, node_fill=fill, size="3.6mm",
                               base="lightgray", base_width="1.3pt")

    generated = [
        ("ring", "nx.cycle\\_graph(8)", nx.cycle_graph(8)),
        ("grid", "nx.grid\\_2d\\_graph(3, 4)", nx.grid_2d_graph(3, 4)),
        ("Waxman", "nx.waxman\\_graph(12, seed=7)", nx.waxman_graph(12, beta=0.7, alpha=0.35, seed=7)),
        ("random", "nx.gnm\\_random\\_graph(10, 16, seed=3)", nx.gnm_random_graph(10, 16, seed=3)),
    ]
    pics = []
    for kind, call, Hg in generated:
        N = network.from_networkx(Hg, capacity=40, name=kind)
        nn = [dict(name=n, x=a["x"], y=a["y"]) for n, a in N.nodes(data=True)]
        ll = [dict(origin=u, destination=v) for u, v in N.edges]
        ok = nx.is_strongly_connected(N)
        pics.append(plain_map(nn, ll, 5.6, 4.2, names=False, size="2.2mm",
                              title=f"{kind}: {N.number_of_nodes()} nodes, {N.number_of_edges()} links"
                                    f"{'' if ok else ' (not connected)'}\\\\\\texttt{{\\footnotesize {call}}}"))
    figs["nx_generated"] = ("\\begin{tabular}{c@{\\hspace{12mm}}c}\n" + pics[0] + "\n&\n" + pics[1]
                            + "\\\\[6mm]\n" + pics[2] + "\n&\n" + pics[3] + "\n\\end{tabular}")
    return figs


# ----------------------------------------------------------------------
# charts
# ----------------------------------------------------------------------
def shade(cs, ymid_label=None):
    """Grey band over the capacities cs (a contiguous range), with an optional label."""
    if not cs:
        return ""
    a, b = min(cs) - 0.5, max(cs) + 0.5
    out = (f"\\fill[band] ({{axis cs:{a},0}}|-{{rel axis cs:0,0}}) rectangle "
           f"({{axis cs:{b},0}}|-{{rel axis cs:0,1}});\n")
    if ymid_label:
        out += (f"\\node[font=\\footnotesize, text=black!55, align=center] at "
                f"({{axis cs:{(a + b) / 2},0}}|-{{rel axis cs:0,0.5}}) {{{ymid_label}}};\n")
    return out


def hline(y, label, where="above right", at=0.0):
    return (f"\\draw[black!55, densely dashed, line width=0.8pt] ({{rel axis cs:0,0}}|-{{axis cs:0,{y}}}) -- "
            f"({{rel axis cs:1,0}}|-{{axis cs:0,{y}}});\n"
            f"\\node[font=\\footnotesize, text=black!60, anchor=south west, inner sep=1.5pt] at "
            f"({{rel axis cs:{at},0}}|-{{axis cs:0,{y}}}) {{{label}}};\n")


def coords(pairs):
    return " ".join(f"({x},{num(y)})" for x, y in pairs)


XLABEL = "capacity of every link, $C$ (wavelengths)"
YOBJ = "total wavelengths used\\\\(summed over the links)"


def ilp_objective(d):
    rows, lower = d["rows"], d["lower_bound"]
    ok = [(r["C"], r["objective"]) for r in rows if r["objective"] is not None]
    bad = [r["C"] for r in rows if r["objective"] is None]
    cs = [r["C"] for r in rows]
    ymax = max(y for _, y in ok)
    first = ok[0]
    return (r"\begin{tikzpicture}\begin{axis}[lab, width=128mm, height=56mm, "
            f"xmin={min(cs) - 1}, xmax={max(cs) + 1}, ymin={lower - 3}, ymax={ymax + 3}, "
            f"xlabel={{{XLABEL}}}, ylabel={{{YOBJ}}}]\n"
            + shade(bad, "infeasible")
            + hline(lower, f"lower bound {lower} (fewest-hop routing)", at=0.18)
            + f"\\addplot[s1] coordinates {{{coords(ok)}}};\n"
            + f"\\node[font=\\footnotesize, text=cA, anchor=west] at (axis cs:{first[0] + 0.4},{num(first[1])}) "
              f"{{$C = {first[0]}$: {num(first[1])}}};\n"
            + r"\end{axis}\end{tikzpicture}")


def ilp_split_full(d):
    rows = d["rows"]
    ok = [r for r in rows if r["objective"] is not None]
    bad = [r["C"] for r in rows if r["objective"] is None]
    cs = [r["C"] for r in rows]
    top = max(max(r["split"], r["saturated"]) for r in ok)
    return (r"\begin{tikzpicture}\begin{axis}[lab, width=128mm, height=42mm, "
            f"xmin={min(cs) - 1}, xmax={max(cs) + 1}, ymin=-0.3, ymax={top + 0.6}, ytick distance=1, "
            f"xlabel={{{XLABEL}}}, ylabel={{number of\\\\demands or links}}, legend pos=north east]\n"
            + shade(bad)
            + f"\\addplot[s1] coordinates {{{coords((r['C'], r['split']) for r in ok)}}};\n"
            + r"\addlegendentry{split demands}" + "\n"
            + f"\\addplot[s2] coordinates "
              f"{{{coords((r['C'], r['saturated']) for r in ok)}}};\n"
            + r"\addlegendentry{full links}" + "\n"
            + r"\end{axis}\end{tikzpicture}")


def ilp_cuts(d):
    cuts = d["cuts"]
    base = d.get("no_failure")
    names = [tex(c["fiber"]) for c in cuts]
    vals = [c["objective"] for c in cuts]
    xmax = max([v for v in vals if v is not None] + [base or 0]) * 1.16
    out = (r"\begin{tikzpicture}\begin{axis}[lab, xbar, bar width=7pt, width=95mm, height=52mm, "
           f"xmin=0, xmax={xmax:.0f}, ymin=-0.6, ymax={len(cuts) - 0.4}, y dir=reverse, "
           f"ytick={{{','.join(str(k) for k in range(len(cuts)))}}}, "
           f"yticklabels={{{','.join('{cut ' + n + '}' for n in names)}}}, ymajorgrids=false, "
           f"xlabel={{total wavelengths used (summed over the links)}}, clip=false, nodes near coords, nodes near coords align=horizontal, "
           f"nodes near coords style={{font=\\scriptsize, text=txt, anchor=west}}, point meta=explicit symbolic]\n"
           + f"\\addplot[fill=cA, draw=none] coordinates "
             f"{{{' '.join(f'({num(v)},{k}) [{num(v)}]' for k, v in enumerate(vals) if v is not None)}}};\n")
    for k, v in enumerate(vals):
        if v is None:
            out += f"\\node[font=\\scriptsize, text=black!55, anchor=west] at (axis cs:3,{k}) {{infeasible}};\n"
    if base is not None:
        out += (f"\\draw[black!55, densely dashed, line width=0.8pt] (axis cs:{num(base)},-0.6) -- "
                f"(axis cs:{num(base)},{len(cuts) - 0.4});\n"
                f"\\node[font=\\scriptsize, text=black!60, anchor=south, fill=white, inner sep=1pt] "
                f"at (axis cs:{num(base)},-0.6) {{no failure: {num(base)}}};\n")
    return out + r"\end{axis}\end{tikzpicture}"


def lab2_objective(d):
    rows, lower = d["rows"], d["lower_bound"]
    s = [(r["C"], r["split"]) for r in rows if r["split"] is not None]
    u = [(r["C"], r["unsplit"]) for r in rows if r["unsplit"] is not None]
    both = [r["C"] for r in rows if r["split"] is None and r["unsplit"] is None]
    only = [r["C"] for r in rows if r["split"] is not None and r["unsplit"] is None]
    cs = [r["C"] for r in rows]
    ymax = max(y for _, y in s + u)
    out = (r"\begin{tikzpicture}\begin{axis}[lab, width=128mm, height=62mm, "
           f"xmin={min(cs) - 1}, xmax={max(cs) + 1}, ymin={lower - 6}, ymax={ymax + 3}, "
           f"xlabel={{{XLABEL}}}, ylabel={{{YOBJ}}}, legend pos=north east]\n"
           + shade(both, "both\\\\infeasible")
           + hline(lower, f"lower bound {lower}", at=0.3)
           + f"\\addplot[s1] coordinates {{{coords(s)}}};\n\\addlegendentry{{splittable}}\n"
           + f"\\addplot[s2] coordinates {{{coords(u)}}};\n"
             f"\\addlegendentry{{unsplittable}}\n")
    if only:
        out += (f"\\addplot[cB, only marks, mark=x, mark size=3pt, line width=1.2pt] coordinates "
                f"{{{coords((c, lower - 4) for c in only)}}};\n\\addlegendentry{{unsplittable infeasible}}\n")
    return out + r"\end{axis}\end{tikzpicture}"


def lab2_difference(d):
    rows = d["rows"]
    diff = [(r["C"], r["unsplit"] - r["split"]) for r in rows if None not in (r["split"], r["unsplit"])]
    only = [r["C"] for r in rows if r["split"] is not None and r["unsplit"] is None]
    shown = [c for c, _ in diff] + only
    top = max(v for _, v in diff)
    out = (r"\begin{tikzpicture}\begin{axis}[lab, ybar, bar width=5.5pt, width=128mm, height=40mm, "
           f"xmin={min(shown) - 1}, xmax={max(shown) + 1}, ymin=0, ymax={top * 1.18:.1f}, "
           f"xlabel={{{XLABEL}}}, ylabel={{extra wavelengths\\\\(unsplittable $-$ splittable)}}, xmajorgrids=false, "
           f"nodes near coords, nodes near coords style={{font=\\scriptsize, text=txt}}]\n"
           f"\\addplot[fill=cB, draw=none] coordinates {{{coords(diff)}}};\n")
    for c in only:
        out += (f"\\node[font=\\scriptsize, text=black!55, rotate=90, anchor=west] at (axis cs:{c},0.5) "
                f"{{unsplittable infeasible}};\n")
    return out + r"\end{axis}\end{tikzpicture}"


def lab2_times(d):
    """Mean computation time with error bars of one standard deviation."""
    rows = d["rows"]
    top = max(max(r["splittable"] + r.get("splittable_std", 0), r["unsplittable"] + r.get("unsplittable_std", 0))
              for r in rows)
    cs = [r["C"] for r in rows]
    step = next(t for t in (0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100, 1e9) if top * 1.3 / t <= 6)

    def pts(key):
        return " ".join(f"({r['C']},{r[key]:.4f}) +- (0,{r.get(key + '_std', 0):.4f})" for r in rows)
    return (r"\begin{tikzpicture}\begin{axis}[lab, width=110mm, height=46mm, "
            f"xmin={min(cs) - 0.5}, xmax={max(cs) + 0.5}, ymin=0, ymax={top * 1.3:.2f}, xtick=data, "
            f"ytick distance={step:g}, "
            f"xlabel={{{XLABEL}}}, ylabel={{computation time (s)}}, legend pos=north east, legend columns=2, "
            r"legend style={/tikz/every even column/.append style={column sep=3mm}}]" + "\n"
            + f"\\addplot[s1, ebars] coordinates {{{pts('splittable')}}};\n\\addlegendentry{{splittable}}\n"
            + f"\\addplot[s2, ebars] coordinates {{{pts('unsplittable')}}};\n\\addlegendentry{{unsplittable}}\n"
            + r"\end{axis}\end{tikzpicture}")


def route_objective(d):
    """Optimal objective vs capacity: the flow formulation and the route formulation for each k."""
    rows, ks = d["rows"], d["ks"]
    series = [("flow", "flow formulation")] + [(f"k{k}", f"route formulation, $k = {k}$") for k in ks]
    vals = [r[key] for r in rows for key, _ in series if r[key] is not None]
    lo, hi = min(vals), max(vals)
    ymin = lo - 0.25 * (hi - lo)
    cs = [r["C"] for r in rows]
    out = (r"\begin{tikzpicture}\begin{axis}[lab, width=128mm, height=64mm, "
           f"xmin={min(cs) - 0.5}, xmax={max(cs) + 0.5}, ymin={ymin:.2f}, ymax={hi + 0.05 * (hi - lo):.2f}, "
           f"xtick={{{','.join(str(c) for c in cs)}}}, xlabel={{{XLABEL}}}, ylabel={{{YOBJ}}}, "
           f"legend pos=north east, legend style={{font=\\footnotesize}}]\n")
    for i, (key, label) in enumerate(series):
        ok = [(r["C"], r[key]) for r in rows if r[key] is not None]
        style = f"s{i + 1}"
        if ok:
            out += f"\\addplot[{style}] coordinates {{{coords(ok)}}};\n\\addlegendentry{{{label}}}\n"
        else:
            out += f"\\addlegendimage{{{style}}}\n\\addlegendentry{{{label} (infeasible for all $C$)}}\n"
    for i, (key, _) in enumerate(series):             # crosses at the bottom: no solution
        bad = [r["C"] for r in rows if r[key] is None]
        if bad:
            y = ymin + (0.03 + 0.035 * i) * (hi - ymin)
            out += (f"\\addplot[s{i + 1}, only marks, mark=x, mark size=2.6pt, line width=1.1pt, forget plot] "
                    f"coordinates {{{coords((c, round(y, 2)) for c in bad)}}};\n")
    out += (f"\\node[font=\\footnotesize, text=black!60, anchor=south west] at (rel axis cs:0.01,0.19) "
            f"{{$\\times$: infeasible}};\n")
    return out + r"\end{axis}\end{tikzpicture}"


def route_times(d):
    """Mean computation time with error bars of one standard deviation, for each case."""
    rows = d["rows"]
    cases = list(dict.fromkeys(r["case"] for r in rows))
    top = max(r["time"] + r["time_std"] for r in rows)
    cs = sorted({r["C"] for r in rows})
    step = next(t for t in (0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 1e9) if top * 1.45 / t <= 6)
    # legend in two columns above the data: the room left by ymax = 1.45 x the highest error bar
    out = (r"\begin{tikzpicture}\begin{axis}[lab, width=110mm, height=55mm, "
           f"xmin={min(cs) - 0.5}, xmax={max(cs) + 0.5}, ymin=0, ymax={top * 1.45:.2f}, xtick=data, "
           f"ytick distance={step:g}, xlabel={{{XLABEL}}}, ylabel={{computation time (s)}}, legend columns=2, "
           f"legend style={{font=\\footnotesize, at={{(0.5,0.98)}}, anchor=north, "
           f"/tikz/every even column/.append style={{column sep=4mm}}}}]\n")
    for i, case in enumerate(cases):
        pts = [r for r in rows if r["case"] == case and r["objective"] is not None]
        if not pts:
            continue
        label = "flow formulation" if case == "flow" else "route formulation, $" + case + "$"
        data = " ".join(f"({r['C']},{r['time']:.4f}) +- (0,{r['time_std']:.4f})" for r in pts)
        out += f"\\addplot[s{i + 1}, ebars] coordinates {{{data}}};\n\\addlegendentry{{{label}}}\n"
    return out + r"\end{axis}\end{tikzpicture}"


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def all_figures():
    figs = tour_figures()
    first = os.path.join(ROOT, "results", "lab1_first_ilp")
    if os.path.isdir(first):
        figs["ilp_map_c40"] = utilization_map(load(os.path.join(first, "ilp_map_c40.json")), 9.4, 7.4)
        figs["ilp_objective_vs_capacity"] = ilp_objective(load(os.path.join(first, "ilp_objective_vs_capacity.json")))
        figs["ilp_split_and_full_links"] = ilp_split_full(load(os.path.join(first, "ilp_split_and_full_links.json")))
        figs["ilp_fiber_cuts_c60"] = ilp_cuts(load(os.path.join(first, "ilp_fiber_cuts_c60.json")))
    lab2 = os.path.join(ROOT, "results", "lab2_unsplittable")
    if os.path.isdir(lab2) and os.path.isfile(os.path.join(lab2, "lab2_maps_c40.json")):
        d = load(os.path.join(lab2, "lab2_maps_c40.json"))
        pics = [utilization_map(m, 5.8, 5.0, title=f"{key.capitalize()}, $C = {d['C']}$: {num(m['objective'])} wavelengths")
                for key, m in d["maps"].items()]
        figs["lab2_maps_c40"] = side_by_side(pics, "4mm")
        figs["lab2_objective_vs_capacity"] = lab2_objective(load(os.path.join(lab2, "lab2_objective_vs_capacity.json")))
        figs["lab2_difference"] = lab2_difference(load(os.path.join(lab2, "lab2_difference.json")))
        if os.path.isfile(os.path.join(lab2, "lab2_time_large.json")):
            figs["lab2_time_large"] = lab2_times(load(os.path.join(lab2, "lab2_time_large.json")))
    route = os.path.join(ROOT, "results", "lab2_route_formulation")
    if os.path.isfile(os.path.join(route, "lab2r_objective_vs_k.json")):
        figs["lab2r_objective_vs_k"] = route_objective(load(os.path.join(route, "lab2r_objective_vs_k.json")))
        if os.path.isfile(os.path.join(route, "lab2r_time_large.json")):
            figs["lab2r_time_large"] = route_times(load(os.path.join(route, "lab2r_time_large.json")))
    return figs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=os.path.join("docs", "lab", "build", "tikz"))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    figs = all_figures()
    for name, body in figs.items():
        with open(os.path.join(args.out, f"{name}.tex"), "w", encoding="utf-8") as fh:
            fh.write(PREAMBLE + body + END)
    print(f"{len(figs)} TikZ figures in {args.out}")


if __name__ == "__main__":
    main()
