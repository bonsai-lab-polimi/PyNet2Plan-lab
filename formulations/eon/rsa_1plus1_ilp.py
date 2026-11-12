"""
1+1 protection: route formulation (ILP)                                 [GIVEN - complete]
=========================================================================================

The heuristic (rsa_1plus1_two_step.py) serves the demands one
at a time: the first demand takes the best pair of paths, even if a later
demand would have needed that spectrum more. The route formulation chooses
the pairs of ALL the demands together, as the route formulation of Lab 2.

Every demand d has a set of candidate pairs Q_d (working, backup) that share
no fibre: for each of the k shortest paths w from s to t, the pair (w, the
shortest path that avoids the fibres of w). On each path the lightpaths are
chosen as in RSA (n lightpaths of one type that reaches the path), so a pair q
takes s_{q,e} slots of 12.5 GHz on every link e (0 if q does not use e).

Notation                                       in the code
--------                                       -----------
Q_d          candidate pairs of demand d       pairs[d.id]: (working, backup)
s_{q,e}      slots taken by the pair q on e    load[d.id][q][e]
c_q          total spectrum of q (slots)       cost[d.id][q] = Σ_e s_{q,e}
S            slots per link                    num_slots(G)

Decision variables
------------------
x_{d,q} ∈ {0, 1}   demand d is served on the pair q
y_d     ∈ {0, 1}   demand d is blocked

Model
-----
min   M · Σ_d y_d  +  Σ_d Σ_{q∈Q_d} c_q · x_{d,q}           (first serve, then save spectrum)

s.t.  Σ_{q∈Q_d} x_{d,q} + y_d = 1                         ∀ d∈D   (one pair, or blocked)
      Σ_d Σ_{q∈Q_d} s_{q,e} · x_{d,q} <= S                ∀ e∈E   (capacity of every link)

M is larger than the spectrum of any plan, so the model first serves as many
demands as possible, then uses the least spectrum. The capacity counts the
slots of every link but not their position: after the ILP, the lightpaths of
the chosen pairs are placed with first-fit, as in the heuristic; a demand
that does not fit is blocked for "spectrum" (rare).
"""

import networkx as nx
import pulp

from pynet2plan.eon.helpers import (Spectrum, fibre, k_shortest_paths, num_slots, path_fibres, path_links,
                                   transponder_table)
from pynet2plan.eon.protection import lightpaths_of
from pynet2plan.eon.solution import EonSolution
from pynet2plan.helpers import solve_ilp, value

NAME = "route formulation (1+1 protection)"
PROTECTION = True            # every served demand must have a fibre-disjoint backup (checked!)
REGENERATION = False

PARAMETER_HELP = {
    "k": "Number of candidate working paths per demand (k shortest by km); each gets its shortest backup.",
    "time_limit": "Maximum solver time in seconds.",
}


def candidate_pairs(G, s, t, k):
    """For each of the k shortest paths w: (w, the shortest path avoiding the fibres of w)."""
    pairs = []
    for working in k_shortest_paths(G, s, t, k):
        used = path_fibres(working)
        H = G.copy()
        H.remove_edges_from([(u, v) for (u, v) in G.edges if fibre(u, v) in used])
        try:
            backup = nx.shortest_path(H, s, t, weight="length")
        except nx.NetworkXNoPath:
            continue
        if (working, backup) not in pairs:
            pairs.append((working, backup))
    return pairs


def solve(G, demands, k=3, time_limit=120):
    table = transponder_table(G)
    S = num_slots(G)

    # ---- the candidate pairs and their spectrum (given) -------------------------
    pairs, combos, load, cost = {}, {}, {}, {}
    for d in demands:
        pairs[d.id], combos[d.id], load[d.id], cost[d.id] = [], [], [], []
        for working, backup in candidate_pairs(G, d.origin, d.destination, k):
            combo_w = lightpaths_of(G, table, working, d.traffic)
            combo_b = lightpaths_of(G, table, backup, d.traffic)
            if combo_w is None or combo_b is None:
                continue                                  # a path out of reach of every type
            on_link = {}
            for path, combo in ((working, combo_w), (backup, combo_b)):
                for e in path_links(path):
                    on_link[e] = on_link.get(e, 0) + sum(tp.slots for tp, _ in combo)
            pairs[d.id].append((working, backup))
            combos[d.id].append((combo_w, combo_b))
            load[d.id].append(on_link)
            cost[d.id].append(sum(on_link.values()))
    M = 1 + sum(max(c, default=0) for c in cost.values())

    # ---- the model ---------------------------------------------------------------
    prob = pulp.LpProblem("route_formulation_1plus1", pulp.LpMinimize)
    x = {(d.id, q): prob.add_variable(f"x_{d.id}_{q}", cat=pulp.LpBinary)
         for d in demands for q in range(len(pairs[d.id]))}
    y = {d.id: prob.add_variable(f"y_{d.id}", cat=pulp.LpBinary) for d in demands}

    prob += (M * pulp.lpSum(y.values())
             + pulp.lpSum(cost[d.id][q] * x[d.id, q] for d in demands for q in range(len(pairs[d.id]))))
    for d in demands:
        prob += pulp.lpSum(x[d.id, q] for q in range(len(pairs[d.id]))) + y[d.id] == 1, f"demand_{d.id}"
    for (u, v) in G.edges:
        terms = [load[d.id][q][u, v] * x[d.id, q] for d in demands for q in range(len(pairs[d.id]))
                 if (u, v) in load[d.id][q]]
        if terms:
            prob += pulp.lpSum(terms) <= S, f"capacity_{u}_{v}"

    solve_ilp(prob, time_limit=time_limit)

    # ---- place the lightpaths of the chosen pairs with first-fit (given) ----------
    spectrum = Spectrum(G)
    sol = EonSolution(objective=value(prob.objective))
    for d in demands:
        chosen = [q for q in range(len(pairs[d.id])) if value(x[d.id, q]) > 0.5]
        if not chosen:
            sol.block(d, "spectrum" if pairs[d.id] else "no disjoint path")
            continue
        q = chosen[0]
        (working, backup), (combo_w, combo_b) = pairs[d.id][q], combos[d.id][q]
        plan = [(working, tp, False) for tp, _ in combo_w] + [(backup, tp, True) for tp, _ in combo_b]
        trial = spectrum.copy()
        starts = []
        for path, tp, _ in plan:
            start = trial.first_fit(path, tp.slots)
            if start is None:
                break
            trial.occupy(path, start, tp.slots)
            starts.append(start)
        if len(starts) < len(plan):
            sol.block(d, "spectrum")                      # the slots are there, not side by side
            continue
        spectrum = trial
        for (path, tp, is_backup), start in zip(plan, starts):
            sol.add_lightpath(d, path, tp, start, backup=is_backup)
    return sol
