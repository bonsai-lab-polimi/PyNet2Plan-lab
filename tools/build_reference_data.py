#!/usr/bin/env python3
"""
Rebuild the reference topologies and traffic matrices of data/:

    data/topologies/spain7.json      7-node Spanish backbone (CND Lab 1 style)
    data/topologies/nsfnet14.json    NSFNET T1 backbone, 14 nodes / 21 links (common variant)
    data/topologies/cost239.json     COST239 pan-European network, 11 nodes / 26 links
    data/topologies/italy10.json     fictitious mesh of the 10 largest Italian cities
    data/topologies/example_cities.json   the small example of PyNet2Plan v1

    data/traffic/<name>_traffic.csv  a seeded random traffic matrix for each
    data/traffic/italy10_traffic_matrix.csv  the Italy-10 matrix, in N x N layout
    data/traffic/spain7_traffic_split_vs_unsplit.csv  Spain-7 matrix where splitting
                                     matters for a wide range of capacities

All links are bidirectional (two unidirectional links), 40 wavelengths each,
lengths = great-circle distance between the cities. Run from the project root:

    python tools/build_reference_data.py

NOTE (Spain-7): the traffic matrix of the original lab file
(example7nodes_withTrafficWavelength.n2p) is not available here, so a
seeded random full-mesh matrix (42 demands) is generated instead. Replace
data/traffic/spain7_traffic.csv with the lab matrix if you have it (same
node names).
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from pynet2plan import network, traffic  # noqa: E402

TOPO_DIR = os.path.join(ROOT, "data", "topologies")
TRAFFIC_DIR = os.path.join(ROOT, "data", "traffic")


def city_network(name, description, cities, edges, capacity=40):
    G = network.new_network(name)
    G.graph["description"] = description
    for label, lat, lon in cities:
        network.add_node(G, label, lat=lat, lon=lon)
    for a, b in edges:
        network.add_link(G, a, b, capacity=capacity, bidirectional=True)
    return G


def spain7():
    cities = [("Madrid", 40.4168, -3.7038), ("Barcelona", 41.3874, 2.1686),
              ("Valencia", 39.4699, -0.3763), ("Sevilla", 37.3891, -5.9845),
              ("Zaragoza", 41.6488, -0.8891), ("Malaga", 36.7213, -4.4214),
              ("Murcia", 37.9922, -1.1307)]
    edges = [("Madrid", "Zaragoza"), ("Zaragoza", "Barcelona"), ("Barcelona", "Valencia"),
             ("Valencia", "Murcia"), ("Murcia", "Malaga"), ("Malaga", "Sevilla"),
             ("Sevilla", "Madrid"), ("Madrid", "Valencia")]
    return city_network("Spain-7", "7-node Spanish backbone, 16 unidirectional links, "
                                   "40 wavelengths per link (CND Lab 1 style).", cities, edges)


def nsfnet14():
    cities = [("Seattle", 47.6062, -122.3321), ("Palo Alto", 37.4419, -122.1430),
              ("San Diego", 32.7157, -117.1611), ("Salt Lake City", 40.7608, -111.8910),
              ("Boulder", 40.0150, -105.2705), ("Houston", 29.7604, -95.3698),
              ("Lincoln", 40.8136, -96.7026), ("Champaign", 40.1164, -88.2434),
              ("Pittsburgh", 40.4406, -79.9959), ("Atlanta", 33.7490, -84.3880),
              ("Ann Arbor", 42.2808, -83.7430), ("Ithaca", 42.4440, -76.5019),
              ("Princeton", 40.3573, -74.6672), ("College Park", 38.9807, -76.9369)]
    n = [c[0] for c in cities]
    pairs = [(1, 2), (1, 3), (1, 8), (2, 3), (2, 4), (3, 6), (4, 5), (4, 11), (5, 6), (5, 7),
             (6, 10), (6, 14), (7, 8), (8, 9), (9, 10), (9, 12), (9, 13), (11, 12), (11, 13),
             (12, 14), (13, 14)]
    edges = [(n[a - 1], n[b - 1]) for a, b in pairs]
    return city_network("NSFNET-14", "NSFNET T1 backbone (a common 14-node / 21-link "
                                     "variant), 40 wavelengths per link.", cities, edges)


def cost239():
    cities = [("Amsterdam", 52.3676, 4.9041), ("Berlin", 52.5200, 13.4050),
              ("Brussels", 50.8503, 4.3517), ("Copenhagen", 55.6761, 12.5683),
              ("London", 51.5074, -0.1278), ("Luxembourg", 49.6116, 6.1319),
              ("Milan", 45.4642, 9.1900), ("Paris", 48.8566, 2.3522),
              ("Prague", 50.0755, 14.4378), ("Vienna", 48.2082, 16.3738),
              ("Zurich", 47.3769, 8.5417)]
    edges = [("London", "Amsterdam"), ("London", "Brussels"), ("London", "Paris"),
             ("London", "Copenhagen"), ("Amsterdam", "Berlin"), ("Amsterdam", "Brussels"),
             ("Amsterdam", "Luxembourg"), ("Amsterdam", "Copenhagen"), ("Berlin", "Copenhagen"),
             ("Berlin", "Prague"), ("Berlin", "Vienna"), ("Berlin", "Paris"),
             ("Brussels", "Paris"), ("Brussels", "Luxembourg"), ("Brussels", "Milan"),
             ("Copenhagen", "Prague"), ("Luxembourg", "Paris"), ("Luxembourg", "Prague"),
             ("Luxembourg", "Zurich"), ("Paris", "Zurich"), ("Paris", "Milan"),
             ("Milan", "Zurich"), ("Milan", "Vienna"), ("Prague", "Vienna"),
             ("Prague", "Zurich"), ("Vienna", "Zurich")]
    return city_network("COST239", "COST239-style pan-European network (11 nodes, 26 "
                                   "bidirectional links), 40 wavelengths per link.", cities, edges)


def italy10():
    cities = [("Milan", 45.4642, 9.1900), ("Turin", 45.0703, 7.6869), ("Genoa", 44.4056, 8.9463),
              ("Venice", 45.4408, 12.3155), ("Bologna", 44.4949, 11.3426),
              ("Florence", 43.7696, 11.2558), ("Rome", 41.9028, 12.4964),
              ("Naples", 40.8518, 14.2681), ("Bari", 41.1171, 16.8719),
              ("Palermo", 38.1157, 13.3615)]
    edges = [("Milan", "Turin"), ("Milan", "Genoa"), ("Turin", "Genoa"), ("Milan", "Venice"),
             ("Milan", "Bologna"), ("Venice", "Bologna"), ("Genoa", "Florence"),
             ("Bologna", "Florence"), ("Florence", "Rome"), ("Venice", "Bari"),
             ("Rome", "Naples"), ("Rome", "Bari"), ("Naples", "Bari"), ("Naples", "Palermo"),
             ("Bari", "Palermo")]
    return city_network("Italy-10", "Fictitious mesh network of the 10 largest Italian "
                                    "cities, 40 wavelengths per link.", cities, edges)


def example_cities():
    path = os.path.join(ROOT, "data", "topologies", "example_cities.json")
    legacy = os.path.join(ROOT, "tests", "data", "legacy_v1_topology.json")
    if os.path.isfile(legacy):
        G = network.load_topology(legacy)
        G.graph.pop("embedded_traffic", None)
        G.graph.pop("load_warnings", None)
        G.graph.pop("source_file", None)
        return G
    if os.path.isfile(path):
        return network.load_topology(path)
    return None


def save(G, stem, traffic_kind, seed, lo, hi, num=None, matrix_copy=False):
    network.save_topology(G, os.path.join(TOPO_DIR, f"{stem}.json"))
    if traffic_kind == "full_mesh":
        demands = traffic.full_mesh_traffic(G, lo, hi, seed=seed)
        comment = traffic.generation_comment("full_mesh_traffic", min_traffic=lo, max_traffic=hi,
                                             seed=seed)
    else:
        demands = traffic.random_traffic(G, num, lo, hi, seed=seed)
        comment = traffic.generation_comment("random_traffic", num_demands=num, min_traffic=lo,
                                             max_traffic=hi, seed=seed)
    comments = [f"topology: {G.graph['name']} (data/topologies/{stem}.json)", comment,
                "traffic = number of wavelengths requested"]
    traffic.save_traffic(demands, os.path.join(TRAFFIC_DIR, f"{stem}_traffic.csv"), comments=comments)
    if matrix_copy:
        traffic.save_traffic(demands, os.path.join(TRAFFIC_DIR, f"{stem}_traffic_matrix.csv"),
                             layout="matrix", nodes=list(G.nodes),
                             comments=comments + ["same demands, N x N matrix layout "
                                                  "(row = origin, column = destination)"])
    print(f"{stem}: {G.number_of_nodes()} nodes, {G.number_of_edges()} links, "
          f"{len(demands)} demands, {traffic.total_traffic(demands)} wavelengths")


def spain7_split_vs_unsplit():
    """A Spain-7 matrix where splitting matters over a wide range of capacities.

    24 demands of 4-16 wavelengths (few, large demands): the unsplittable
    formulation cannot "fill" the scarce links exactly, so it needs more
    wavelengths than the splittable one for C = 35..56 (except 41 and 43),
    and at C = 34 only the splittable formulation is feasible.
    """
    G = network.load_topology(os.path.join(TOPO_DIR, "spain7.json"))
    demands = traffic.random_traffic(G, 24, 4, 16, seed=9)
    comments = [
        "topology: Spain-7 (data/topologies/spain7.json)",
        traffic.generation_comment("random_traffic", num_demands=24, min_traffic=4,
                                   max_traffic=16, seed=9),
        "traffic = number of wavelengths requested",
        "Splittable vs. unsplittable flow formulation (total wavelengths used), uniform capacity C:",
        "  C <= 33: both infeasible      C = 34: splittable 431, unsplittable INFEASIBLE",
        "  C = 35: 430 vs 460   C = 36-40: 429..425 vs 443   C = 42-56: 423..409 vs 424/422",
        "  C = 41, 43: equal (424, 422)  C >= 57: equal (408, every demand on a shortest path)",
    ]
    path = os.path.join(TRAFFIC_DIR, "spain7_traffic_split_vs_unsplit.csv")
    traffic.save_traffic(demands, path, comments=comments)
    print(f"spain7_traffic_split_vs_unsplit: {len(demands)} demands, "
          f"{traffic.total_traffic(demands)} wavelengths")


def main():
    os.makedirs(TOPO_DIR, exist_ok=True)
    os.makedirs(TRAFFIC_DIR, exist_ok=True)
    save(spain7(), "spain7", "full_mesh", seed=23, lo=1, hi=6)
    spain7_split_vs_unsplit()
    save(nsfnet14(), "nsfnet14", "random", seed=14, lo=1, hi=8, num=30)
    save(cost239(), "cost239", "random", seed=239, lo=1, hi=8, num=25)
    save(italy10(), "italy10", "random", seed=10, lo=1, hi=10, num=36, matrix_copy=True)
    G = example_cities()
    if G is not None:
        save(G, "example_cities", "random", seed=1, lo=1, hi=10, num=8)


if __name__ == "__main__":
    main()
