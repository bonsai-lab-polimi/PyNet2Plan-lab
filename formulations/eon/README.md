# Writing an EON algorithm (elastic optical networks)

Every `.py` file of this folder (except those starting with `_`) is an
algorithm of the **EON window** (`python -m pynet2plan eon`). **Read `rsa_greedy.py` first**: it is complete and
commented. The other files are complete too (given):

In the order of the labs (and of the window's lists):

| lab | file | what | status |
|---|---|---|---|
| 3 | `rsa_greedy.py` | no protection, no 3R: the greedy plan (k shortest paths, the transponders with the least spectrum, first-fit); in Lab 4 the greedy RSA | **given** |
| 3 | `rsa_1plus1_two_step.py` | 1+1 protection, two-step: shortest path, then the shortest backup path without its fibres | **given** |
| 3 | `rsa_1plus1_ilp.py` | 1+1 protection: route formulation (ILP, PuLP) choosing the pairs of all the demands together; compare it with the two-step heuristic | **given** |
| 4 | `rsa_3r.py` | 3R regeneration (segments, per-segment slots) | **given** |
| 4 | `rsa_3r_budget.py` | 3R with a budget on the transponder cost (example 6) | **empty** (to be written) |

*Check* runs a file on a small test network; `python -m pytest tests/test_eon_exercises.py -v`
checks rsa_3r against known values.

## The interface

```python
from pynet2plan.eon.helpers import (Spectrum, best_combination, k_shortest_paths, path_length,
                                   transponder_table, types_reaching)
from pynet2plan.eon.solution import EonSolution

NAME = "My EON algorithm"        # shown in the EON window
PROTECTION = False               # True: every served demand needs a fibre-disjoint backup  (checked)
REGENERATION = False             # True: lightpaths may use 3R regenerators                  (checked)
PARAMETER_HELP = {"k": "number of candidate paths"}        # optional
PARAMETER_CHOICES = {"order": ["as_given", "largest_first"]}  # optional

def solve(G, demands, k=3, order="as_given"):
    ...
    return sol                   # an EonSolution
```

Every parameter after `G, demands` needs a default value (it becomes a field
of the *Parameters…* dialog).

## The inputs

```python
G.edges[i, j]["length"]          # km of the unidirectional link i -> j (only the links that are up)
table = transponder_table(G)     # list of Transponder: tp.name, tp.rate (Gb/s), tp.slots, tp.reach (km), tp.cost
spectrum = Spectrum(G)           # all slots free; spectrum.used[(i, j)] = numpy array of booleans
spectrum.num_slots               # slots per link (320 by default)
d.id, d.origin, d.destination, d.traffic      # a demand; d.traffic is a data rate in Gb/s
```

Every **unidirectional link has its own spectrum**. A **fibre** is the pair of
opposite links `{(u, v), (v, u)}`: a cut takes down both, so a 1+1 backup
path must share no fibre with its working path (`path_fibres`, `fibre`).

## The output

```python
sol = EonSolution()
sol.add_lightpath(d, ["A", "B", "C"], tp, start=8)                         # slots 8..8+tp.slots-1 on A->B and B->C
sol.add_lightpath(d, ["A", "B", "C"], tp, start=[4, 12], regenerators=["B"])   # 3R at B: one start per segment
sol.add_lightpath(d, ["A", "D", "E", "F", "C"], tp, start=0, backup=True)      # 1+1 backup lightpath
sol.block(d, "spectrum")         # optional: why a demand was not served ("spectrum", "reach", "no disjoint path")
return sol
```

`tp` is a `Transponder` or its name. The number of slots of a lightpath comes
from the transponder table, never from the algorithm. A demand may be
carried by several lightpaths (their rates must add up to at least
`d.traffic`); a demand without lightpaths is blocked.

**Do not check the solution yourself**: PyNet2Plan checks it independently and
reports `INVALID` with a message such as

* `Lightpath #3 (demand 5, 200G 16QAM): path A > B > C is 1200 km but the reach of 200G 16QAM is 900 km.`
* `Slot 12 of link B->C is used by 2 lightpaths (demands 3, 7): two lightpaths cannot share a slot.`
* `Demand 4 (C->D, 500 Gb/s): working and backup paths share the fibre B-E: one cut would take both down.`
* `Lightpath #2 (...): uses 3R at B, but this algorithm is declared without regeneration (REGENERATION = False).`

## Helpers (`pynet2plan.eon.helpers`)

| function | what |
|---|---|
| `k_shortest_paths(G, s, t, k)` | the k shortest loopless paths by km |
| `path_length(G, path)`, `path_links(path)` | km of a path, its links `[(A, B), (B, C)]` |
| `fibre(u, v)`, `path_fibres(path)` | the fibre of a link (same for both directions), the fibres of a path |
| `types_reaching(table, km)` | the transponder types whose reach covers `km` |
| `best_combination(candidates, rate, order)` | the lightpaths carrying `rate` Gb/s: `candidates` = `[(tp, number_of_3R), ...]`, `order` = `"slots"` (fewest slots, then fewest 3R), `"3R"` or `"cost"`; returns `[(tp, number_of_3R), ...]` = n lightpaths of ONE type (a demand never mixes types), or None |
| `Spectrum(G)` | `.first_fit(path, n)`, `.occupy(path, start, n)`, `.free_on_path(path)`, `.copy()`, `.is_free(...)` |
| `segments_of(path, regenerators)` | cut a path at its 3R nodes |
| `combination_text(names)` | `"2 × 300G PCS 16QAM"` |

## Debugging

`print(...)` works (the output is shown at the end of the run);
`python -m pynet2plan eon-check formulations/eon/<file>.py` runs a file on the
test network; `python -m pynet2plan eon-run -t data/topologies/eon6.json -d
data/traffic_eon/eon6_traffic.csv -a <file>` runs it from the command line.
