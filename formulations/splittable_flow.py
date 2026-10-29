"""
Splittable flow formulation (link-flow ILP)                     [GIVEN - complete]
=================================================================================

Route all the demands over the network using as few wavelengths as possible
(summed over all the links). The traffic of a demand may be SPLIT over
several paths.

Notation                                   in the code
--------                                   -----------
G = (N, E)   directed network              G (a networkx.DiGraph)
e = (i, j)   link from node i to node j    for (i, j) in G.edges
f_e          fibers of link e              G.edges[i, j]["fibers"]   (1 in the lab data)
W_e          wavelengths per fiber of e    G.edges[i, j]["capacity"]
u_e          capacity of link e (λ)        f_e · W_e
D            set of demands                demands (list of Demand)
s_d, t_d     origin, destination of d      d.origin, d.destination
h_d          wavelengths requested by d    d.traffic
δ+(n)        links leaving node n          G.out_edges(n)
δ-(n)        links entering node n         G.in_edges(n)

Decision variables
------------------
x_{d,e} >= 0   number of wavelengths of demand d carried on link e
               (integer, since wavelengths are discrete)

Model
-----
min   Σ_{d∈D} Σ_{e∈E} x_{d,e}                                  (total wavelengths used)

s.t.  Σ_{e∈δ+(n)} x_{d,e} - Σ_{e∈δ-(n)} x_{d,e} =  h_d   if n = s_d
                                                 = -h_d   if n = t_d     ∀ d∈D, n∈N
                                                 =  0     otherwise      (flow conservation)

      Σ_{d∈D} x_{d,e} <= u_e                                    ∀ e∈E  (capacity)

The solution gives, for each demand, the amount of flow on every link; the
helper ``flow_to_routes`` turns it into paths ("flow decomposition").
"""

import pulp

from pynet2plan.helpers import flow_to_routes, solve_ilp, value
from pynet2plan.solution import Solution

NAME = "Splittable flow formulation"
SPLITTABLE = True            # a demand may use several paths
ALLOWS_BLOCKING = False      # all the traffic must be carried
ORDER = 1                    # position in the list of algorithms of the GUI

PARAMETER_HELP = {
    "time_limit": "Maximum solver time in seconds.",
}


def solve(G, demands, time_limit=60):
    prob = pulp.LpProblem("splittable_flow", pulp.LpMinimize)

    # ------------------------------------------------------------------
    # Decision variables x[d.id, i, j] >= 0, integer (wavelengths)
    # (a dictionary indexed by demand id and link)
    # ------------------------------------------------------------------
    x = {}
    for d in demands:
        for (i, j) in G.edges:
            x[d.id, i, j] = prob.add_variable(f"x_{d.id}_{i}_{j}", lowBound=0, cat=pulp.LpInteger)

    # ------------------------------------------------------------------
    # Objective: total number of wavelengths used on all the links
    # ------------------------------------------------------------------
    prob += pulp.lpSum(x[d.id, i, j] for d in demands for (i, j) in G.edges)

    # ------------------------------------------------------------------
    # Flow conservation, for every demand and every node
    # ------------------------------------------------------------------
    for d in demands:
        for n in G.nodes:
            out_flow = pulp.lpSum(x[d.id, i, j] for (i, j) in G.out_edges(n))
            in_flow = pulp.lpSum(x[d.id, i, j] for (i, j) in G.in_edges(n))
            if n == d.origin:
                rhs = d.traffic
            elif n == d.destination:
                rhs = -d.traffic
            else:
                rhs = 0
            prob += out_flow - in_flow == rhs, f"flow_{d.id}_{n}"

    # ------------------------------------------------------------------
    # Capacity of every link
    # ------------------------------------------------------------------
    for (i, j) in G.edges:
        u = G.edges[i, j]["fibers"] * G.edges[i, j]["capacity"]     # fibers x wavelengths per fiber
        prob += pulp.lpSum(x[d.id, i, j] for d in demands) <= u, f"capacity_{i}_{j}"

    # ------------------------------------------------------------------
    # Solve (raises InfeasibleError if there is no feasible routing)
    # ------------------------------------------------------------------
    solve_ilp(prob, time_limit=time_limit)

    # ------------------------------------------------------------------
    # Build the solution: decompose the flow of each demand into paths
    # ------------------------------------------------------------------
    sol = Solution(objective=value(prob.objective))
    for d in demands:
        flow = {(i, j): value(x[d.id, i, j]) for (i, j) in G.edges}
        for path, amount in flow_to_routes(flow, d.origin, d.destination):
            sol.add_route(d, path, amount)
    return sol
