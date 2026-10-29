#!/usr/bin/env python3
"""
Lab 1 - a tour of the backend: networks are NetworkX graphs
===========================================================

Everything PyNet2Plan does with a network is plain NetworkX. Run this file
from the project root, top to bottom:

    python labs/lab1_networkx_tour.py              # prints the results, saves the figures
    python labs/lab1_networkx_tour.py --show       # ... and also opens the figures

or run it cell by cell (the "# %%" lines) in VS Code / Spyder / Jupyter.
The figures are saved in results/networkx_tour/.
"""

# %% 0. Imports -----------------------------------------------------------------
import argparse
import itertools
import math
import os
import sys
from itertools import islice

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import matplotlib  # noqa: E402

if "--show" not in sys.argv:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402

from pynet2plan import network, traffic  # noqa: E402

ap = argparse.ArgumentParser(description="A tour of the NetworkX backend of PyNet2Plan")
ap.add_argument("--out", default=os.path.join(ROOT, "results", "networkx_tour"), help="folder of the figures")
ap.add_argument("--show", action="store_true", help="also show the figures on screen")
args, _ = ap.parse_known_args()
OUT = args.out
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.size": 11, "axes.titlesize": 13, "figure.dpi": 110})

BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#9e9e9e"


def section(title):
    print("\n" + title + "\n" + "-" * len(title))


def save(fig, name):
    path = os.path.join(OUT, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"   figure saved: {os.path.relpath(path, ROOT)}")
    if not args.show:
        plt.close(fig)


# %% 1. A network is a networkx.DiGraph -------------------------------------------
section("1. A network is a networkx.DiGraph")
H = nx.DiGraph(name="Tiny")
H.add_node("A", x=0, y=0)
H.add_node("B", x=100, y=0)
H.add_node("C", x=50, y=80)
H.add_edge("A", "B", capacity=40, fibers=1, length=100.0)   # one direction ...
H.add_edge("B", "A", capacity=40, fibers=1, length=100.0)   # ... and the opposite one
H.add_edge("B", "C", capacity=10, fibers=2, length=94.3)    # 2 fibers of 10 wavelengths each
print("nodes:", list(H.nodes(data=True)))
print("links:", list(H.edges(data=True)))
bc = H.edges["B", "C"]
print("capacity of B->C:", bc["fibers"], "fibers x", bc["capacity"], "wavelengths =",
      bc["fibers"] * bc["capacity"], "wavelengths")
# the PyNet2Plan helpers build exactly the same graph, checking the values for you:
H2 = network.new_network("Tiny")
for n, x, y in [("A", 0, 0), ("B", 100, 0), ("C", 50, 80)]:
    network.add_node(H2, n, x=x, y=y)
network.add_link(H2, "A", "B", capacity=40, bidirectional=True)   # length from the positions
network.add_link(H2, "B", "C", capacity=10, fibers=2)          # fibers=1 if not given
print("same links with the helpers:", sorted(H2.edges) == sorted(H.edges))

# %% 2. The Spain-7 network ----------------------------------------------------------
section("2. The Spain-7 network of the lab")
G = network.load_topology(os.path.join(ROOT, "data", "topologies", "spain7.json"))
print(type(G).__name__, "-", G.graph["name"], "-", G.number_of_nodes(), "nodes,", G.number_of_edges(), "links")
print("Madrid:", G.nodes["Madrid"])
print("links leaving Madrid:", list(G.out_edges("Madrid")))
print("links entering Madrid:", list(G.in_edges("Madrid")))
print("out-degree:", dict(G.out_degree()))
print(f"{'link':22s} {'fibers':>6s} {'capacity':>8s} {'length (km)':>12s}")
for u, v, a in sorted(G.edges(data=True)):
    print(f"{u + ' -> ' + v:22s} {a['fibers']:6d} {a['capacity']:8d} {a['length']:12.1f}")

pos = {n: (a["x"], a["y"]) for n, a in G.nodes(data=True)}     # drawing positions
U = G.to_undirected()                                          # one line per pair of links
fig, ax = plt.subplots(figsize=(7.5, 6.2))
nx.draw_networkx_edges(U, pos, ax=ax, width=2, edge_color="#546e7a")
nx.draw_networkx_nodes(U, pos, ax=ax, node_size=900, node_color=BLUE, edgecolors="white")
nx.draw_networkx_labels(U, pos, ax=ax, font_size=10, font_color="white", font_weight="bold",
                        labels={n: n[:3] for n in U})
nx.draw_networkx_edge_labels(U, pos, ax=ax, font_size=10,
                             edge_labels={(u, v): f"{a['length']:.0f} km" for u, v, a in U.edges(data=True)})
ax.set_title("Spain-7, link lengths in km")
ax.set_axis_off()
ax.margins(0.08)
save(fig, "nx_spain7.png")

# %% 3. Shortest paths ------------------------------------------------------------------
section("3. Shortest paths")
s, t = "Sevilla", "Valencia"
p_hops = nx.shortest_path(G, s, t)                     # fewest links (hops)
p_km = nx.shortest_path(G, s, t, weight="length")      # shortest in km
km = nx.path_weight(G, p_km, weight="length")
print(f"fewest hops : {' > '.join(p_hops)}   ({len(p_hops) - 1} hops, "
      f"{nx.path_weight(G, p_hops, weight='length'):.0f} km)")
print(f"shortest km : {' > '.join(p_km)}   ({len(p_km) - 1} hops, {km:.0f} km)")
hops = dict(nx.shortest_path_length(G))                 # hop distance of every pair
print("hop distance Zaragoza -> every node:", hops["Zaragoza"])


def draw_paths(ax, paths, colors, title):
    nx.draw_networkx_edges(U, pos, ax=ax, width=1.5, edge_color="#cfd8dc")
    for p, c in zip(paths, colors):
        nx.draw_networkx_edges(U, pos, ax=ax, edgelist=list(zip(p[:-1], p[1:])), width=5, edge_color=c)
    nx.draw_networkx_nodes(U, pos, ax=ax, node_size=620, node_color=BLUE, edgecolors="white")
    nx.draw_networkx_labels(U, pos, ax=ax, font_size=8.5, font_color="white", font_weight="bold",
                            labels={n: n[:3] for n in U})
    ax.set_title(title, fontsize=11.5)
    ax.set_axis_off()
    ax.margins(0.08)


fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
draw_paths(axes[0], [p_hops], [ORANGE], f"{s} to {t}, fewest hops ({len(p_hops) - 1})")
draw_paths(axes[1], [p_km], [AQUA], f"{s} to {t}, shortest length ({km:.0f} km)")
save(fig, "nx_shortest_paths.png")

# %% 4. The k shortest paths (used by the route formulations) ----------------------------
section("4. The k shortest paths: candidate routes")
s, t = "Zaragoza", "Malaga"
k = 3
paths = list(islice(nx.shortest_simple_paths(G, s, t, weight="length"), k))
for i, p in enumerate(paths, 1):
    print(f"  path {i}: {' > '.join(p):45s} {len(p) - 1} hops, "
          f"{nx.path_weight(G, p, weight='length'):6.0f} km")
fig, axes = plt.subplots(1, k, figsize=(14, 4.6))
for i, (ax, p, c) in enumerate(zip(axes, paths, [BLUE, ORANGE, AQUA]), 1):
    draw_paths(ax, [p], [c], f"path {i}: {len(p) - 1} hops, {nx.path_weight(G, p, weight='length'):.0f} km")
fig.suptitle(f"The {k} shortest paths from {s} to {t}", fontsize=13)
save(fig, "nx_k_shortest_paths.png")

# %% 5. Connectivity, failures and cuts ---------------------------------------------------
section("5. Connectivity, failures and cuts")
print("strongly connected:", nx.is_strongly_connected(G))
print("links that disconnect the network if they fail (bridges):", list(nx.bridges(U)) or "none")
print("node connectivity:", nx.node_connectivity(U), "  edge connectivity:", nx.edge_connectivity(U))
F = G.copy()
F.remove_edges_from([("Madrid", "Valencia"), ("Valencia", "Madrid")])     # a fiber cut
print("Madrid -> Murcia before the cut:", " > ".join(nx.shortest_path(G, "Madrid", "Murcia")))
print("Madrid -> Murcia after the cut :", " > ".join(nx.shortest_path(F, "Madrid", "Murcia")))

# Cut condition: the traffic that must leave a set of nodes S cannot exceed the
# capacity of the links leaving S. With one fiber and the same capacity C on every link:
#     C >= traffic(S -> outside) / number of links (S -> outside)     for every S
D = traffic.load_traffic(os.path.join(ROOT, "data", "traffic", "spain7_traffic_split_vs_unsplit.csv"), G)
best = None
for size in range(1, G.number_of_nodes()):
    for S in itertools.combinations(G.nodes, size):
        S = set(S)
        links = len(list(nx.edge_boundary(G, S)))                 # links from S to the rest
        need = sum(d.traffic for d in D if d.origin in S and d.destination not in S)
        if links and (best is None or math.ceil(need / links) > best[0]):
            best = (math.ceil(need / links), need, links, S)
C_min, need, links, S = best
print(f"tightest cut: traffic into {sorted(set(G) - S)} = {need} λ over {links} links"
      f"  ->  every link needs C >= {C_min}")

fig, ax = plt.subplots(figsize=(7.5, 6.2))
inside = set(G) - S
cut = [(u, v) for u, v in U.edges if (u in S) != (v in S)]          # drawn once per pair
nx.draw_networkx_edges(U, pos, ax=ax, width=2, edge_color="#b0bec5")
nx.draw_networkx_edges(U, pos, ax=ax, edgelist=cut, width=6, edge_color=ORANGE)
nx.draw_networkx_nodes(U, pos, ax=ax, nodelist=sorted(S), node_size=900, node_color=BLUE, edgecolors="white")
nx.draw_networkx_nodes(U, pos, ax=ax, nodelist=sorted(inside), node_size=900, node_color=AQUA,
                       edgecolors="white")
nx.draw_networkx_labels(U, pos, ax=ax, font_size=10, font_color="white", font_weight="bold",
                        labels={n: n[:3] for n in U})
ax.set_title(f"Traffic entering {' and '.join(sorted(inside))}: {need} λ on {links} links\n"
             f"(in orange), hence C ≥ {need}/{links} = {C_min}")
ax.set_axis_off()
ax.margins(0.08)
save(fig, "nx_cut.png")

# %% 6. Generating networks with NetworkX ----------------------------------------------------
section("6. Generating networks with NetworkX")
generated = {
    "ring: nx.cycle_graph(8)": nx.cycle_graph(8),
    "grid: nx.grid_2d_graph(3, 4)": nx.grid_2d_graph(3, 4),
    "Waxman: nx.waxman_graph(12, seed=7)": nx.waxman_graph(12, beta=0.7, alpha=0.35, seed=7),
    "random: nx.gnm_random_graph(10, 16, seed=3)": nx.gnm_random_graph(10, 16, seed=3),
}
fig, axes = plt.subplots(2, 2, figsize=(11, 9.5))
for ax, (title, Hg) in zip(axes.flat, generated.items()):
    N = network.from_networkx(Hg, capacity=40, name=title.split(":")[0])   # -> a PyNet2Plan network
    p = {n: (a["x"], a["y"]) for n, a in N.nodes(data=True)}
    nx.draw_networkx(N.to_undirected(), p, ax=ax, node_size=160, node_color=BLUE, edge_color="#546e7a",
                     width=1.5, with_labels=False)
    ok = nx.is_strongly_connected(N)
    kind, call = title.split(": ")
    ax.set_title(f"{kind} - {N.number_of_nodes()} nodes, {N.number_of_edges()} links"
                 f"{'' if ok else ' (NOT connected)'}\n{call}", fontsize=11.5)
    ax.set_axis_off()
    ax.margins(0.08)
    print(f"  {title:45s} {N.number_of_nodes():3d} nodes {N.number_of_edges():3d} links  connected: {ok}")
save(fig, "nx_generated.png")
W = network.from_networkx(generated["Waxman: nx.waxman_graph(12, seed=7)"], capacity=40, name="Waxman 12")
path = os.path.join(OUT, "waxman12.json")
network.save_topology(W, path)
print(f"  saved {os.path.relpath(path, ROOT)}: open it in the GUI with File > Open topology...")

# %% 7. Traffic: repeatable random matrices --------------------------------------------------
section("7. Traffic: repeatable random matrices")
D1 = traffic.random_traffic(G, 24, 4, 16, seed=9)
D2 = traffic.random_traffic(G, 24, 4, 16, seed=9)
print("same seed, same demands:", D1 == D2)
print("it is exactly data/traffic/spain7_traffic_split_vs_unsplit.csv:", D1 == D)
print("first demands:", ", ".join(f"{d.origin}->{d.destination} {d.traffic}λ" for d in D1[:4]), "...")
print("total traffic:", traffic.total_traffic(D1), "wavelengths")
print("as a matrix {(origin, destination): wavelengths}:", dict(list(traffic.traffic_matrix(D1).items())[:3]), "...")
lower = sum(d.traffic * hops[d.origin][d.destination] for d in D)
print(f"if every demand followed a fewest-hops path: {lower} wavelengths used in total"
      f" (a lower bound for the ILP objective)")

if args.show:
    plt.show()
