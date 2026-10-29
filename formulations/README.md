# Writing an algorithm

Every `.py` file in this folder, except those whose name starts with `_`, is an algorithm and
appears in the list of the graphical interface. New algorithms can be started from
`_template.py`. The file `splittable_flow.py` is a complete and commented example and should be
read before the exercises.

## Interface

```python
import pulp
from pynet2plan.helpers import solve_ilp, value, flow_to_routes
from pynet2plan.solution import Solution

NAME = "My algorithm"            # name shown in the interface
SPLITTABLE = True                # may a demand use several paths?            (checked)
ALLOWS_BLOCKING = False          # may part of the traffic remain unrouted?   (checked)
WAVELENGTH_CONTINUITY = False    # must every route list its wavelengths?     (checked)
ORDER = 10                       # position in the list of the interface      (optional)
PARAMETER_HELP = {"k": "number of candidate paths"}        # optional
PARAMETER_CHOICES = {"order": ["a", "b"]}                  # optional

def solve(G, demands, k=3, time_limit=60):
    ...
    return sol
```

Every parameter after `G` and `demands` must have a default value. Each parameter becomes a
field of the *Parameters...* dialog, and its type is taken from the default value. The function
`solve` must return a `Solution`.

## Inputs

`G` is a `networkx.DiGraph` that contains only the nodes and links in operation; failed elements
are removed before `solve` is called.

```python
for (i, j) in G.edges:                 # every unidirectional link
    G.edges[i, j]["fibers"]            # number of fibers (int, 1 by default)
    G.edges[i, j]["capacity"]          # wavelengths per fiber (int)
    G.edges[i, j]["length"]            # km
G.nodes                                # node names
G.out_edges(n), G.in_edges(n)          # links leaving and entering n
nx.shortest_simple_paths(G, s, t, weight="length")    # paths in order of length (generator)
```

A link with several fibers offers `fibers * capacity` wavelengths in total, and with
wavelength continuity each wavelength can be used once per fiber. All the networks of the
lab exercises have one fiber per link.

`demands` is a list of `Demand` objects with the attributes `d.id`, `d.origin`,
`d.destination` and `d.traffic` (wavelengths). Demands that cannot be routed at all because of
failures are not included in the list; they are reported as UNREACHABLE.

## Output

```python
sol = Solution(objective=value(prob.objective))
sol.add_route(d, ["Madrid", "Zaragoza", "Barcelona"], 3)                   # 3 wavelengths on this path
sol.add_route(d, ["Madrid", "Valencia", "Barcelona"], 1, wavelengths=[4])  # with wavelength continuity
sol.info["candidate_paths"] = 120      # optional values, saved in summary.csv
return sol
```

A path is the list of the nodes it visits. Routes that carry no traffic are ignored, so all the
candidate paths can be added with their value, even when it is zero.

The solution does not need to be checked inside the algorithm. PyNet2Plan verifies that every
demand is completely carried, that the paths exist, that the link capacities are respected,
that no demand is split when `SPLITTABLE = False`, and that the wavelengths are valid and free
of conflicts (at most one route per wavelength and fiber) when `WAVELENGTH_CONTINUITY = True`. A violation gives the status `INVALID`.

## PuLP essentials

```python
prob = pulp.LpProblem("name", pulp.LpMinimize)
x = prob.add_variable("x_0_A_B", lowBound=0, cat=pulp.LpInteger)   # or pulp.LpBinary
prob += pulp.lpSum([...])                       # objective (an expression, not a comparison)
prob += pulp.lpSum([...]) <= 40, "cap_A_B"      # constraint, with an optional unique name
solve_ilp(prob, time_limit=60)                  # CBC or HiGHS
value(x)                                        # value in the solution
```

Every variable needs a unique name, which is obtained by writing all its indices in the name,
for example `f"x_{d.id}_{i}_{j}"`. Variables are created with `prob.add_variable(...)`, which
works with PuLP 3.3 and PuLP 4. `solve_ilp` returns `"Optimal"`, or `"Feasible"` when the time
limit is reached with a solution, and otherwise raises `InfeasibleError`, `UnboundedError`
(often a missing constraint) or `TimeLimitError`, so the status does not need to be checked.
The command `prob.writeLP("model.lp")` writes the model as text, which helps when looking for
errors.

## Helper functions (`pynet2plan.helpers`)

| function | purpose |
|---|---|
| `solve_ilp(prob, time_limit)` | solves with CBC or HiGHS and records statistics (variables, constraints, time) |
| `value(x)` | value of a variable or expression (0.0 if undefined) |
| `flow_to_routes(flow, s, t)` | decomposes a flow `{(i, j): amount}` into `[(path, amount), ...]` |
| `k_shortest_paths(G, s, t, k, weight=None)` | k loop-free shortest paths, by hops or with `weight="length"` |
| `path_links(path)` | converts `["A", "B", "C"]` into `[("A", "B"), ("B", "C")]` |

## Debugging

The output of `print` appears in the terminal and in the details of the dialog shown at the end
of the run. The command `python -m pynet2plan check formulations/<file>.py` runs a file on a small
network of 5 nodes and prints the status, the messages and the problems found. When an
exception occurs, the dialog shows the file, the line and the code that failed; the complete
traceback is available under *Show full details*.
