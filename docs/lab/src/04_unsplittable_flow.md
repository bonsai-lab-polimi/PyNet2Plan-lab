---
title: The unsplittable flow formulation
subtitle: Lab handout 4 (Lab 2)
tag: Files: formulations/unsplittable_flow.py (to be completed) and labs/lab2_unsplittable.py.
footer: Handout 4, unsplittable flow
---

## 1. The problem

In handout 3 the wavelengths of a demand could be divided among several paths. In many networks
this is not allowed: all the wavelengths of a demand must follow the same path, for instance
because they belong to the same client connection. The problem of this lab is the same as in
handout 3, routing all the demands with the minimum number of wavelengths summed over all
links, with one additional requirement: every demand uses a single path.

### Link-flow formulation with binary variables

The notation is that of handout 3. The variables, however, change meaning: x<sub>d,e</sub> is
now a binary variable, equal to 1 if the path of demand d uses link e and 0 otherwise. The
number of wavelengths of demand d on link e is therefore h<sub>d</sub> x<sub>d,e</sub>.

<div class="math">
<div class="row"><span class="lhs">minimise</span><span>Σ<sub>d∈D</sub> Σ<sub>e∈E</sub> h<sub>d</sub> x<sub>d,e</sub></span></div>
<div class="row"><span class="lhs">subject to</span><span>Σ<sub>e∈δ<sup>+</sup>(n)</sub> x<sub>d,e</sub> − Σ<sub>e∈δ<sup>−</sup>(n)</sub> x<sub>d,e</sub> = 1 if n = s<sub>d</sub>, −1 if n = t<sub>d</sub>, 0 otherwise, &nbsp; for all d ∈ D, n ∈ N</span></div>
<div class="row"><span class="lhs"></span><span>Σ<sub>d∈D</sub> h<sub>d</sub> x<sub>d,e</sub> ≤ u<sub>e</sub>, &nbsp; for all e ∈ E</span></div>
<div class="row"><span class="lhs"></span><span>x<sub>d,e</sub> ∈ {0, 1}</span></div>
</div>

Compared with the splittable formulation, three things change. The flow conservation
constraints send one unit of flow from s<sub>d</sub> to t<sub>d</sub>; since the variables are
binary, this unit cannot be divided and describes exactly one path. The objective and the
capacity constraints weight each variable with the traffic h<sub>d</sub> of its demand. The
number of variables and constraints does not change: for Spain-7 with 24 demands there are
again 384 variables and 184 constraints.

## 2. Completing the exercise

The file `formulations/unsplittable_flow.py` contains the model in its first lines and all the
code except four blocks. Each block is marked by a comment `TODO n` and ends with the line
`raise NotCompletedError("TODO n: ...")`, which stops the program and reports which block is
missing. For each block, write the code and then delete the `raise` line. The file
`formulations/splittable_flow.py` (handout 3) is the model to follow.

| TODO | what to write | difference from `splittable_flow.py` |
|---|---|---|
| 1 | a variable `x[d.id, i, j]` for every demand and every link, each with a unique name | binary variables (`cat=pulp.LpBinary`) |
| 2 | the objective function | each variable is multiplied by `d.traffic` |
| 3 | flow conservation, for every demand and every node | right-hand side 1, −1 or 0 |
| 4 | the capacity of every link | each variable is multiplied by `d.traffic` |

Before using real data, the formulation is tested on the small test network of PyNet2Plan, with
the button *Check* of the graphical interface or with the command

```bash
python -m pynet2plan check formulations/unsplittable_flow.py
```

As long as a block is missing, the answer is NOT_COMPLETED, with the file, the line and the
text of the first TODO:

{{output check_todo}}

When the four blocks are correct, the answer is OPTIMAL with objective 21 (the splittable
formulation gives 20 on the same network):

{{output check_done}}

PyNet2Plan checks every solution independently of the model, so most mistakes produce a clear
message. The following table lists the most frequent ones.

| result of *Check* | probable cause |
|---|---|
| NOT_COMPLETED | a `raise NotCompletedError(...)` line has not been deleted |
| ERROR: "Two variables have the same name" | the names of the variables are not unique: write `d.id`, `i` and `j` in the name |
| INFEASIBLE | the right-hand side of the flow conservation is h<sub>d</sub> instead of 1 |
| INVALID: "Link B->C carries 6 wavelengths but its capacity is 4" | the capacity constraint does not multiply the variables by `d.traffic` |
| INVALID: "Demand 0 (A->C) is split over 2 paths" | continuous variables instead of binary ones |
| UNBOUNDED | integer variables without the lower bound `lowBound=0` |
| OPTIMAL, with a warning on the objective | the objective does not multiply the variables by `d.traffic` |

## 3. Spain-7 with C = 40

The data are those of handout 3: Spain-7 with 40 wavelengths on every link and the traffic
matrix `spain7_traffic_split_vs_unsplit.csv` (24 demands, 229 wavelengths). In the graphical
interface the example *Spain-7: splittable vs unsplittable* is opened, *Unsplittable flow
formulation* is selected and *Run* is pressed. The script of this lab runs both formulations
and compares them:

```bash
python labs/lab2_unsplittable.py
```

Its first part repeats the check on the test network; if the formulation is not complete, the
script stops there. The second part solves Spain-7 with C = 40:

{{output lab2 2}}

The unsplittable optimum is 443, that is 35 wavelengths above the lower bound 408, against 17
for the splittable formulation. In the splittable solution a demand is divided between a
fewest-hop path and a longer one, so that the scarce capacity of Sevilla→Malaga is used
exactly. Without splitting, whole demands have to be moved, and moving a whole demand costs
more than moving the few wavelengths that do not fit. The routes listed above are one of
several optimal solutions; another solver may list different routes with the same objective.

{{figure ../figures/lab2_maps_c40.svg | Figure 1. Link utilization in the two optimal solutions for C = 40.}}

{{figure ../screenshots/lab2/raw/33_unsplittable_routes.png | Figure 2. Unsplittable solution for C = 40 in the *Results* tab: the single path of demand {{fact lab2_demand}} ({{fact lab2_origin}} to {{fact lab2_destination}}, {{fact lab2_traffic}} λ) is highlighted. | crop=0,167,1150,757 width=182mm}}

## 4. Comparison for C = 30 to 60

In the graphical interface the two formulations are compared with *Compare (sweep)...*: both
are selected and the capacities `30-60` are entered (Figure 3). The results appear in the
*Sweep* tab, and *Charts in a large window* shows them enlarged (Figure 4).

{{figure ../screenshots/lab2/30_sweep_two_formulations.png | Figure 3. The sweep dialog with the two flow formulations selected. | shot width=165mm}}

{{figure ../screenshots/lab2/32_sweep_charts.png | Figure 4. Objective and computation time of the two formulations for every capacity (*Charts in a large window*); the times are the mean of 5 runs, with error bars of one standard deviation. | shot width=172mm}}

The third part of the script performs the same comparison:

{{output lab2 3}}

{{figure ../figures/lab2_objective_vs_capacity.svg | Figure 5. Optimal objective of the two formulations. The cross marks the capacity for which only the unsplittable problem is infeasible.}}

{{figure ../figures/lab2_difference.svg | Figure 6. Additional wavelengths required by the unsplittable formulation.}}

The unsplittable optimum is never smaller than the splittable one, since an unsplittable
routing is also a valid splittable routing. The two curves have different shapes: the
splittable optimum decreases by one wavelength for each additional wavelength of capacity,
while the unsplittable optimum decreases in steps. The fourth part of the script explains
these steps.

{{output lab2 4}}

Every fewest-hop routing sends 57 wavelengths over Sevilla→Malaga, so both formulations
reach the lower bound 408 only for C ≥ 57. For smaller capacities at least 57 − C
wavelengths must avoid this link. The splittable formulation moves exactly 57 − C
wavelengths, each on a path one hop longer, hence the objective 465 − C. The unsplittable
formulation must move whole demands. Moving demand 10 or demand 16 (14 λ, one hop more)
costs 14 wavelengths and is sufficient as long as 57 − 14 ≤ C, which explains the constant
value 422 for 43 ≤ C ≤ 56. For C = 43 the two formulations coincide, because the 14 wavelengths
that the splittable formulation has to move form exactly one demand.

## 5. Computation time

The two formulations have the same number of variables and constraints, but the solver does
not handle them in the same way. For the splittable formulation an integer optimum is found
almost immediately. For the unsplittable formulation the solver has to explore several
combinations of paths (branch and bound) before proving that a solution is optimal. On
Spain-7 both take a fraction of a second. The fifth part of the script uses a larger network,
GEANT2 (35 nodes, 110 links, 60 demands), close to its smallest feasible capacity.

A computation time is a measurement: the same run, repeated, takes a slightly different time,
depending on the other programs running on the computer. Each case is therefore solved 5 times
(option `--repetitions`), and the script reports the mean and the standard deviation. The
repetitions are interleaved, first all the cases once, then all of them again, and so on, so
that a period in which the computer is slower affects all the cases in the same way. A
difference between two cases is meaningful only if it is clearly larger than the standard
deviations.

{{output lab2 5}}

{{figure ../figures/lab2_time_large.svg | Figure 7. Computation times on GEANT2: mean of 5 runs, with error bars of one standard deviation. They were measured on the computer used to prepare this handout and depend on the computer and on the solver.}}

The standard deviations are small compared with the differences between the two formulations:
the unsplittable formulation is slower for every capacity, and its time changes with the
capacity, since the number of branch-and-bound nodes depends on the instance, while the time of
the splittable formulation is almost constant.

## 6. Questions

For every result, record the network, the traffic file, the capacity and the solver used.

1. Replace the right-hand side 1 of the flow conservation constraints with `d.traffic` and run
   *Check*. Explain the status that is obtained.

2. Why is the unsplittable problem infeasible for C = 34, while the splittable one is feasible?
   List the demands that enter Malaga and Murcia (handout 2, section 5) and look for groups of
   demands with exactly 34 wavelengths. Then consider the links that enter Sevilla.

3. Using part 4 of the script, explain the value 424 for C = 41 and C = 42, and why the two
   formulations give the same value for C = 41.

4. For C = 40, the unsplittable solution moves three demands away from their fewest-hop paths.
   Why is it not enough to move two of them? Hint: look at the load of Valencia→Murcia and of
   Sevilla→Madrid.

5. Can the unsplittable optimum increase when the capacity increases? Can a feasible solution of
   the binary model contain, besides the path of a demand, a cycle of links with
   x<sub>d,e</sub> = 1? Why does this not happen in an optimal solution?

6. Give two fibers to the link Sevilla→Malaga (*Links* tab, *Fibers...*) and solve both
   formulations with C = 40. How do the two optima change? Which link becomes the bottleneck?

7. Repeat part 5 on your computer. For which capacities is the unsplittable formulation slower,
   taking the standard deviations into account?
   Optionally, generate a random traffic matrix on NSFNET-14 with 90 demands of 4 to 16
   wavelengths (seed 2) and compare the two formulations for C = 76 to 92.
