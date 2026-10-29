#!/usr/bin/env python3
"""
Notebook of the Lab 1 exercises (Jupyter, Google Colab)
=======================================================

Writes labs/lab1_exercises.ipynb, a self-contained notebook with the NetworkX
exercises of Lab 1: it needs only networkx and matplotlib (preinstalled in Google
Colab), and no file or repository. It contains

* the data files used by the exercises (networks and traffic matrices of data/),
  embedded as Python values;
* a small toolbox with the functions of PyNet2Plan used by the exercises
  (network.load_topology, traffic.random_traffic, ...), which behave as the
  originals and write files that the graphical interface can open;
* the helpers and the exercise functions of labs/lab1_exercises.py, unchanged,
  and the questions of the table of handout 2.

With --solutions, it also writes solutions/labs/lab1_exercises.ipynb from the
solved script (instructors' repository only).

Run it again whenever the script, the data or the table of handout 2 changes; a
test checks that the notebook is up to date and that the toolbox gives the same
results as PyNet2Plan:

    python tools/make_notebook.py               # labs/lab1_exercises.ipynb
    python tools/make_notebook.py --solutions   # ... and the solved notebook
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "labs", "lab1_exercises.py")
SOLVED_SCRIPT = os.path.join(ROOT, "solutions", "labs", "lab1_exercises.py")
NOTEBOOK = os.path.join(ROOT, "labs", "lab1_exercises.ipynb")
SOLVED_NOTEBOOK = os.path.join(ROOT, "solutions", "labs", "lab1_exercises.ipynb")
HANDOUT = os.path.join(ROOT, "docs", "lab", "src", "02_networkx_backend.md")

COLAB = "https://colab.research.google.com/github/bonsai-lab-polimi/PyNet2Plan-lab/blob/main/labs/lab1_exercises.ipynb"
HELPERS = ["fiber_cut", "fibers", "fewest_hop_bound", "km"]
#: Part 1 of the notebook (introduction to NetworkX): markdown with ```python blocks
INTRO_PART = os.path.join(ROOT, "tools", "notebook_networkx_intro.md")

#: the files of data/ read by the exercises (embedded in the notebook)
TOPOLOGY_FILES = ["data/topologies/spain7.json", "data/topologies/nsfnet14.json",
                  "data/topologies/cost239.json", "data/topologies/real/top22_geant2.json"]
TRAFFIC_FILES = ["data/traffic/spain7_traffic_split_vs_unsplit.csv", "data/traffic/spain7_traffic.csv"]
#: cities that network.add_city can place (coordinates of the offline list of PyNet2Plan)
CITIES = ["Bilbao", "Lisbon", "Porto", "Paris"]

INTRO = f"""# Lab 1: NetworkX

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)]({COLAB})

The NetworkX part of Lab 1 (handout 2, *Networks as NetworkX graphs*) in the form of a notebook.
Part 1 is a short introduction to NetworkX with the network of the lab; Part 2 contains the
exercises, and the sections it mentions are those of handout 2. The network is Spain-7, with 40
wavelengths on every link, and the traffic is the matrix of the lab (24 demands, 229
wavelengths). Exercises 1 to 5 are done in the lab; 6 and 7 are optional.

**Self-contained.** The notebook needs only `networkx` and `matplotlib`, which Google Colab already
has: open it with the link above, or upload the file in Colab (*File > Upload notebook*), or open
it in Jupyter or VS Code. The data of the lab (the networks and traffic matrices of the folder
`data`) and the few functions of PyNet2Plan used by the exercises are in the first two cells. The
exercises are the same functions as in `labs/lab1_exercises.py`: work in the form you prefer.

**How to work.** Run the three setup cells (data, toolbox, tools), then the cells of Part 1 in
order. In Part 2, run the cell of the helpers; each exercise is then a function: write its code
where the comments indicate, delete the line `raise NotCompletedError(...)`, run the cell of the
function and then the cell below it, which runs the exercise.

**Saving your work.** Colab does not save the changes in the original notebook: use
*File > Save a copy in Drive*, or *File > Download > Download .ipynb*.
"""

TOOLBOX = '''# @title Toolbox: the functions of PyNet2Plan used by the exercises (run this cell)
# They behave as network.* and traffic.* of PyNet2Plan, read the data embedded above
# instead of the files, and write files that the graphical interface of PyNet2Plan opens.
import csv
import itertools
import json
import math
import os
import random
import types
from collections import namedtuple

import matplotlib.pyplot as plt
import networkx as nx

ROOT = "."                                       # paths such as ROOT/data/... refer to the data above
TOPOLOGY = os.path.join(ROOT, "data", "topologies", "spain7.json")
TRAFFIC = os.path.join(ROOT, "data", "traffic", "spain7_traffic_split_vs_unsplit.csv")
OUT = os.path.join("results", "lab1_exercises")  # files written by the exercises (Files panel in Colab)


class NotCompletedError(Exception):
    """Raised by the parts of the exercises that are still to be written."""


class Demand(namedtuple("Demand", "id origin destination traffic")):
    """A demand: ``traffic`` wavelengths from ``origin`` to ``destination``."""

    def __str__(self):
        return f"d{self.id}: {self.origin}->{self.destination} ({self.traffic} λ)"


def _embedded(path, files):
    key = os.path.normpath(path).replace(os.sep, "/")
    if key not in files:
        raise FileNotFoundError(f"{path}: not among the files of this notebook ({', '.join(files)})")
    return files[key]


def load_topology(path):
    """The network of a topology file (embedded above) as a networkx.DiGraph: nodes with lat
    and lon, links with capacity (wavelengths per fiber), fibers and length (km)."""
    data = _embedded(path, TOPOLOGIES)
    G = nx.DiGraph(name=data["name"])
    for name, lat, lon in data["nodes"]:
        G.add_node(name, lat=lat, lon=lon, up=True)
    for u, v, length, *fibers in data["links"]:
        G.add_edge(u, v, capacity=data["capacity"], fibers=fibers[0] if fibers else 1, length=length, up=True)
    return G


def load_traffic(path, G=None):
    """The demands of a traffic file (embedded above); with G, their nodes are checked."""
    demands = [Demand(*row) for row in _embedded(path, TRAFFIC_FILES)]
    for d in demands:
        if G is not None and (d.origin not in G or d.destination not in G):
            raise ValueError(f"demand {d}: unknown node")
    return demands


def total_traffic(demands):
    return sum(d.traffic for d in demands)


def describe(G):
    """One line describing the network, as in PyNet2Plan."""
    links = [a for _, _, a in G.edges(data=True)]
    caps = [a.get("capacity", 0) for a in links] or [0]
    fib = [a.get("fibers", 1) for a in links] or [0]
    up = sum(1 for a in links if a.get("up", True))
    cap = f"{min(caps)}" if min(caps) == max(caps) else f"{min(caps)}-{max(caps)}"
    fibers = "" if max(fib) <= 1 else (f", {min(fib)}" + (f"-{max(fib)}" if min(fib) != max(fib) else "")
                                       + " fibers per link")
    return (f"{G.graph.get('name', '')}: {G.number_of_nodes()} nodes, {G.number_of_edges()} links ({up} up), "
            f"capacity {cap} λ{' per fiber' if fibers else ''}{fibers}")


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(a)))


def add_city(G, city, name=None, allow_online=False):
    """Adds a node at the coordinates of ``city`` (one of CITIES); returns its name."""
    if city not in CITIES:
        raise KeyError(f"{city}: unknown city; known: {', '.join(CITIES)} (or use G.add_node(name, lat=..., lon=...))")
    lat, lon = CITIES[city]
    name = name or city
    G.add_node(name, lat=lat, lon=lon, up=True)
    return name


def link_length(G, u, v):
    """Great-circle km between two nodes with lat and lon, otherwise the distance of x and y."""
    a, b = G.nodes[u], G.nodes[v]
    if a.get("lat") is not None and b.get("lat") is not None:
        return round(haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]), 2) or 1.0
    return round(math.hypot(a["x"] - b["x"], a["y"] - b["y"]), 3) or 1.0


def add_link(G, origin, destination, capacity=40, length=None, bidirectional=False, fibers=1):
    """Adds the link origin -> destination (and the opposite one with bidirectional=True)."""
    for u, v in [(origin, destination)] + ([(destination, origin)] if bidirectional else []):
        if G.has_edge(u, v):
            raise ValueError(f"the link {u}->{v} already exists")
        G.add_edge(u, v, capacity=capacity, fibers=fibers,
                   length=link_length(G, u, v) if length is None else float(length), up=True)


def random_traffic(G, num_demands, min_traffic=1, max_traffic=8, seed=0):
    """num_demands demands between distinct random node pairs, each of a random number of
    wavelengths in [min_traffic, max_traffic]; the same seed gives the same demands."""
    rnd = random.Random(seed)
    pairs = [(a, b) for a in G.nodes for b in G.nodes if a != b]
    demands = []
    for i in range(min(num_demands, len(pairs))):          # partial Fisher-Yates shuffle
        j = i + int(rnd.random() * (len(pairs) - i))
        pairs[i], pairs[j] = pairs[j], pairs[i]
        traffic = min_traffic + int(rnd.random() * (max_traffic - min_traffic + 1))
        demands.append(Demand(i, pairs[i][0], pairs[i][1], traffic))
    return demands


def save_topology(G, path):
    """Saves the network as a PyNet2Plan topology file (File > Open topology... in the tool)."""
    nodes = []
    for n, a in G.nodes(data=True):
        item = {"name": n}
        item.update({k: a[k] for k in ("lat", "lon", "x", "y") if a.get(k) is not None})
        item["up"] = bool(a.get("up", True))
        nodes.append(item)
    links = []
    for u, v, a in G.edges(data=True):
        item = {"origin": u, "destination": v, "capacity": int(a.get("capacity", 40))}
        if int(a.get("fibers", 1)) != 1:
            item["fibers"] = int(a["fibers"])
        item.update(length=a.get("length"), up=bool(a.get("up", True)))
        links.append(item)
    data = {"format": "pynet2plan-topology", "version": 2, "name": G.graph.get("name", "Untitled network"),
            "nodes": nodes, "links": links}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def save_traffic(demands, path):
    """Saves the demands as a PyNet2Plan traffic file (Traffic > Open traffic matrix... in the tool)."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "origin", "destination", "traffic"])
        for d in demands:
            w.writerow([d.id, d.origin, d.destination, d.traffic])


def from_networkx(H, capacity=40, name=None, size=1000.0):
    """A network made by a NetworkX generator (e.g. nx.waxman_graph) as a PyNet2Plan network:
    two links per edge, positions scaled to a size x size square, lengths from the positions."""
    pos = nx.get_node_attributes(H, "pos")
    if len(pos) != H.number_of_nodes():
        pos = nx.spring_layout(H, seed=0)
    xs, ys = [float(pos[n][0]) for n in H], [float(pos[n][1]) for n in H]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    G = nx.DiGraph(name=name or f"{type(H).__name__} ({H.number_of_nodes()} nodes)")
    for n, x, y in zip(H, xs, ys):
        G.add_node(str(n), x=round((x - min(xs)) / span * size, 1), y=round((y - min(ys)) / span * size, 1),
                   up=True)
    for u, v in H.edges():
        if u != v and not G.has_edge(str(u), str(v)):
            add_link(G, str(u), str(v), capacity=capacity, bidirectional=not H.is_directed())
    return G


network = types.SimpleNamespace(load_topology=load_topology, describe=describe, add_city=add_city,
                                add_link=add_link, save_topology=save_topology, from_networkx=from_networkx)
traffic = types.SimpleNamespace(load_traffic=load_traffic, total_traffic=total_traffic,
                                random_traffic=random_traffic, save_traffic=save_traffic)

G = network.load_topology(TOPOLOGY)
D = traffic.load_traffic(TRAFFIC, G)
print(network.describe(G))
print(f"{len(D)} demands, {traffic.total_traffic(D)} wavelengths")'''

TOOLS = '''# Tools of the notebook (given): run an exercise, draw a network and some paths on a map
def run(exercise):
    """Runs an exercise on G and D; says which TODO is still missing."""
    print(exercise.__doc__.split("\\n")[0])
    try:
        exercise(G, D)
    except NotCompletedError as e:
        print(f"  not completed yet: {e}")


def draw(H, paths=(), title=None, separate=False):
    """Draws H with longitude and latitude as coordinates, and each path of ``paths`` in its own
    colour; with separate=True, each path on its own map."""
    pos = {n: (H.nodes[n]["lon"], H.nodes[n]["lat"]) for n in H.nodes}
    above = {n: (x, y + 0.12) for n, (x, y) in pos.items()}         # labels above the nodes
    U = H.to_undirected()
    groups = [[p] for p in paths] if separate and paths else [list(paths)]
    fig, axes = plt.subplots(1, len(groups), figsize=(5.2 * len(groups) if separate else 6.5, 5), squeeze=False)
    for i, (ax, group) in enumerate(zip(axes[0], groups)):
        nx.draw_networkx_edges(U, pos, ax=ax, edge_color="#9e9e9e", width=1.5)
        for k, path in enumerate(group):
            color = ("#eb6834", "#1baf7a", "#2a78d6", "#7b4fd1")[(i + k) % 4]
            nx.draw_networkx_edges(U, pos, edgelist=list(zip(path, path[1:])), ax=ax, edge_color=color,
                                   width=4, label=" > ".join(path))
        nx.draw_networkx_nodes(H, pos, ax=ax, node_size=90, node_color="#2a78d6")
        nx.draw_networkx_labels(H, above, ax=ax, font_size=11, verticalalignment="bottom")
        ax.margins(0.12)
        ax.set_axis_off()
        if separate:
            ax.set_title(" > ".join(group[0]), fontsize=10)
        elif group:                                                  # legend below the map
            ax.legend(loc="upper center", bbox_to_anchor=(0.5, 0.0), fontsize=10, frameon=False)
    if separate:
        fig.suptitle(title or H.graph.get("name", ""), fontsize=13)
    else:
        axes[0][0].set_title(title or H.graph.get("name", ""), fontsize=13)
    plt.show()
    plt.close(fig)'''

CALLS = """## The NetworkX calls you need

All of them are explained in handout 2 and used in `labs/lab1_networkx_tour.py`.

| call | result |
|---|---|
| `nx.shortest_path(G, s, t)` | path with the fewest hops, as a list of nodes |
| `nx.shortest_path(G, s, t, weight="length")` | shortest path in kilometres |
| `nx.shortest_path_length(G, s, t)` | number of hops of the fewest-hop path |
| `nx.path_weight(G, path, weight="length")` | length of a path in kilometres (helper `km(G, path)`) |
| `nx.is_strongly_connected(H)` | `True` if every node can reach every other node |
| `G.nodes`, `G.edges`, `G.edges[u, v]["length"]` | nodes, links and attributes of a link |
| `G.out_edges(n)`, `G.in_edges(n)` | links leaving and entering node n |
| `itertools.combinations(nodes, k)` | every set of k nodes |
| `d.origin`, `d.destination`, `d.traffic` | a demand of `D` |

The files mentioned in the exercises (`data/...`) are those embedded in the first cell, and
`network.*` and `traffic.*` are the functions of the toolbox. The tool `draw(H, [path1, path2])`
shows a network and some paths on a map (`separate=True`: one map per path)."""

EXTRA = {
    1: "Tip: `draw(H, [path1, path2])` shows two paths on the map of the network H.",
    5: ("The files are written in the folder `results/lab1_exercises` (in Colab: *Files* panel on the "
        "left, right click > *Download*). Open them in PyNet2Plan on your computer with "
        "*File > Open topology...* and *Traffic > Open traffic matrix...*."),
    6: "`waxman15.json` is written in the same folder, to be opened in the interface.",
}

OUTRO = """## When you have finished

Compare the results of exercise 2 with the fibre cuts of handout 3 (section 5), where the capacity
of the links is limited to 60 wavelengths. The same functions are in `labs/lab1_exercises.py`,
which can be run from a terminal with `python labs/lab1_exercises.py`."""


def handout_questions(path: str = HANDOUT) -> dict[int, tuple[str, str]]:
    """Exercise number -> (question, NetworkX calls) from the table of handout 2."""
    rows = {}
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"\|\s*(\d+)( \(optional\))?\s*\|(.+)\|(.+)\|\s*$", line)
            if m:
                rows[int(m.group(1))] = (m.group(3).strip(), m.group(4).strip())
    return rows


def functions(path: str) -> dict[str, tuple[str, str]]:
    """Name -> (source, docstring) of the top-level functions of a script."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    tree = ast.parse(text)
    return {node.name: (ast.get_source_segment(text, node), ast.get_docstring(node) or "")
            for node in tree.body if isinstance(node, ast.FunctionDef)}


def data_cell(root: str = ROOT) -> str:
    """The cell with the data files of the exercises, as Python values."""
    sys.path.insert(0, root)
    from pynet2plan import geo, network, traffic
    out = ["# @title Data of the lab: networks and traffic matrices of the folder data (run this cell)",
           "# Topology files: name, capacity of every link (wavelengths per fiber), nodes (name, lat, lon),",
           "# links (origin, destination, length in km[, fibers if more than 1]). Traffic files: demands",
           "# (id, origin, destination, wavelengths).", "TOPOLOGIES = {"]
    for rel in TOPOLOGY_FILES:
        G = network.load_topology(os.path.join(root, *rel.split("/")))
        caps = {a["capacity"] for _, _, a in G.edges(data=True)}
        assert len(caps) == 1, f"{rel}: the notebook assumes the same capacity on every link"
        out.append(f'    "{rel}": {{')
        out.append(f'        "name": {json.dumps(G.graph["name"], ensure_ascii=False)}, "capacity": {caps.pop()},')
        out.append('        "nodes": [')
        for n, a in G.nodes(data=True):
            out.append(f'            ({json.dumps(n, ensure_ascii=False)}, {a["lat"]!r}, {a["lon"]!r}),')
        out.append("        ],")
        out.append('        "links": [')
        links = []
        for u, v, a in G.edges(data=True):
            extra = f", {a['fibers']}" if a.get("fibers", 1) != 1 else ""
            links.append(f'({json.dumps(u, ensure_ascii=False)}, {json.dumps(v, ensure_ascii=False)}, '
                         f'{a["length"]!r}{extra})')
        for k in range(0, len(links), 3):
            out.append("            " + ", ".join(links[k:k + 3]) + ",")
        out.append("        ],")
        out.append("    },")
    out += ["}", "", "TRAFFIC_FILES = {"]
    for rel in TRAFFIC_FILES:
        D = traffic.load_traffic(os.path.join(root, *rel.split("/")))
        out.append(f'    "{rel}": [')
        rows = [f"({d.id}, {json.dumps(d.origin, ensure_ascii=False)}, {json.dumps(d.destination, ensure_ascii=False)}, "
                f"{d.traffic})" for d in D]
        for k in range(0, len(rows), 3):
            out.append("        " + ", ".join(rows[k:k + 3]) + ",")
        out.append("    ],")
    out += ["}", "", "CITIES = {"]
    for city in CITIES:
        out.append(f'    "{city}": {geo.geocode(city, allow_online=False)!r},')
    out.append("}")
    return "\n".join(out)


def intro_part(path: str = INTRO_PART) -> list[tuple[str, str]]:
    """The cells of Part 1: each ```python block is a code cell, the text between blocks is a
    markdown cell, split at the headings (the leading HTML comment is left out)."""
    with open(path, encoding="utf-8") as fh:
        text = re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S)
    cells = []
    for k, chunk in enumerate(re.split(r"^```python\n(.*?)^```\n", text, flags=re.S | re.M)):
        if k % 2:
            cells.append(("code", chunk.strip("\n")))
            continue
        for part in re.split(r"\n(?=#{1,3} )", chunk):          # a markdown cell per section
            if part.strip():
                cells.append(("markdown", part.strip("\n")))
    return cells


def cell(kind: str, text: str, n: int, form: bool = False) -> dict:
    lines = text.strip("\n").split("\n")
    c = {"cell_type": kind, "id": f"cell-{n:02d}", "metadata": {"cellView": "form"} if form else {},
         "source": [ln + "\n" for ln in lines[:-1]] + [lines[-1]]}
    if kind == "code":
        c.update(execution_count=None, outputs=[])
    return c


def notebook(script: str, solved: bool = False) -> dict:
    funcs = functions(script)
    questions = handout_questions()
    intro = INTRO
    if solved:
        intro = intro.replace("# Lab 1: NetworkX exercises", "# Lab 1: NetworkX exercises (solutions)")
        intro = re.sub(r"\[!\[Open In Colab\].*\n\n", "", intro)
        intro = intro.replace("open it with the link above, or upload", "upload")
    setup = ("## Setup\n\nThe data of the lab, the toolbox and two tools of the notebook: `run(exercise)` "
             "runs an exercise of Part 2, `draw(H, paths)` draws a network and some paths on a map.")
    parts = [("markdown", intro), ("markdown", setup), ("code", data_cell(), True), ("code", TOOLBOX, True),
             ("code", TOOLS)] + intro_part()
    parts += [("markdown", "# Part 2. Exercises\n\n## Helpers (given)\n\nThe same helper functions as in "
                           "`labs/lab1_exercises.py`."),
             ("code", "\n\n\n".join(funcs[name][0] for name in HELPERS)), ("markdown", CALLS)]
    numbers = sorted(int(name.split("_")[1]) for name in funcs if re.fullmatch(r"exercise_\d+", name))
    for n in numbers:
        source, doc = funcs[f"exercise_{n}"]
        title = doc.split("\n")[0].strip()
        optional = title.startswith("(Optional)")
        title = title.replace("(Optional) ", "")
        md = f"## Exercise {n}{' (optional)' if optional else ''}\n\n"
        if n in questions:                             # the question of handout 2, or the docstring
            question, calls = questions[n]
            md += f"{question}\n\nFunctions to use: {calls}"
        else:
            md += title
        if n in EXTRA:
            md += "\n\n" + EXTRA[n]
        parts += [("markdown", md), ("code", source), ("code", f"run(exercise_{n})")]
    parts.append(("markdown", OUTRO))
    return {
        "cells": [cell(p[0], p[1], k + 1, *p[2:]) for k, p in enumerate(parts)],
        "metadata": {
            "colab": {"provenance": [], "toc_visible": True},
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def dumps(nb: dict) -> str:
    return json.dumps(nb, indent=1, ensure_ascii=False) + "\n"


def write(script: str, out: str, solved: bool = False) -> str:
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(dumps(notebook(script, solved)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--solutions", action="store_true", help="also write the solved notebook")
    args = ap.parse_args(argv)
    print("written:", os.path.relpath(write(SCRIPT, NOTEBOOK), ROOT))
    if args.solutions:
        if not os.path.isfile(SOLVED_SCRIPT):
            print("solutions/labs/lab1_exercises.py not found: solved notebook not written")
            return 1
        print("written:", os.path.relpath(write(SOLVED_SCRIPT, SOLVED_NOTEBOOK, solved=True), ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
