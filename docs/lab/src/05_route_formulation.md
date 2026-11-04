---
title: The route formulation
subtitle: Lab handout 5 (Lab 2)
tag: Files: formulations/route_formulation_vwp.py (to be completed) and labs/lab2_route_formulation.py.
footer: Handout 5, route formulation
---

## 1. From links to paths

The flow formulations of handouts 3 and 4 decide how many wavelengths each demand sends on each
link, and the paths of a demand appear only in the solution. The route formulation, also called
path formulation, works the other way round. For every demand a small set of candidate paths is
computed in advance, and the model only decides how many wavelengths of the demand follow each
candidate path. In this lab the candidate paths of a demand are its k shortest paths by number of
hops, computed with NetworkX as in handout 2, section 4.

The problem is the one of handout 3: all the demands are routed with the minimum number of
wavelengths summed over all links, and a demand may be split over several paths. The model
counts the wavelengths used on each link but not which ones, so it assumes that every node can
convert a wavelength into another one (no wavelength continuity, in short VWP).

| symbol | meaning | code |
|---|---|---|
| P<sub>d</sub> | candidate paths of demand d: its k shortest paths by number of hops | `paths[d.id]` |
| l<sub>p</sub> | number of links of path p | `len(path) - 1` |
| r<sub>d,p</sub> | wavelengths of demand d on its candidate path p | `r[d.id, p]` |
| u<sub>e</sub> | capacity of link e: fibres × wavelengths per fibre | `G.edges[i, j]["fibers"] * G.edges[i, j]["capacity"]` |

<div class="math">
<div class="row"><span class="lhs">minimise</span><span>Σ<sub>d∈D</sub> Σ<sub>p∈P<sub>d</sub></sub> l<sub>p</sub> r<sub>d,p</sub></span></div>
<div class="row"><span class="lhs">subject to</span><span>Σ<sub>p∈P<sub>d</sub></sub> r<sub>d,p</sub> = h<sub>d</sub>, &nbsp; for all d ∈ D</span></div>
<div class="row"><span class="lhs"></span><span>Σ<sub>d∈D</sub> Σ<sub>p∈P<sub>d</sub>: e∈p</sub> r<sub>d,p</sub> ≤ u<sub>e</sub>, &nbsp; for all e ∈ E</span></div>
<div class="row"><span class="lhs"></span><span>r<sub>d,p</sub> ≥ 0 and integer</span></div>
</div>

There are no flow conservation constraints: every candidate path already connects the origin of
its demand to the destination, so it is enough to require that the wavelengths on the
candidate paths add up to the traffic of the demand. The model is therefore much smaller. For
Spain-7 with the 24 demands of handout 3 it has 24 k variables and 24 + 16 = 40 constraints,
against 384 variables and 184 constraints of the flow formulation. The price is that only the
candidate paths can be used: when the good paths are not among them, the optimum is worse than
that of the flow formulation, or the problem has no solution.

## 2. Completing the exercise

The file `formulations/route_formulation_vwp.py` contains the model in its first lines and five
blocks to be completed, marked `TODO 1` to `TODO 5`. As in handout 4, write the code of each
block and then delete its `raise NotCompletedError(...)` line. The dictionary `paths_through`,
which lists for every link the pairs (demand, candidate path) that use it, is given.

| TODO | what to write | hint |
|---|---|---|
| 1 | the k candidate paths of every demand, `paths[d.id]` | `nx.shortest_simple_paths` and `islice`, as in handout 2 |
| 2 | a variable `r[d.id, p]` for every demand and candidate path | integer, `lowBound=0`, a unique name |
| 3 | the objective function | each variable multiplied by the number of links of its path |
| 4 | the demand constraints | they replace the flow conservation constraints |
| 5 | the capacity of every link | sum over the pairs in `paths_through[i, j]` |

The formulation is tested with *Check* or with

```bash
python -m pynet2plan check formulations/route_formulation_vwp.py
```

As long as a block is missing, the answer is NOT_COMPLETED:

{{output check_todo_route}}

When the five blocks are correct, the answer is OPTIMAL with objective 20, the value of the
splittable flow formulation on the same network:

{{output check_done_route}}

| result of *Check* | probable cause |
|---|---|
| NOT_COMPLETED | a `raise NotCompletedError(...)` line has not been deleted |
| ERROR: "Two variables have the same name" | the name of the variables does not contain both `d.id` and `p` |
| UNBOUNDED | integer variables without the lower bound `lowBound=0` |
| INVALID: "Demand 0 (A->C) carries 0 of the 3 requested wavelengths" | demand constraint written with `<=` instead of `==` |
| INVALID: "Link B->C carries 6 wavelengths but its capacity is 4" | capacity constraint missing, or not summed over `paths_through[i, j]` |
| OPTIMAL, with a warning on the objective | the objective does not multiply the variables by `len(path) - 1` |
| the script does not end on a large network | `islice` is missing, so every path of every demand is enumerated |

## 3. Spain-7 with C = 40

The script of this lab compares the route formulation with the splittable flow formulation:

```bash
python labs/lab2_route_formulation.py
```

Its first part repeats the check; its second part solves Spain-7 with C = 40 on every link and
the traffic matrix of handouts 3 and 4:

{{output lab2r 2}}

With k = 1 every demand has a single candidate path, one of its fewest-hop paths. This is the
fewest-hop routing of the lower bound 408, which sends 57 wavelengths over Sevilla→Malaga
(handout 4, section 4), so the problem is infeasible for every C below 57. With k = 2 the
optimum is already 425, the value of the flow formulation, with 48 variables and 40 constraints
instead of 384 and 184. The routes may differ from those of the flow formulation, since several
routings use exactly 425 wavelengths.

## 4. How many candidate paths?

On Spain-7 two candidate paths per demand are enough. The third part of the script uses a network
with more alternative paths, COST239 (11 nodes, 52 links, 25 demands), and solves it for C = 6
to 15:

{{output lab2r 3}}

{{figure ../figures/lab2r_objective_vs_k.svg | Figure 1. COST239: optimal objective of the flow formulation and of the route formulation for k = 1 to 4. The crosses at the bottom mark the capacities without a solution.}}

The fewer the wavelengths available, the more candidate paths are needed. For C ≥ 11 two paths
per demand give the optimum of the flow formulation. For C = 8 the route formulation needs 225
wavelengths with k = 2, 213 with k = 3 and 209, the optimum of the flow formulation, with k = 4.
For C = 7, the smallest capacity for which the flow formulation is feasible, it has no solution
with k ≤ 3, and with k = 4 it needs 216 wavelengths instead of 213. With k = 1 it is infeasible
for every capacity of the figure: the fewest-hop routing needs C = 22.

## 5. Model size and computation time

The fourth part of the script compares the two models on GEANT2 (35 nodes, 110 links, 60
demands) close to its smallest feasible capacity. As in handout 4, every case is solved 5 times
and the times are given as mean ± standard deviation.

{{output lab2r 4}}

{{figure ../figures/lab2r_time_large.svg | Figure 2. Computation times on GEANT2: mean of 5 runs, with error bars of one standard deviation; only the cases with a solution are shown. The values depend on the computer and on the solver.}}

The flow formulation has 60 × 110 = 6600 variables, the route formulation with k = 8 has 468, and
it is solved about six times faster; the difference is much larger than the standard
deviations. Near the smallest feasible capacity, however, the route formulation needs many
candidate paths: for C = 18 it is infeasible with k = 5 and reaches the optimum 898 of the flow
formulation only with k = 8. In practice the route formulation is preferred on large networks,
with a number of candidate paths chosen by checking, as done here, that a larger k does not
improve the result.

## 6. Questions

For every result, record the network, the traffic file, the capacity, the value of k and the
solver used.

1. The route formulation has no flow conservation constraints. What guarantees that the
   wavelengths of a demand travel from its origin to its destination?

2. Find the smallest capacity for which the route formulation with k = 1 is feasible on Spain-7
   with the traffic of this lab, using *Compare (sweep)...* with `k=1` and capacities `50-60`.
   Explain the value with handout 4, section 4.

3. For the same data, can the route formulation give a smaller objective than the flow
   formulation? Can it give a larger one? Answer by comparing the sets of feasible solutions of
   the two models.

4. Write the number of variables and of constraints of the two formulations as functions of
   |N|, |E|, |D| and k, and compute them for GEANT2 with k = 8. Why does the script report 468
   variables and not 60 × 8 = 480?

5. In TODO 1, compute the candidate paths by length in kilometres
   (`nx.shortest_simple_paths(G, d.origin, d.destination, weight="length")`) and repeat part 3
   for C = 8 and C = 10. Does the optimum change? Why can it change, given that the objective
   counts hops?

6. How would you write a route formulation in which demands cannot be split? Which variables and
   constraints change? Optionally, write it in a new file of `formulations/`, starting from
   `formulations/_template.py`, and compare it with the unsplittable flow formulation of
   handout 4.
