"""
Route formulation WITHOUT wavelength continuity (VWP)            [EXERCISE - to complete]
=========================================================================================

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

What to do
----------
Complete the five TODO blocks below. In each block, write your code and then
DELETE the line ``raise NotCompletedError(...)``. The model is the same kind of
ILP as splittable_flow.py, but the variables belong to (demand, candidate
path) pairs instead of (demand, link) pairs. Test it from the GUI (button
Check) or with ``python -m pynet2plan check formulations/route_formulation_vwp.py``:
on the test network the optimum is 20, as for the splittable flow formulation.

Then compare it with the flow formulations for k = 1, 2, 3 (handout 5).
"""

from itertools import islice

import networkx as nx
import pulp

from pynet2plan.errors import NotCompletedError
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
    # paths[d.id] = list of the k shortest loopless paths (by number of hops)
    # from d.origin to d.destination, each path a list of nodes. As in
    # handout 2, section 4: nx.shortest_simple_paths(G, origin, destination)
    # yields the paths in order of increasing length, and islice(..., k)
    # takes the first k of them.
    paths = {}
    raise NotCompletedError("TODO 1: compute the k candidate paths of every demand.")

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
    # r[d.id, p] >= 0 and integer: wavelengths of demand d on its p-th
    # candidate path, for p = 0, 1, ..., len(paths[d.id]) - 1. Every variable
    # needs a unique name, e.g. f"r_{d.id}_{p}".
    r = {}
    raise NotCompletedError("TODO 2: create the variables r[d.id, p].")

    # ---- TODO 3: objective function -------------------------------------
    # Minimize Σ_d Σ_p l_p · r_{d,p}, where l_p = len(paths[d.id][p]) - 1 is
    # the number of links of the p-th path of d.
    raise NotCompletedError("TODO 3: write the objective function.")

    # ---- TODO 4: demand constraints -------------------------------------
    # One constraint for every demand d: the wavelengths on its candidate
    # paths add up to its traffic, Σ_p r_{d,p} = d.traffic.
    raise NotCompletedError("TODO 4: write the demand constraints.")

    # ---- TODO 5: capacity constraints -----------------------------------
    # One constraint for every link (i, j): the sum of r[d_id, p] over the
    # pairs (d_id, p) in paths_through[i, j] cannot exceed the capacity
    # G.edges[i, j]["fibers"] * G.edges[i, j]["capacity"].
    raise NotCompletedError("TODO 5: write the capacity constraints.")

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
