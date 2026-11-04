"""
Unsplittable flow formulation (link-flow ILP)                    [EXERCISE - to complete]
=========================================================================================

Same problem as the splittable flow formulation (splittable_flow.py, read it
first!), but now ALL the wavelengths of a demand must follow ONE single path:
the traffic of a demand cannot be split.

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

What to do
----------
Complete the four TODO blocks below. In each block, write your code and then
DELETE the line ``raise NotCompletedError(...)``. Run the formulation from
the GUI (or with ``python -m pynet2plan check formulations/unsplittable_flow.py``):
PyNet2Plan tells you which TODO is still missing, shows the line of any error,
and checks that your solution really is unsplittable and respects the
capacities.

Then compare it with the splittable formulation (objective and time) while
varying the link capacity: Run > Compare algorithms (sweep).
"""

import pulp

from pynet2plan.errors import NotCompletedError
from pynet2plan.helpers import flow_to_routes, solve_ilp, value
from pynet2plan.solution import Solution

NAME = "Unsplittable flow formulation"
SPLITTABLE = False           # every demand must use exactly one path (checked!)
ALLOWS_BLOCKING = False
ORDER = 2                    # position in the list of algorithms of the GUI

PARAMETER_HELP = {"time_limit": "Maximum solver time in seconds."}


def solve(G, demands, time_limit=60):
    prob = pulp.LpProblem("unsplittable_flow", pulp.LpMinimize)

    # ---- TODO 1: decision variables ----------------------------------
    # Create the binary variables x[d.id, i, j] for every demand d and every
    # link (i, j), exactly as in splittable_flow.py but with cat=pulp.LpBinary.
    # Every variable needs a unique name, e.g. f"x_{d.id}_{i}_{j}".
    x = {}
    raise NotCompletedError("TODO 1: create the binary variables x[d.id, i, j].")

    # ---- TODO 2: objective function ----------------------------------
    # Minimize the total number of wavelengths used: Σ_d Σ_e h_d · x_{d,e}.
    # Hint: prob += pulp.lpSum(... for d in demands for (i, j) in G.edges)
    raise NotCompletedError("TODO 2: write the objective function.")

    # ---- TODO 3: flow conservation constraints -----------------------
    # One constraint for every demand d and node n. The right-hand side is
    # 1 at the origin, -1 at the destination, 0 elsewhere (x is binary!).
    raise NotCompletedError("TODO 3: write the flow conservation constraints.")

    # ---- TODO 4: capacity constraints --------------------------------
    # One constraint for every link (i, j): the wavelengths of all the demands
    # crossing it (h_d · x_{d,e}) cannot exceed the capacity u_e of the link,
    # G.edges[i, j]["fibers"] * G.edges[i, j]["capacity"].
    raise NotCompletedError("TODO 4: write the capacity constraints.")

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
