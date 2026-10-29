#!/usr/bin/env python3
"""
Lab 1 - exercises on the NetworkX back end (handout 2)                [EXERCISE - to complete]
=========================================================================================

The network is Spain-7 and the traffic is the matrix of the lab,
data/traffic/spain7_traffic_split_vs_unsplit.csv (24 demands, 229 wavelengths).
Exercises 1 to 5 are done in the lab; 6 and 7 are optional.

Each exercise is a function below. Write its code where the comments say, then
delete the line ``raise NotCompletedError(...)``. The script runs every
exercise and reports the ones not completed yet; the cells of
labs/lab1_networkx_tour.py contain all the NetworkX calls you need.

    python labs/lab1_exercises.py              # every exercise
    python labs/lab1_exercises.py --only 2 5   # only some of them

The files written by the exercises are saved in results/lab1_exercises/.
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import networkx as nx  # noqa: E402

from pynet2plan import network, traffic  # noqa: E402
from pynet2plan.errors import NotCompletedError  # noqa: E402

TOPOLOGY = os.path.join(ROOT, "data", "topologies", "spain7.json")
TRAFFIC = os.path.join(ROOT, "data", "traffic", "spain7_traffic_split_vs_unsplit.csv")
OUT = os.path.join(ROOT, "results", "lab1_exercises")


# ---- helpers (given) ------------------------------------------------------------------
def fiber_cut(G, u, v):
    """A copy of G without the two directions of the link u-v (a fibre cut)."""
    H = G.copy()
    H.remove_edges_from([(u, v), (v, u)])
    return H


def fibers(G):
    """Every pair of opposite links once: ('Madrid', 'Zaragoza'), ..."""
    seen = []
    for u, v in G.edges:
        if (u, v) not in seen and (v, u) not in seen:
            seen.append((u, v))
    return seen


def fewest_hop_bound(G, D):
    """Wavelengths used if every demand follows a path with the fewest hops (handout 2, section 7)."""
    hops = dict(nx.shortest_path_length(G))
    return sum(d.traffic * hops[d.origin][d.destination] for d in D)


def km(G, path):
    return nx.path_weight(G, path, weight="length")


# ---- exercises --------------------------------------------------------------------------
def exercise_1(G, D):
    """Paths from Sevilla to Valencia, before and after the cut of the fibre Madrid-Valencia."""
    # ---- TODO 1 ----
    # For G and for fiber_cut(G, "Madrid", "Valencia"), print the path with the fewest hops
    # (nx.shortest_path) and the shortest path in kilometres (weight="length") from Sevilla
    # to Valencia, with their number of hops and their length (km(H, path)).
    raise NotCompletedError("TODO 1: paths before and after the cut")


def exercise_2(G, D):
    """The effect of every single fibre cut on the fewest-hop bound of the lab traffic.

    For each cut: is the network still connected, and how many wavelengths does the
    fewest-hop routing of the lab traffic need?"""
    # ---- TODO 2 ----
    # For every fibre (u, v) in fibers(G): H = fiber_cut(G, u, v); check
    # nx.is_strongly_connected(H); if it is, print fewest_hop_bound(H, D) and its increase
    # with respect to fewest_hop_bound(G, D) = 408. Which cut increases the bound the most?
    raise NotCompletedError("TODO 2: fewest-hop bound after every single fibre cut")


def exercise_3(G, D):
    """Cut bound (handout 2, section 5) for the other traffic matrix of Spain-7."""
    # ---- TODO 3 ----
    # Load data/traffic/spain7_traffic.csv, then repeat the computation of section 5 of
    # handout 2 (cell 5 of the tour): for every set S of nodes, the traffic from S to the
    # other nodes divided by the number of links leaving S, rounded up. Print the largest
    # value, the set S and the number of links.
    raise NotCompletedError("TODO 3: cut bound for spain7_traffic.csv")


def exercise_4(G, D):
    """Transit traffic of every node with the fewest-hop routing of the lab traffic.

    Transit = wavelengths of the demands whose path crosses the node, without starting
    or ending there."""
    # ---- TODO 4 ----
    # For every demand d, path = nx.shortest_path(G, d.origin, d.destination); add
    # d.traffic to every intermediate node path[1:-1]. Print the nodes from the most
    # to the least loaded.
    raise NotCompletedError("TODO 4: transit traffic of every node")


def exercise_5(G, D):
    """A new city: Bilbao, linked to Madrid and Zaragoza; topology and traffic saved for the GUI."""
    # ---- TODO 5 ----
    # H = G.copy(); add the node with network.add_city(H, "Bilbao", allow_online=False) and
    # two bidirectional links of 40 wavelengths with network.add_link(H, "Bilbao", "Madrid",
    # capacity=40, bidirectional=True) (and the same towards Zaragoza). Generate
    # traffic.random_traffic(H, 30, 4, 16, seed=3), save the topology and the traffic in OUT
    # with network.save_topology and traffic.save_traffic, then open both files in the
    # graphical interface and run the splittable flow formulation.
    raise NotCompletedError("TODO 5: Spain-8 with Bilbao")


def exercise_6(G, D):
    """(Optional) A connected Waxman network with 15 nodes, saved for the GUI."""
    # ---- TODO 6 ----
    # As in cell 6 of the tour: nx.waxman_graph(15, beta=0.6, alpha=0.3, seed=seed) for
    # seed = 0, 1, 2, ... until nx.is_connected; convert it with network.from_networkx and
    # save it in OUT.
    raise NotCompletedError("TODO 6: a connected Waxman network")


def exercise_7(G, D):
    """(Optional) Size of some real networks: nodes, links, average out-degree, diameter in hops."""
    # ---- TODO 7 ----
    # For spain7.json, nsfnet14.json, cost239.json and real/top22_geant2.json in
    # data/topologies: number of nodes and links, links per node, nx.diameter(H).
    raise NotCompletedError("TODO 7: size of some real networks")


EXERCISES = {1: exercise_1, 2: exercise_2, 3: exercise_3, 4: exercise_4, 5: exercise_5,
             6: exercise_6, 7: exercise_7}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", type=int, nargs="+", choices=sorted(EXERCISES), help="exercises to run")
    args = ap.parse_args(argv)
    G = network.load_topology(TOPOLOGY)
    D = traffic.load_traffic(TRAFFIC, G)
    for n in args.only or sorted(EXERCISES):
        func = EXERCISES[n]
        print(f"\nExercise {n}. {func.__doc__.split(chr(10))[0].strip()}")
        try:
            func(G, D)
        except NotCompletedError as e:
            print(f"  not completed yet: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
