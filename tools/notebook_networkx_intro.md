<!--
Part 1 of labs/lab1_exercises.ipynb: a short introduction to NetworkX.
Each ```python block becomes a code cell and the text between blocks a markdown cell
(tools/make_notebook.py). The cells use the data and the toolbox of the notebook (G, D,
network.*, traffic.*, draw). After changing this file run: python tools/make_notebook.py --solutions
-->

# Part 1. A short introduction to NetworkX

NetworkX is the Python library used by PyNet2Plan to represent networks. This part presents the
calls needed in the exercises, with the network of the lab; it follows sections 1 to 7 of
handout 2. Run the cells in order and read their output.

## 1. Graphs, nodes and links

NetworkX represents a graph as a Python object: `nx.Graph()` is an undirected graph and
`nx.DiGraph()` a directed one. An optical network is a directed graph, because a pair of fibres
between two cities gives two links, one per direction, each with its own capacity and load.
Nodes and links can have attributes, which are stored in dictionaries.

```python
T = nx.DiGraph(name="Tiny")                    # an empty directed graph
T.add_node("A", lat=45.46, lon=9.19)           # a node with two attributes
T.add_node("B", lat=45.07, lon=7.69)
T.add_node("C", lat=44.41, lon=8.93)
T.add_edge("A", "B", capacity=40, fibers=1, length=126.0)   # the link A -> B ...
T.add_edge("B", "A", capacity=40, fibers=1, length=126.0)   # ... and the opposite one
T.add_edge("A", "C", capacity=10, fibers=2, length=118.0)   # 2 fibres of 10 wavelengths

print("nodes:", list(T.nodes))
print("node A:", T.nodes["A"])
print("links:", list(T.edges))
print("link A->C:", T.edges["A", "C"])
print("is there a link C->A?", T.has_edge("C", "A"))
print(T.number_of_nodes(), "nodes and", T.number_of_edges(), "links")
```

The capacity of a link, in wavelengths, is the number of fibres times the wavelengths per
fibre: for A→C, `T.edges["A", "C"]["fibers"] * T.edges["A", "C"]["capacity"]` = 20. In PyNet2Plan
every network is a `DiGraph` of this kind; the function `add_link(G, u, v, capacity=40,
bidirectional=True)` of the toolbox adds the two directions at once and computes the length from
the coordinates.

## 2. The network of the lab

`G`, loaded in the toolbox cell, is Spain-7: 7 cities and 8 pairs of fibres, that is 16 links,
with 40 wavelengths on every link. The links leaving and entering a node are given by
`G.out_edges(n)` and `G.in_edges(n)`, and their number by `G.out_degree(n)` and `G.in_degree(n)`.

```python
print(G.graph["name"], "-", G.number_of_nodes(), "nodes,", G.number_of_edges(), "links")
print("Madrid:", G.nodes["Madrid"])
print("links leaving Madrid:", list(G.out_edges("Madrid")))
print("links entering Madrid:", list(G.in_edges("Madrid")))
print("out-degree:", dict(G.out_degree()))
```

A loop over `G.edges(data=True)` gives every link with its attributes:

```python
print(f"{'link':22s} {'fibers':>6s} {'capacity':>8s} {'length (km)':>12s}")
for u, v, a in sorted(G.edges(data=True)):
    print(f"{u + ' -> ' + v:22s} {a['fibers']:6d} {a['capacity']:8d} {a['length']:12.1f}")
draw(G)
```

## 3. Shortest paths

`nx.shortest_path(G, s, t)` returns the path with the fewest links (hops) from s to t, as a list
of nodes. With `weight="length"` it returns the path of minimum total length, in kilometres.
`nx.path_weight(G, path, weight="length")` adds up an attribute along a path.

```python
s, t = "Sevilla", "Valencia"
p_hops = nx.shortest_path(G, s, t)
p_km = nx.shortest_path(G, s, t, weight="length")
for label, p in (("fewest hops", p_hops), ("shortest km", p_km)):
    print(f"{label}: {' > '.join(p)}  ({len(p) - 1} hops, {nx.path_weight(G, p, weight='length'):.0f} km)")
draw(G, [p_hops, p_km], title=f"{s} to {t}: fewest hops and shortest length")
```

The two criteria give different paths: the path through Madrid has one hop less, the path along
the coast is 35 km shorter. Without s and t, `nx.shortest_path_length(G)` gives the number of
hops between every pair of nodes, as a dictionary of dictionaries:

```python
hops = dict(nx.shortest_path_length(G))
print("hops from Zaragoza:", hops["Zaragoza"])
print("hops from Sevilla to Barcelona:", hops["Sevilla"]["Barcelona"])
```

## 4. The k shortest paths

The route formulations of Lab 2 choose the path of each demand among a few candidate paths.
`nx.shortest_simple_paths(G, s, t, weight="length")` generates all the paths without loops from
s to t, from the shortest to the longest, one at a time; `islice` takes the first k of them
without computing the others.

```python
from itertools import islice

paths = list(islice(nx.shortest_simple_paths(G, "Zaragoza", "Malaga", weight="length"), 3))
for i, p in enumerate(paths, 1):
    print(f"path {i}: {' > '.join(p)}  ({len(p) - 1} hops, {nx.path_weight(G, p, weight='length'):.0f} km)")
draw(G, paths, title="The 3 shortest paths from Zaragoza to Malaga", separate=True)
```

## 5. Connectivity and failures

A directed graph is strongly connected when every node can reach every other node. A fibre cut
removes the two links of a pair; it is simulated on a copy of the network, so that `G` does not
change. On the undirected version of the graph, `nx.bridges` lists the edges whose failure
disconnects the network and `nx.edge_connectivity` gives the smallest number of edges whose
failure does.

```python
U = G.to_undirected()
print("strongly connected:", nx.is_strongly_connected(G))
print("bridges:", list(nx.bridges(U)) or "none", "- edge connectivity:", nx.edge_connectivity(U))

F = G.copy()                                    # the network after the cut of Madrid-Valencia
F.remove_edges_from([("Madrid", "Valencia"), ("Valencia", "Madrid")])
print("Madrid -> Murcia before the cut:", " > ".join(nx.shortest_path(G, "Madrid", "Murcia")))
print("Madrid -> Murcia after the cut :", " > ".join(nx.shortest_path(F, "Madrid", "Murcia")))
print("still strongly connected:", nx.is_strongly_connected(F))
```

## 6. Demands

`D`, also loaded in the toolbox cell, is the traffic matrix of the lab: a list of demands, each
with an id, an origin, a destination and a traffic in wavelengths. The matrix was generated with
`traffic.random_traffic` and a seed: the same seed always gives the same demands, so a random
matrix can be reproduced by anybody.

```python
print(len(D), "demands,", traffic.total_traffic(D), "wavelengths")
for d in D[:4]:
    print(" ", d, "- origin", d.origin, "- traffic", d.traffic)
print("random_traffic(G, 24, 4, 16, seed=9) gives the same demands:",
      traffic.random_traffic(G, 24, 4, 16, seed=9) == D)
```

## 7. Two bounds from the graph

If the capacities were unlimited, every demand would follow a path with the fewest hops, and
the wavelengths used, summed over all the links, would be the traffic of each demand times its
number of hops. No routing can use fewer wavelengths, so this value is a lower bound for the
optimum of the formulations of handout 3.

```python
lower = sum(d.traffic * hops[d.origin][d.destination] for d in D)
print("fewest-hop routing:", lower, "wavelengths")
```

The capacities also have a lower bound. The traffic from a set S of nodes to the other nodes
must cross the links that leave S, so with C wavelengths on every link,
C ≥ (traffic leaving S) / (number of links leaving S) for every set S.
`nx.edge_boundary(G, S)` lists the links leaving S, and `itertools.combinations` gives every set
of k nodes.

```python
S = {"Madrid", "Barcelona", "Valencia", "Zaragoza", "Sevilla"}     # all but Malaga and Murcia
links = list(nx.edge_boundary(G, S))
need = sum(d.traffic for d in D if d.origin in S and d.destination not in S)
print(f"{need} wavelengths leave S on the links {links}: C >= {math.ceil(need / len(links))}")

best = None
for size in range(1, G.number_of_nodes()):
    for S in itertools.combinations(G.nodes, size):
        bound = math.ceil(sum(d.traffic for d in D if d.origin in S and d.destination not in S)
                          / len(list(nx.edge_boundary(G, S))))
        if best is None or bound > best[0]:
            best = (bound, sorted(S))
print("most restrictive set:", best[1], "-> C >=", best[0])
draw(G, [["Sevilla", "Malaga"], ["Valencia", "Murcia"]], title="The two links entering Malaga and Murcia")
```

## 8. Generating networks

NetworkX generates many kinds of graphs: rings, grids, random graphs, and Waxman graphs, whose
nodes are placed at random in a square and connected with a probability that decreases with
their distance. These graphs are undirected; `network.from_networkx` turns one into a network of
PyNet2Plan, with two links per edge and lengths taken from the positions, which can be saved with
`network.save_topology` and opened in the tool.

```python
generated = {"ring": nx.cycle_graph(8), "grid": nx.grid_2d_graph(3, 4),
             "Waxman": nx.waxman_graph(12, beta=0.7, alpha=0.35, seed=7),
             "random": nx.gnm_random_graph(10, 16, seed=3)}
fig, axes = plt.subplots(1, 4, figsize=(15, 3.8))
for ax, (kind, H) in zip(axes, generated.items()):
    pos = nx.get_node_attributes(H, "pos") or nx.spring_layout(H, seed=0)
    nx.draw(H, pos, ax=ax, node_size=60, node_color="#2a78d6", edge_color="#9e9e9e")
    ax.set_title(f"{kind}: {H.number_of_nodes()} nodes, {H.number_of_edges()} edges\n"
                 f"connected: {nx.is_connected(H)}", fontsize=11)
plt.show()
plt.close(fig)
W = network.from_networkx(generated["Waxman"], capacity=40, name="Waxman 12")
print(network.describe(W))
```

These are all the calls needed in Part 2. The complete tour, with more comments, is the script
`labs/lab1_networkx_tour.py` described in handout 2.
