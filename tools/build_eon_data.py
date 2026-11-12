#!/usr/bin/env python3
"""
Rebuild the data files of the EON lab
=====================================

    data/topologies/eon6.json                  the A-F network of the lecture (lengths in km)
    data/traffic_eon/eon6_traffic.csv          120 random demands in Gb/s (the EON notebook's demands)
    data/traffic_eon/eon6_slide_example.csv    CR1, CR3, CR2 of the slide "Amplification and 3R regeneration"
    data/traffic_eon/nsfnet14_eon_traffic.csv  150 demands for NSFNET-14 (long links), seed 14
    data/traffic_eon/italy10_eon_traffic.csv   150 demands for Italy-10 (short links), seed 10
    data/traffic_eon/<name>_eon_traffic.csv    spain7 (seed 7), cost239 (239), example_cities (1)
    data/traffic_eon/eon6_long_fast.csv        88 long, fast demands on EON-6 (self-check of rsa_3r)
    data/traffic_eon/spain7_first_plan.csv, spain7_lab4_*.csv
                                               the teaching examples on Spain-7 (see EXAMPLE_FILES below)
    data/traffic_eon/real/top<N>_<name>_eon_traffic.csv   every real topology, seed N

EON traffic is in Gb/s and lives in data/traffic_eon/, apart from the
wavelength traffic of data/traffic/ (1 λ is not 1 Gb/s: loaded in the EON
window, a wavelength file gives a few Gb/s per demand, all 100G QPSK).

The random demands draw the data rate uniformly among the rates of
data/eon/transponders.csv (100-800 Gb/s) with numpy's default_rng(seed) (see
pynet2plan.eon.traffic). Number of demands: 8 per node, between 150 and 400
(EON-6: 120, as in the notebook): with 320 slots per link rsa_greedy fills
the busiest link of most networks to ~90 %, with some blocking on the larger
ones. Networks with intercontinental links (thousands of km, beyond every
reach) block most demands for reach: there 3R is the only way. The other data
files are built by tools/build_reference_data.py and are not touched.

    python tools/build_eon_data.py
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from pynet2plan import network, traffic  # noqa: E402
from pynet2plan.eon import transponders  # noqa: E402
from pynet2plan.eon.runner import EON6_LINKS  # noqa: E402
from pynet2plan.eon.traffic import generation_comment, random_eon_traffic  # noqa: E402

TOPO_DIR = os.path.join(ROOT, "data", "topologies")
TRAFFIC_DIR = os.path.join(ROOT, "data", "traffic_eon")

#: drawing positions of EON-6 (the notebook's layout: A B C on top, D E F below)
EON6_POS = {"A": (0, 1), "B": (1, 1), "C": (2, 1), "D": (0, 0), "E": (1, 0), "F": (2, 0)}


def eon6():
    G = network.new_network("EON-6")
    G.graph["description"] = ("The 6-node network of the EON lab (lecture 'Amplification and 3R "
                              "regeneration'): 7 bidirectional fibres of 100-800 km. A-B-C "
                              "(700 + 500 km) is the slide's 3R example.")
    for n, (x, y) in EON6_POS.items():
        network.add_node(G, n, x=1000.0 * x, y=1000.0 * y)
    for u, v, km in EON6_LINKS:
        network.add_link(G, u, v, capacity=network.DEFAULT_CAPACITY, length=km, bidirectional=True)
    return G


def num_demands(G) -> int:
    """8 demands per node, between 150 and 400."""
    return max(150, min(400, 8 * G.number_of_nodes()))


def save_random(G, stem, num, seed, rates, topology_file=None):
    demands = random_eon_traffic(G, num, rates, seed=seed)
    comments = [f"EON traffic for {G.graph['name']}: data rates in Gb/s"]
    if topology_file:
        comments.append(f"topology: {G.graph['name']} ({topology_file})")
    comments.append(generation_comment("random_eon_traffic", num_demands=num, rates=rates, seed=seed))
    path = os.path.join(TRAFFIC_DIR, stem)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    traffic.save_traffic(demands, path, comments=comments)
    return demands


# ----------------------------------------------------------------------
# The teaching examples on Spain-7, the network of the wavelength labs
# (File > Teaching examples in the EON window). Each one is built (with a seed)
# so that one comparison shows clearly with 320 slots per link; the expected
# numbers are in the file header and in tests/test_eon_examples.py.
# ----------------------------------------------------------------------
RATES = [100, 200, 300, 400, 500, 600, 700, 800]
HIGH = [500, 600, 700, 800]
EX2_CUT = ("Murcia", "Valencia")        # the fibre whose cut takes down the most demands of RSA
#: Lab 4, part 1 (1+1 protection, in GHz): 2 = example 1, 6 = example 2, 5 = example 3;
#: Lab 4 (EON, in slots): 1 = example 1 (the grid of slots), 3 = example 2 (no 3R vs 3R)
EXAMPLE_FILES = {1: "spain7_first_plan.csv", 2: "spain7_lab4_protection.csv", 3: "spain7_lab4_3r.csv",
                 5: "spain7_lab4_one_demand.csv", 6: "spain7_lab4_ilp.csv"}
ILP_SLOTS = 96                               # 1200 GHz per link: not enough for every backup path
ONE_DEMAND = ("Madrid", "Valencia", 700)     # one lightpath without protection, two on the backup path


def long_pairs(G, km=1000):
    """Ordered node pairs whose shortest path is at least ``km`` long."""
    import networkx as nx
    dist = dict(nx.all_pairs_dijkstra_path_length(G, weight="length"))
    return [(a, b) for a in G for b in G if a != b and dist[a][b] >= km]


def long_high_demands(G, n, rng, first_id=0, km=1000):
    """``n`` demands of 500-800 Gb/s between far-apart nodes (>= ``km``)."""
    pairs = long_pairs(G, km)
    return [traffic.Demand(first_id + i, *pairs[rng.integers(len(pairs))], int(rng.choice(HIGH)))
            for i in range(n)]


def example_demands(G, which):
    """The demands of teaching example ``which`` on Spain-7 (G)."""
    import numpy as np
    if which == 1:          # RSA basics: light load, 7 transponder types (800G and 300G 64QAM reach no link)
        return random_eon_traffic(G, 30, RATES, seed=0)
    if which == 2:          # RSA vs 1+1: both serve everything; the cut of Murcia-Valencia
        return random_eon_traffic(G, 40, RATES, seed=0)
    if which == 3:          # RSA vs 3R: long, fast demands; RSA runs out of spectrum, 3R does not
        return long_high_demands(G, 100, np.random.default_rng(2), km=600)
    if which == 6:          # 1+1 heuristic vs ILP: 40 demands, a scarce band
        return random_eon_traffic(G, 40, RATES, seed=18)
    if which == 5:          # one demand: the backup path is a detour that needs two lightpaths
        return [traffic.Demand(0, *ONE_DEMAND)]
    raise ValueError(which)


def example_texts(G):
    """The header of every example file, with the numbers of its runs."""
    from pynet2plan.eon import runner
    out = []

    def s(alg, D, **kw):
        return runner.run_eon(G, D, alg, save=False, **kw).summary
    D = example_demands(G, 1)
    a = runner.run_eon(G, D, "rsa_greedy", save=False)
    types = sorted({lp["transponder"] for lp in a.tables["lightpaths"]}, key=lambda t: -int(t.split("G")[0]))
    out.append((1, EXAMPLE_FILES[1], [
        f"Lab 4, example 4 - RSA on the grid of slots, Spain-7: {len(D)} demands, light "
        f"load. rsa_greedy serves {a.summary['served_demands']};", f"look at the Lightpaths tab: {len(types)} "
        "transponder types, fast modulations on short paths, slow but far-reaching ones on long paths",
        "(800G PCS 64QAM and 300G 64QAM reach 150 and 100 km: shorter than every link of Spain-7); a demand above",
        "800 Gb/s or beyond a reach needs several lightpaths."]))
    D = example_demands(G, 2)
    H = G.copy()
    H.graph["cut_after_planning"] = EX2_CUT
    g, p = s("rsa_greedy", D), s("rsa_1plus1_two_step", D)
    gc = runner.run_eon(H, D, "rsa_greedy", save=False).summary
    pc = runner.run_eon(H, D, "rsa_1plus1_two_step", save=False).summary
    cut = f"{EX2_CUT[0]}-{EX2_CUT[1]}"
    out.append((2, EXAMPLE_FILES[2], [
        f"Lab 4, example 1 - no protection vs 1+1 protection on Spain-7: {len(D)} demands, both serve all "
        "of them (fair comparison).",
        f"1+1 needs {p['transponders'] / g['transponders']:.1f}x the transponders and "
        f"{p['total_slots_used'] / g['total_slots_used']:.1f}x the spectrum, but no fibre cut takes a demand down "
        f"(no protection: up to {g['demands_down_worst_cut']}).",
        f"The EON window cuts fibre {cut} AFTER planning (the line below): the results show "
        f"{gc['demands_down_cut']} demands DOWN", f"without protection (rsa_greedy) and "
        f"{pc['demands_switched_cut']} demands switched to their backup path with 1+1.",
        f"cut fibre: {cut}",
        "spectrum unit: GHz"]))
    D = example_demands(G, 5)
    a = runner.run_eon(G, D, "rsa_greedy", save=False).solution.lightpaths
    b = runner.run_eon(G, D, "rsa_1plus1_two_step", save=False).solution.lightpaths
    w, k = [lp for lp in b if not lp.backup], [lp for lp in b if lp.backup]
    out.append((5, EXAMPLE_FILES[5], [
        f"Lab 4, example 3 - one demand, {ONE_DEMAND[0]} -> {ONE_DEMAND[1]} at {ONE_DEMAND[2]} Gb/s, on Spain-7.",
        f"Without protection: {len(a)} lightpath of {a[0].transponder} on {' > '.join(a[0].path)}.",
        f"With 1+1: the same working lightpath, and a backup path {' > '.join(k[0].path)}, too long for",
        f"{a[0].transponder}: {len(k)} lightpaths of {k[0].transponder}. Transponders: {2 * len(a)} without "
        f"protection, {2 * (len(w) + len(k))} with 1+1.",
        f"The EON window cuts fibre {ONE_DEMAND[0]}-{ONE_DEMAND[1]} AFTER planning (the line below): without "
        "protection the demand is DOWN,", "with 1+1 it switches to its longer backup path.",
        f"cut fibre: {ONE_DEMAND[0]}-{ONE_DEMAND[1]}",
        "spectrum unit: GHz"]))
    D = example_demands(G, 6)
    H = G.copy()
    H.graph["cut_after_planning"] = EX2_CUT
    h = {alg: runner.run_eon(H, D, alg, save=False, num_slots=ILP_SLOTS).summary
         for alg in ("rsa_greedy", "rsa_1plus1_two_step", "rsa_1plus1_ilp")}
    out.append((6, EXAMPLE_FILES[6], [
        f"Lab 4, example 2 - no protection vs 1+1 heuristic vs 1+1 ILP on Spain-7: {len(D)} demands, "
        f"{ILP_SLOTS * 12.5:g} GHz per link ({ILP_SLOTS} slots),",
        f"the fibre {EX2_CUT[0]}-{EX2_CUT[1]} cut after planning. No protection (rsa_greedy): "
        f"{h['rsa_greedy']['served_demands']} planned, {h['rsa_greedy']['served_after_cut']} served after the cut.",
        f"1+1 heuristic (rsa_1plus1_two_step), the demands one at a time: {h['rsa_1plus1_two_step']['served_demands']}; "
        f"1+1 ILP (rsa_1plus1_ilp), all the demands together: {h['rsa_1plus1_ilp']['served_demands']}.",
        "Every protected demand is still served after the cut.",
        f"cut fibre: {EX2_CUT[0]}-{EX2_CUT[1]}",
        f"slots per link: {ILP_SLOTS}",
        "spectrum unit: GHz"]))
    D = example_demands(G, 3)
    g, r = s("rsa_greedy", D), s("solutions/rsa_3r", D)
    out.append((3, EXAMPLE_FILES[3], [
        f"Lab 4, example 5 - no 3R vs 3R on Spain-7: {len(D)} demands of 500-800 Gb/s between far-apart nodes "
        "(>= 600 km).",
        "Without 3R (rsa_greedy) the long paths need slow types (more slots per Gb/s): the spectrum runs out and",
        f"{len(D) - g['served_demands']} demands are blocked. With 3R (rsa_3r) the fast types are regenerated "
        f"where their reach ends: all {r['served_demands']} served,",
        f"with less spectrum ({r['total_slots_used']} vs {g['total_slots_used']} slots), but "
        f"{r['regenerators']} regenerators (more hardware).",
        "spectrum unit: slots"]))
    return out


def main():
    rates = transponders.rates(transponders.load_table())
    G = eon6()
    network.save_topology(G, os.path.join(TOPO_DIR, "eon6.json"))
    save_random(G, "eon6_traffic.csv", 120, 42, rates)
    D = traffic.Demand
    traffic.save_traffic([D(1, "A", "C", 100), D(3, "B", "C", 600), D(2, "A", "C", 200)],
                         os.path.join(TRAFFIC_DIR, "eon6_slide_example.csv"),
                         comments=["The slide's example (Gb/s): CR1 (A,C) 100G QPSK reaches 3000 km;",
                                   "CR3 (B,C) 600 Gb/s fills the bottom of the band on B-C;",
                                   "CR2 (A,C) 200 Gb/s: 200G 16QAM reaches 900 km < 1200 km (the red X)."])
    for name, num, seed in (("nsfnet14", 150, 14), ("italy10", 150, 10)):
        H = network.load_topology(os.path.join(TOPO_DIR, f"{name}.json"))
        save_random(H, f"{name}_eon_traffic.csv", num, seed, rates)
    import numpy as np
    traffic.save_traffic(long_high_demands(G, 88, np.random.default_rng(15)),       # >= 1000 km on EON-6
                         os.path.join(TRAFFIC_DIR, "eon6_long_fast.csv"),
                         comments=["88 demands of 500-800 Gb/s between far-apart nodes of EON-6 (>= 1000 km):",
                                   "rsa_greedy blocks 10 (spectrum), rsa_3r serves all 88 with 87 x 3R",
                                   "(self-check of the 3R exercise). Built by tools/build_eon_data.py."])
    spain = network.load_topology(os.path.join(TOPO_DIR, "spain7.json"))
    for which, fname, text in example_texts(spain):
        traffic.save_traffic(example_demands(spain, which), os.path.join(TRAFFIC_DIR, fname),
                             comments=text + ["topology: Spain-7 (data/topologies/spain7.json)",
                                              "Data rates in Gb/s; built by tools/build_eon_data.py "
                                              f"(example_demands(spain7, {which}))."])
    for name, seed in (("spain7", 7), ("cost239", 239), ("example_cities", 1),
                       ("spain7_tight", 7), ("italy10_tight", 10), ("cost239_3r", 239)):   # the Lab 3 variants
        H = network.load_topology(os.path.join(TOPO_DIR, f"{name}.json"))
        save_random(H, f"{name}_eon_traffic.csv", num_demands(H), seed, rates, f"data/topologies/{name}.json")
    real = sorted(f for f in os.listdir(os.path.join(TOPO_DIR, "real")) if f.endswith(".json"))
    for f in real:
        H = network.load_topology(os.path.join(TOPO_DIR, "real", f))
        stem = os.path.splitext(f)[0]
        seed = int(stem[3:].split("_")[0])                  # top103_geant -> 103
        save_random(H, os.path.join("real", f"{stem}_eon_traffic.csv"), num_demands(H), seed, rates,
                    f"data/topologies/real/{f}")
    print(f"EON data files written in {TRAFFIC_DIR} ({len(real)} real topologies).")


if __name__ == "__main__":
    main()
