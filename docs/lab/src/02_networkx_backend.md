---
title: Networks as NetworkX graphs
subtitle: Lab handout 2
tag: To be read while running the script labs/lab1_networkx_tour.py.
footer: Handout 2, NetworkX
---

## Introduction

All the operations that PyNet2Plan performs on a network are based on
[NetworkX](https://networkx.org), the Python library for graphs that is also used in the rest of
the course. There is no special class for networks: a network is a `networkx.DiGraph`, the
traffic is a list of demands, and an algorithm is a Python function that receives both.

The script `labs/lab1_networkx_tour.py` illustrates the main ideas in seven short cells. It is
run from the lab folder, with the virtual environment active:

```bash
python labs/lab1_networkx_tour.py           # prints the results and saves the figures in results/networkx_tour/
python labs/lab1_networkx_tour.py --show    # also opens the figures
```

The cells, separated by `# %%` lines, can also be executed one at a time in VS Code. In the
following sections each cell is reproduced together with the output it prints.

## 1. A network is a directed graph

A link is unidirectional: a pair of fibres between two cities corresponds to two links, one in
each direction, and each of them has its own capacity. In NetworkX such a network is a directed
graph (`DiGraph`) whose nodes and edges carry attributes. Nodes have a drawing position `x`,
`y` and, optionally, the geographic coordinates `lat` and `lon`. Links have a number of
`fibers` (1 by default), a `capacity`, which is the number of wavelengths of each fiber, and a
`length` (km). A link therefore offers `fibers × capacity` wavelengths. All the networks used
in the lab have one fiber per link.

{{cell labs/lab1_networkx_tour.py 1}}

{{output tour 1}}

The functions of `pynet2plan.network` (`add_node`, `add_link`, `load_topology`, `save_topology`
and so on) build exactly the same graph. In addition they check the values (for example, a
capacity must be a whole number and a link cannot start and end at the same node) and compute
the lengths from the positions of the nodes.

## 2. The Spain-7 network

{{cell labs/lab1_networkx_tour.py 2}}

{{output tour 2}}

{{figure ../figures/nx_spain7.svg | Figure 1. Spain-7 and the length of its links. The cell above draws it with the functions of NetworkX; the method `G.to_undirected()` merges the two directions of each link into a single line. The figures of this handout show the same data redrawn with TikZ.}}

The table below lists the NetworkX expressions used most often in the lab.

| purpose | NetworkX |
|---|---|
| nodes and links | `G.nodes`, `G.edges`; with their attributes `G.nodes(data=True)`, `G.edges(data=True)` |
| a single attribute | `G.nodes["Madrid"]["lat"]`, `G.edges["Madrid", "Zaragoza"]["capacity"]`, `G.edges["Madrid", "Zaragoza"]["fibers"]` |
| links leaving or entering a node n | `G.out_edges(n)`, `G.in_edges(n)` |
| neighbours of a node | `G.successors(n)`, `G.predecessors(n)`, `G.out_degree(n)` |
| copies and sub-networks | `G.copy()`, `G.subgraph(nodes)`, `G.edge_subgraph(links)` |

## 3. Shortest paths

The meaning of "shortest" depends on the weight. Without a weight NetworkX counts the hops,
that is the number of links; with `weight="length"` it adds the lengths in kilometres. From
Sevilla to Valencia the two criteria give different paths.

{{cell labs/lab1_networkx_tour.py 3}}

{{output tour 3}}

{{figure ../figures/nx_shortest_paths.svg | Figure 2. Path with the fewest hops (left) and shortest path in kilometres (right) from Sevilla to Valencia.}}

## 4. The k shortest paths

The function `nx.shortest_simple_paths` enumerates the loop-free paths between two nodes in
order of increasing length. The first k of them are the candidate paths of the route
formulations and of the k-shortest-path heuristic studied in the next labs; the helper
`pynet2plan.helpers.k_shortest_paths(G, s, t, k)` is implemented in this way.

{{cell labs/lab1_networkx_tour.py 4}}

{{output tour 4}}

{{figure ../figures/nx_k_shortest_paths.svg | Figure 3. The three shortest paths from Zaragoza to Malaga by length.}}

## 5. Connectivity, failures and cuts

NetworkX also answers questions on the robustness of a network: whether it is connected, which
single failures disconnect it, and so on. A failure is simply the removal of an edge. In the
graphical interface, *Fail / repair selected* has the same effect on the copy of the network
that is given to the algorithms.

{{cell labs/lab1_networkx_tour.py 5}}

{{output tour 5}}

The last lines of the cell check a cut condition. If the nodes are divided into a set S and the
remaining nodes, all the traffic from S to the other nodes has to cross the links that leave S.
With the same capacity C on every link this gives

<div class="math">
C · (number of links leaving S) ≥ traffic from S to the other nodes, for every set S.
</div>

The script examines all the 126 possible sets S of Spain-7. The most restrictive one contains
all the nodes except Malaga and Murcia: 68 wavelengths have to reach Malaga and Murcia, and
only two links enter these nodes (Sevilla to Malaga and Valencia to Murcia). Hence C must be at
least 34. The same number appears in handout 3, where the ILP turns out to be infeasible for
every capacity below 34.

{{figure ../figures/nx_cut.svg | Figure 4. The most restrictive cut for the traffic matrix of the lab: the traffic for Malaga and Murcia (green) must cross the two links in orange.}}

## 6. Generating networks

NetworkX contains generators for many families of graphs. The function
`pynet2plan.network.from_networkx` converts any of them into a PyNet2Plan network: each
undirected edge becomes two links, and the node positions are scaled to a square of
1000 × 1000 units so that the lengths are comparable to kilometres. The result can be saved
and opened in the graphical interface.

{{cell labs/lab1_networkx_tour.py 6}}

{{output tour 6}}

{{figure ../figures/nx_generated.svg | Figure 5. Four generated networks. The Waxman model places the nodes at random and connects nearby nodes with higher probability, as happens in real fibre networks.}}

## 7. Repeatable traffic matrices

{{cell labs/lab1_networkx_tour.py 7}}

{{output tour 7}}

The traffic matrix of the lab is therefore the result of `random_traffic(G, 24, 4, 16, seed=9)`
and can be regenerated by anybody. The last line computes a lower bound for the ILP of
handout 3. If the capacities were unlimited, every demand would follow a path with the fewest
hops, and the total number of wavelengths used would be 408.

## 8. The graph inside an ILP formulation

The formulations in `formulations/` read the network with the same NetworkX calls. As an
example, the flow conservation constraints of the splittable flow formulation (handout 3) are
written with `G.nodes`, `G.out_edges(n)` and `G.in_edges(n)`:

{{excerpt formulations/splittable_flow.py | # Flow conservation, for every demand and every node | prob += out_flow - in_flow == rhs}}

## Exercises

The exercises are in the file `labs/lab1_exercises.py`. Each one is a function that ends with
`raise NotCompletedError(...)`; write the code where the comments indicate and delete that line.
The file already contains the network (Spain-7, with 40 wavelengths on every link), the traffic
matrix of the lab and three helper functions: `fiber_cut(G, u, v)` returns a copy of the network
without the two directions of a link, `fibers(G)` lists the fibres once, and
`fewest_hop_bound(G, D)` computes the bound of section 7. The script runs every exercise and
reports those not completed yet:

```bash
python labs/lab1_exercises.py              # all the exercises
python labs/lab1_exercises.py --only 2     # only exercise 2
```

The same exercises are in the notebook `labs/lab1_exercises.ipynb`, which can be opened in
Jupyter or VS Code, or in Google Colab without installing anything (*File > Upload notebook*, or
the link *Open in Colab* at the top of the notebook in the lab repository). Its first part is a
short introduction to NetworkX that follows sections 1 to 7 of this handout, and its second part
contains the exercises. The notebook is self-contained: it includes the networks and traffic
matrices used by the exercises, the few functions of PyNet2Plan that they call, and a function
`draw(H, paths)` that shows a network and some paths on a map. Changes made in Colab are kept only with *File > Save a copy in Drive*.

| exercise | question | NetworkX |
|---|---|---|
| 1 | Paths from Sevilla to Valencia with the fewest hops and in kilometres, before and after the cut of the fibre Madrid-Valencia. How many hops and kilometres does the cut add? | `shortest_path`, `path_weight` |
| 2 | For each of the 8 single fibre cuts: does the network remain connected, and how many wavelengths does the fewest-hop routing of the lab traffic need? Which cut is the most harmful? | `is_strongly_connected`, `shortest_path_length` |
| 3 | The cut bound of section 5 for the other traffic matrix, `data/traffic/spain7_traffic.csv`: which set S is the most restrictive, and which capacity does it require? | `itertools.combinations` |
| 4 | With the fewest-hop routing of the lab traffic, how many wavelengths cross each node in transit (neither origin nor destination)? | `shortest_path` |
| 5 | Add Bilbao, linked to Madrid and Zaragoza with 40 wavelengths, generate 30 demands of 4 to 16 wavelengths with seed 3, and save both files. Open them in the graphical interface and run the splittable flow formulation. Is the problem feasible? Find the smallest feasible capacity with a sweep and compare it with the cut bound of exercise 3. | `add_city`, `add_link`, `random_traffic` |
| 6 (optional) | Generate the first connected Waxman network with 15 nodes (section 6) and open it in the graphical interface. | `waxman_graph`, `from_networkx` |
| 7 (optional) | Number of nodes and links, links per node and diameter in hops of Spain-7, NSFNET-14, COST239 and GEANT2. | `diameter` |

Compare the results of exercise 2 with the fibre cuts of handout 3 (section 5), where the
capacity of the links is limited to 60 wavelengths.
