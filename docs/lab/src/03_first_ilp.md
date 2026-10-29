---
title: The splittable flow formulation
subtitle: Lab handout 3
tag: Files: formulations/splittable_flow.py and labs/lab1_first_ilp.py.
footer: Handout 3, splittable flow
---

## 1. The problem

A network is given, with a capacity (number of wavelengths) on each link, together with a
traffic matrix whose demands are also expressed in wavelengths. The problem is to route all the
demands using the minimum number of wavelengths, summed over all links. For instance, a demand
of 5 wavelengths routed on a path of 3 links contributes 15 to the objective. In this first
formulation the traffic of a demand may be split over several paths, for example 10 wavelengths
on one path and 4 on another.

### Link-flow formulation

The notation and its counterpart in the code are summarised in the following table.

| symbol | meaning | code |
|---|---|---|
| G = (N, E) | directed network, e = (i, j) a link | `G`, a `networkx.DiGraph`; `for (i, j) in G.edges` |
| u<sub>e</sub> | capacity of link e (wavelengths): f<sub>e</sub> fibers of W<sub>e</sub> wavelengths, u<sub>e</sub> = f<sub>e</sub> W<sub>e</sub> | `G.edges[i, j]["fibers"] * G.edges[i, j]["capacity"]` |
| D | set of demands; s<sub>d</sub>, t<sub>d</sub>, h<sub>d</sub> origin, destination and wavelengths of d | `demands`; `d.origin`, `d.destination`, `d.traffic` |
| δ<sup>+</sup>(n), δ<sup>−</sup>(n) | links leaving and entering node n | `G.out_edges(n)`, `G.in_edges(n)` |
| x<sub>d,e</sub> | wavelengths of demand d carried by link e (non-negative integer variables) | `x[d.id, i, j]` |

<div class="math">
<div class="row"><span class="lhs">minimise</span><span>Σ<sub>d∈D</sub> Σ<sub>e∈E</sub> x<sub>d,e</sub></span></div>
<div class="row"><span class="lhs">subject to</span><span>Σ<sub>e∈δ<sup>+</sup>(n)</sub> x<sub>d,e</sub> − Σ<sub>e∈δ<sup>−</sup>(n)</sub> x<sub>d,e</sub> = h<sub>d</sub> if n = s<sub>d</sub>, −h<sub>d</sub> if n = t<sub>d</sub>, 0 otherwise, &nbsp; for all d ∈ D, n ∈ N</span></div>
<div class="row"><span class="lhs"></span><span>Σ<sub>d∈D</sub> x<sub>d,e</sub> ≤ u<sub>e</sub>, &nbsp; for all e ∈ E</span></div>
<div class="row"><span class="lhs"></span><span>x<sub>d,e</sub> ≥ 0 and integer</span></div>
</div>

The first group of constraints expresses flow conservation: h<sub>d</sub> wavelengths leave the
origin of demand d, the same amount reaches its destination, and at every other node the flow
entering is equal to the flow leaving. The second group limits the load of each link to its
capacity. The variables are integer, since they count wavelengths. For Spain-7 (16 links and
7 nodes) with 24 demands the model has 24 × 16 = 384 variables and 24 × 7 + 16 = 184
constraints.

### The code

The file `formulations/splittable_flow.py` is short, and each block corresponds to one part of
the model. The variables are created for every demand and every link:

{{excerpt formulations/splittable_flow.py | x = {} | x[d.id, i, j] = prob.add_variable}}

The objective function and the capacity constraints are

{{excerpt formulations/splittable_flow.py | prob += pulp.lpSum(x[d.id, i, j] for d in demands for (i, j) in G.edges) | prob += pulp.lpSum(x[d.id, i, j] for d in demands for (i, j) in G.edges)}}

{{excerpt formulations/splittable_flow.py | for (i, j) in G.edges: | f"capacity_{i}_{j}" | # Capacity of every link}}

The flow conservation constraints are reproduced at the end of handout 2. The function
`solve_ilp` then calls the solver (CBC or HiGHS), and the flow of each demand is decomposed
into paths by `flow_to_routes`. The resulting `Solution` is checked, saved and displayed by
PyNet2Plan.

## 2. The data

The network is Spain-7 (handout 2), with 8 pairs of links, one fiber per link and the same
capacity C on every link (40 wavelengths in the topology file). The traffic matrix is
`data/traffic/spain7_traffic_split_vs_unsplit.csv`: 24 demands of 4 to 16 wavelengths, 229
wavelengths in total. The demands are few and large, and several of them compete for the same
links.

Two values help to interpret the results. The first is a lower bound on the objective. If the
capacities were unlimited, each demand would follow a path with the fewest hops, and the
objective would be the sum of h<sub>d</sub> times the number of hops of that path, which is 408.
No routing can use fewer than 408 wavelengths. The second is the cut bound of handout 2: 68
wavelengths must reach Malaga and Murcia through only two links, so the capacity must be at
least 34.

## 3. Running the formulation

In the graphical interface:

1. open the network and its traffic with *File > Open example > Spain-7: splittable vs
   unsplittable* (all links have C = 40);
2. select *Splittable flow formulation* in the run bar and press *Run*;
3. in the summary press *Open in the Results tab* and examine the *Report*, *Routes*, *Links*
   and *Occupancy* tabs (sections 11 to 14 of handout 1).

{{figure ../screenshots/raw/13_results_routes.png | Figure 1. Result for C = 40. The paths highlighted in light blue are the two routes of demand {{fact split_demand}} ({{fact split_origin}} to {{fact split_destination}}). | crop=0,167,1000,757 width=182mm}}

The first part of the script `labs/lab1_first_ilp.py` performs the same run from the command
line and prints some additional information:

```bash
python labs/lab1_first_ilp.py
```

{{output first_ilp 1}}

### Discussion

The status is OPTIMAL and the objective is 425, that is 17 wavelengths more than the lower
bound. Each unit above 408 corresponds to one wavelength carried on a link that is not part of
a fewest-hop path, i.e. to a detour; the extra wavelengths listed in the output add up to 17.
Detours are necessary because some links are full: the demands that would use them have to be
routed around them. The full links can be identified on the map and in the *Links* tab, where a
click on a link lists the demands that use it. Finally, some demands are split over two paths.
The formulation allows it, and splitting allows the solver to fill the scarce links exactly.

In general several routings use exactly 425 wavelengths, and the solver returns one of them. A
different solver, or another version of CBC, may return a different optimal solution, with
other split demands and other full links. The optimal value, 425, does not change.

{{figure ../figures/ilp_map_c40.svg | Figure 2. Link utilization in the optimal solution for C = 40 (same colours as in the graphical interface).}}

## 4. Experiment 1: the effect of the capacity

The formulation is now solved for every capacity from C = 30 to C = 60, either with *Compare
(sweep)...* in the graphical interface (capacities `30-60`, see sections 16 to 18 of handout 1)
or with the second part of the script:

{{output first_ilp 2}}

{{figure ../figures/ilp_objective_vs_capacity.svg | Figure 3. Objective as a function of the capacity. The shaded region contains the infeasible capacities.}}

Three regions can be distinguished. For C ≤ 33 the problem is infeasible, as predicted by the
cut bound of handout 2, which is tight in this case. Between C = 34 and C = 57 the objective
decreases by exactly one wavelength for each additional wavelength of capacity: one more
wavelength on the bottleneck links allows one more wavelength of some demand to avoid a detour
of one hop. For C ≥ 57 the objective equals the lower bound 408, every demand follows a
fewest-hop path and additional capacity is not used.

{{figure ../figures/ilp_split_and_full_links.svg | Figure 4. Number of split demands and of full links in the optimal solution returned by the solver. These numbers depend on which optimal solution is returned.}}

## 5. Experiment 2: fibre cuts

A fibre cut interrupts both directions of a link. In the graphical interface the two links are
selected in the *Links* tab (Ctrl+click, or Cmd+click on macOS) and switched off with *Fail /
repair selected*; the capacity is set with *Same capacity for all...*. The third part of the
script tries the 8 possible cuts with C = 60:

{{output first_ilp 3}}

{{figure ../figures/ilp_fiber_cuts_c60.svg | Figure 5. The 8 single fibre cuts with C = 60 on every link.}}

{{figure ../screenshots/raw/22_failure_c60.png | Figure 6. C = 60 with the link Madrid-Valencia cut (dashed): the traffic is carried by the remaining links, with longer detours. | crop=0,167,1000,757 width=182mm}}

With C = 60 the network survives four of the eight cuts, at the cost of up to 64 additional
wavelengths, while the other four cuts make the problem infeasible. A capacity that is
sufficient in normal operation does not make a network survivable.

## 6. Charts for the lab report

The figures of this handout and those saved by the script in `results/lab1_first_ilp/` (PNG
for the screen, PDF for a report, with their data in JSON files) follow a few rules, which
also apply to the charts of the lab reports.

- Every axis has a title with the quantity and its unit, for example *capacity of every link,
  C (wavelengths)* or *computation time (ms)*.
- Tick labels, axis titles and legends remain readable when the figure is reduced to the
  width of the page: in the final document they should not be smaller than about 8 points.
- The series differ in colour, marker and line style and are named in a legend or directly
  on the chart, so that the chart can also be read in a black and white print and by readers
  with a colour vision deficiency. Hollow markers keep a series visible where it overlaps
  another one.
- Missing points are shown explicitly, for example with a shaded band or with crosses for
  the capacities without a solution.
- Integer quantities, such as capacities and wavelengths, have integer ticks.
- A quantity that changes from one measurement to the next, such as a computation time, is
  measured several times. The chart shows the mean with error bars, and the caption states
  what the error bars represent (in this course, one standard deviation).
- Charts are inserted in a report as vector files (PDF), which remain sharp at any size. The
  buttons *Save as...* and *Open as PDF* of the graphical interface produce such files.

In Matplotlib, `plotting.use_report_style()` and `plotting.series_style(i)` of PyNet2Plan apply
these settings; their use can be seen in the functions at the end of the lab scripts.

## 7. Questions

The questions can be answered with the graphical interface or by modifying the script. For
every result, record the network, the traffic file, the capacity and the parameters used.

1. For C = 40, list the full links and the demands that do not follow a fewest-hop path, and
   check that the additional wavelengths add up to 425 − 408. Is your solution the same as the
   one obtained by other students?

2. Explain with the cut bound why the problem is infeasible for C = 33. Which links are full for
   C = 34?

3. What is the smallest capacity, equal on all links, for which the network survives every
   single fibre cut? The option `--failure-capacity` of the script can be used, with values such
   as 64, 66, 68.

4. Starting from C = 34, capacity can be added to individual links instead of to all of them.
   Which links would you upgrade, and by how much, to reach the lower bound 408 with the smallest
   total amount of additional capacity?

5. Look at the computation times of the sweep, given as the mean and the standard deviation
   of 5 runs. Are the differences between the capacities larger than the standard deviations?
   Repeat the run on a larger network (*File > Open example > NSFNET-14*) and compare the
   number of variables and the computation time.

## 8. Next lab

In the next lab splitting is no longer allowed: in `formulations/unsplittable_flow.py`, which
is downloaded with `git pull` before the lab (handout 0), each demand must use a single path. The formulation has to be completed and then compared with the
splittable one on the same data. The traffic matrix of this handout was chosen so that the two
formulations give different results for most capacities.
