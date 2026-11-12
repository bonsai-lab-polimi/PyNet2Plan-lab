"""
Route formulation WITHOUT wavelength continuity (VWP)  [SOLUTION]           
=====================================================================================

Instead of deciding the flow on every link (flow formulation), we first
compute a set of candidate paths P_d for every demand d -- here the k
shortest paths by number of hops -- and then decide how many wavelengths of
the demand to send on each candidate path.

"Without wavelength continuity" (Virtual Wavelength Path, VWP): every node can
convert wavelengths, so a lightpath may use different wavelengths on different
links. Only the NUMBER of wavelengths used on each link matters, not which ones.

Notation                                   in the code
--------                                   -----------
P_d          candidate paths of demand d   paths[d.id] (lists of nodes)
l_p          number of links (hops) of p   len(path) - 1
δ(e)         paths that traverse link e    see 'paths_through' below

Decision variables
------------------
r_{d,p} >= 0   wavelengths of demand d routed on its candidate path p (integer)

Model
-----
min   Σ_{d∈D} Σ_{p∈P_d} l_p · r_{d,p}                          (total wavelengths used)

s.t.  Σ_{p∈P_d} r_{d,p} = h_d                                   ∀ d∈D   (demand)
      Σ_{(d,p): e∈p} r_{d,p} <= u_e                             ∀ e∈E   (capacity)

u_e = f_e · W_e is the capacity of link e: G.edges[i, j]["fibers"] fibers with
G.edges[i, j]["capacity"] wavelengths each (one fiber in the lab data).

With a small k the problem can become infeasible even if the flow
formulation is feasible: the good paths are simply not among the candidates.
"""

from itertools import islice

import networkx as nx
import pulp

from pynet2plan.helpers import solve_ilp, value
from pynet2plan.solution import Solution

NAME = "Route formulation, no wavelength continuity (VWP)"
SPLITTABLE = True
ALLOWS_BLOCKING = False
ORDER = 3                    # position in the list of algorithms of the GUI

PARAMETER_HELP = {
    "k": "Number of candidate paths per demand (k shortest paths by number of hops).",
    "time_limit": "Maximum solver time in seconds.",
}


def solve(G, demands, k=3, time_limit=60):
    # ---- TODO 1: candidate paths ---------------------------------------
    paths = {}
    for d in demands:
        paths[d.id] = list(islice(nx.shortest_simple_paths(G, d.origin, d.destination), k))

    # ---- links of the paths (given) ------------------------------------
    # links_of([A, B, C]) = [(A, B), (B, C)]; paths_through[i, j] lists the
    # pairs (d.id, p) whose candidate path p traverses the link (i, j)
    def links_of(path):
        return list(zip(path[:-1], path[1:]))

    paths_through = {(i, j): [] for (i, j) in G.edges}
    for d in demands:
        for p, path in enumerate(paths[d.id]):
            for e in links_of(path):
                paths_through[e].append((d.id, p))

    prob = pulp.LpProblem("route_formulation_vwp", pulp.LpMinimize)

    # ---- TODO 2: decision variables -------------------------------------
    r = {}
    for d in demands:
        for p in range(len(paths[d.id])):
            r[d.id, p] = prob.add_variable(f"r_{d.id}_{p}", lowBound=0, cat=pulp.LpInteger)

    # ---- TODO 3: objective function -------------------------------------
    prob += pulp.lpSum((len(paths[d.id][p]) - 1) * r[d.id, p]
                       for d in demands for p in range(len(paths[d.id])))

    # ---- TODO 4: demand constraints -------------------------------------
    for d in demands:
        prob += pulp.lpSum(r[d.id, p] for p in range(len(paths[d.id]))) == d.traffic, f"demand_{d.id}"

    # ---- TODO 5: capacity constraints -----------------------------------
    for (i, j) in G.edges:
        u = G.edges[i, j]["fibers"] * G.edges[i, j]["capacity"]     # fibers x wavelengths per fiber
        prob += pulp.lpSum(r[d_id, p] for (d_id, p) in paths_through[i, j]) <= u, f"capacity_{i}_{j}"

    # ---- solve (given) -------------------------------------------------
    solve_ilp(prob, time_limit=time_limit)

    # ---- build the solution (given) -------------------------------------
    # one route for every candidate path with r > 0
    sol = Solution(objective=value(prob.objective))
    sol.info["candidate_paths"] = sum(len(p) for p in paths.values())
    for d in demands:
        for p, path in enumerate(paths[d.id]):
            sol.add_route(d, path, value(r[d.id, p]))
    return sol
