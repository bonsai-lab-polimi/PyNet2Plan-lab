"""
TEMPLATE for a new algorithm                    (files starting with '_' are ignored)
=====================================================================================

Copy this file to a new name WITHOUT the leading underscore (for example
``formulations/my_formulation.py``), then use "Run > Reload formulations" in
the GUI: it appears in the list of algorithms.

The rules
---------
* define ``solve(G, demands, ...)``; every extra parameter needs a default
  value and becomes a field of the parameter dialog in the GUI;
* ``G`` is a networkx.DiGraph with only the nodes/links that are up; links
  have the attributes "fibers" (number of fibers, 1 by default), "capacity"
  (wavelengths per fiber) and "length" (km); the capacity of a link is
  fibers x capacity wavelengths;
* ``demands`` is a list of Demand (d.id, d.origin, d.destination, d.traffic);
  demands that cannot be routed because of failures are not included;
* return a ``Solution`` with one ``sol.add_route(d, path, traffic)`` for
  every path used (path = list of nodes);
* do NOT check the solution yourself: PyNet2Plan validates it (capacity,
  flow, splitting, wavelengths) according to the flags below.
"""

import pulp

from pynet2plan.helpers import solve_ilp, value  # noqa: F401
from pynet2plan.solution import Solution

NAME = "My new algorithm"
SPLITTABLE = True               # may a demand use several paths?
ALLOWS_BLOCKING = False         # may some traffic be left unrouted?
WAVELENGTH_CONTINUITY = False   # must every route list its wavelength indices?
ORDER = 50                      # position in the list of algorithms of the GUI (optional)

PARAMETER_HELP = {"time_limit": "Maximum solver time in seconds."}


def solve(G, demands, time_limit=60):
    prob = pulp.LpProblem("my_formulation", pulp.LpMinimize)
    # ... variables:   v = prob.add_variable("name", lowBound=0, cat=pulp.LpInteger)
    # ... objective:   prob += pulp.lpSum(...)
    # ... constraints: prob += pulp.lpSum(...) <= ..., "constraint_name"
    solve_ilp(prob, time_limit=time_limit)
    sol = Solution(objective=value(prob.objective))
    # ... sol.add_route(d, ["A", "B", "C"], 2)
    return sol
