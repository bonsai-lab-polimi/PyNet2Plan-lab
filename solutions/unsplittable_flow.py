"""
Unsplittable flow formulation (link-flow ILP)          [SOLUTION]           
=========================================================================================

Same problem as the splittable flow formulation, but now ALL the wavelengths
of a demand must follow ONE single path (the traffic cannot be split).

Notation: see splittable_flow.py.

Decision variables
------------------
x_{d,e} ∈ {0, 1}   1 if the (single) path of demand d uses link e

Model
-----
min   Σ_{d∈D} Σ_{e∈E} h_d · x_{d,e}                            (total wavelengths used)

s.t.  Σ_{e∈δ+(n)} x_{d,e} - Σ_{e∈δ-(n)} x_{d,e} =  1   if n = s_d
                                                 = -1   if n = t_d       ∀ d∈D, n∈N
                                                 =  0   otherwise        (flow conservation)

      Σ_{d∈D} h_d · x_{d,e} <= u_e                              ∀ e∈E    (capacity)

u_e = f_e · W_e: G.edges[i, j]["fibers"] fibers with G.edges[i, j]["capacity"]
wavelengths each (as in splittable_flow.py; one fiber in the lab data).
"""

import pulp

from pynet2plan.helpers import flow_to_routes, solve_ilp, value
from pynet2plan.solution import Solution

NAME = "Unsplittable flow formulation"
SPLITTABLE = False           # every demand must use exactly one path
ALLOWS_BLOCKING = False
ORDER = 2                    # position in the list of algorithms of the GUI

PARAMETER_HELP = {"time_limit": "Maximum solver time in seconds."}


def solve(G, demands, time_limit=60):
    prob = pulp.LpProblem("unsplittable_flow", pulp.LpMinimize)

    # ---- TODO 1: decision variables ----------------------------------
    x = {}
    for d in demands:
        for (i, j) in G.edges:
            x[d.id, i, j] = prob.add_variable(f"x_{d.id}_{i}_{j}", cat=pulp.LpBinary)

    # ---- TODO 2: objective function ----------------------------------
    prob += pulp.lpSum(d.traffic * x[d.id, i, j] for d in demands for (i, j) in G.edges)

    # ---- TODO 3: flow conservation constraints -----------------------
    for d in demands:
        for n in G.nodes:
            out_flow = pulp.lpSum(x[d.id, i, j] for (i, j) in G.out_edges(n))
            in_flow = pulp.lpSum(x[d.id, i, j] for (i, j) in G.in_edges(n))
            if n == d.origin:
                rhs = 1
            elif n == d.destination:
                rhs = -1
            else:
                rhs = 0
            prob += out_flow - in_flow == rhs, f"flow_{d.id}_{n}"

    # ---- TODO 4: capacity constraints --------------------------------
    for (i, j) in G.edges:
        u = G.edges[i, j]["fibers"] * G.edges[i, j]["capacity"]
        prob += pulp.lpSum(d.traffic * x[d.id, i, j] for d in demands) <= u, f"capacity_{i}_{j}"

    # ---- solve (given) -------------------------------------------------
    solve_ilp(prob, time_limit=time_limit)

    # ---- build the solution (given) -------------------------------------
    # x[d.id, i, j] = 1 on the links of the path of d: the flow of demand d on
    # link (i, j) is d.traffic * x[d.id, i, j]; flow_to_routes finds the path.
    sol = Solution(objective=value(prob.objective))
    for d in demands:
        flow = {(i, j): d.traffic * value(x[d.id, i, j]) for (i, j) in G.edges}
        for path, amount in flow_to_routes(flow, d.origin, d.destination):
            sol.add_route(d, path, amount)
    return sol
