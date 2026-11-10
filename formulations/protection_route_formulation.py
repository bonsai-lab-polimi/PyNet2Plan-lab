"""
route formulation (1+1 protection), ILP                      [EXERCISE - to complete]
=========================================================================================

The route formulation WITH wavelength continuity of Lab 2 (WP), extended to 1+1
protection. The greedy 1+1 heuristic (``greedy_1plus1_protection.py``) serves the
demands one at a time: an early demand takes the best pair of paths and the lowest
wavelengths even if a later demand would have needed them more. This ILP chooses the
pairs AND the wavelengths of ALL the demands together: its result is the global
optimum over the candidate pairs.

Every candidate is a PAIR of paths n = (W_{c,n}, B_{c,n}), a working path and a backup
path that share no fibre: the pairs are built as in the greedy heuristic, so the
link-disjointness needs no constraint. A demand is served on one pair (its v_c
wavelengths on the working AND on the backup path) or it is blocked. Notation as in the
route formulation of the course (slide 72).

Notation (slides)                              in the code
-----------------                              -----------
c            a demand (in the course: a        c in demands (c.id, c.traffic)
             connection request)
v_c          wavelengths requested by c        v_c[c.id] = c.traffic
n            the n-th candidate pair of c:     Q[c.id][n] = (working, backup): the pair of the
             (W_{c,n}, B_{c,n}), no common     greedy heuristic, then the next shortest working
             fibre                             paths, each with its shortest fibre-disjoint
                                               backup (shortest = the fewest hops, equal hops:
                                               the shorter in km); with an optical reach, only
                                               pairs whose two paths are within the reach
l_{c,n}      links of W_{c,n} + links of B_{c,n}   l[c.id, n]
(l,k)        a link from node l to node k      (l, k) in G.edges
R(l,k)       the paths that use link (l,k)     RW[l, k], RB[l, k]: the pairs (c.id, n) whose
                                               working / backup path uses (l, k)
F_{l,k}      fibers of link (l,k) (given)      F[l, k] = G.edges[l, k]["fibers"]
W            wavelengths per fibre             G.edges[l, k]["capacity"] (may differ by link)
λ            a wavelength, λ0 ... λ_{W-1}      lam in Lambda(path) = range(min capacity on
                                               the path): only the wavelengths that exist
                                               on EVERY link of the path. This is where W
                                               limits the model: r exists only for these λ
                                               (no constraint needed)

Decision variables
------------------
x_{c,n}       ∈ {0, 1}   1 if demand c is served on its n-th pair
y_c           ∈ {0, 1}   1 if demand c is blocked
r^W_{c,n,λ}   ∈ {0, 1}   1 if the working path W_{c,n} carries c on wavelength λ (on ALL its links)
r^B_{c,n,λ}   ∈ {0, 1}   1 if the backup path B_{c,n} carries c on wavelength λ (on ALL its links)

Model
-----
min   M · Σ_c y_c  +  Σ_c Σ_n v_c · l_{c,n} · x_{c,n}       (first serve, then fewest wavelengths)

Demand     Σ_n x_{c,n} + y_c = 1                             ∀ c          (one pair, or blocked)
           Σ_λ r^W_{c,n,λ} = v_c · x_{c,n}                   ∀ c, n       (v_c wavelengths on W)
           Σ_λ r^B_{c,n,λ} = v_c · x_{c,n}                   ∀ c, n       (v_c wavelengths on B)
Capacity   Σ_{W_{c,n} ∈ R(l,k)} r^W_{c,n,λ}
             + Σ_{B_{c,n} ∈ R(l,k)} r^B_{c,n,λ} <= F_{l,k}     ∀ (l,k), λ ∈ {λ0..λ_{W-1}}
Integrity  x, y, r^W, r^B binary

The working and the backup path share no fibre, so they may use the same wavelength.
M is larger than the wavelengths of any plan, so the model first serves as many
demands as possible, then uses the fewest wavelength-links. The plan of the greedy
heuristic is one feasible solution (its pair is the first candidate), so the optimum
never serves fewer demands than the greedy.

What to do
----------
The data (candidate pairs Q, v_c, l, RW, RB, F, M), the decision variables, the
objective function and the wavelength capacity constraints are given. Write the three
groups of DEMAND constraints of the model above, one per TODO block (write the code,
then DELETE the ``raise NotCompletedError(...)`` line):

  TODO 1  one pair, or the demand is blocked
  TODO 2  v_c wavelengths on the working path of the chosen pair
  TODO 3  v_c wavelengths on the backup path of the chosen pair

PyNet2Plan checks the result: every served demand needs a backup path that shares no
fibre with its working path, every route lists its wavelengths, the same wavelength
cannot be used twice on a link (one fibre), and it must exist on every link of the path.

Questions:
1. Open the example "Italy-10: 1+1 protection example" (9 λ, 30 demands). How many
   demands do the greedy 1+1 heuristic and your route formulation protect?
   Compare (sweep) over the capacities 5-13: from which capacity is everything protected?
2. The model has no link-disjoint constraint (slide 72 of the course has one): why is
   the backup path still fibre-disjoint from the working path?
"""

from itertools import islice

import networkx as nx
import pulp

from pynet2plan import helpers
from pynet2plan.errors import NotCompletedError
from pynet2plan.helpers import SolverNotAvailableError, solve_ilp, value
from pynet2plan.network import fibre, path_fibres, within_reach  # noqa: F401
from pynet2plan.protection import WEIGHTS, path_weight
from pynet2plan.solution import Solution

NAME = "route formulation (1+1 protection)"
SPLITTABLE = False
ALLOWS_BLOCKING = True
PROTECTION = True            # every served demand must have a fibre-disjoint backup (checked!)
WAVELENGTH_CONTINUITY = True     # every route lists its wavelengths (checked!)
ORDER = 8

PARAMETER_HELP = {
    "k": "Number of candidate pairs per demand (working path among the k shortest, each with "
         "its shortest fibre-disjoint backup).",
    "weight": "'hops' (fewest links, equal hops: shorter in km) or 'length' (km), for the pairs.",
    "time_limit": "Maximum solver time in seconds.",
}
PARAMETER_CHOICES = {"weight": WEIGHTS}


def candidate_pairs(G, s, t, k, weight="hops"):
    """Up to k pairs (working, backup) that share no fibre. The first working path is the one
    of the greedy heuristic (the shortest), the others the next shortest paths; each gets the
    shortest path that avoids its fibres as backup (none: the pair is skipped). Shortest =
    the fewest hops (equal hops: the shorter in km), or in km with weight='length'.
    With an optical reach, a pair with a path longer than the reach is skipped too."""
    w8 = path_weight(weight)
    try:
        workings = [nx.shortest_path(G, s, t, weight=w8)]
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []
    for w in islice(nx.shortest_simple_paths(G, s, t, weight=w8), k):
        if len(workings) < k and w not in workings:
            workings.append(w)
    pairs = []
    for working in workings:
        used = path_fibres(working)
        H = G.copy()
        H.remove_edges_from([(u, v) for (u, v) in G.edges if fibre(u, v) in used])
        try:
            backup = nx.shortest_path(H, s, t, weight=w8)
        except nx.NetworkXNoPath:
            continue
        if within_reach(G, working) and within_reach(G, backup):
            pairs.append((working, backup))
    return pairs


def _solve(prob, time_limit):
    """solve_ilp with HiGHS, unless a solver was chosen explicitly: the wavelengths are
    interchangeable, and HiGHS proves this model optimal in seconds where CBC may need minutes."""
    chosen = helpers.SETTINGS.get("solver", "auto")
    if chosen in ("", "auto") and {"HiGHS", "HiGHS_CMD"} & set(helpers.available_solvers()):
        helpers.SETTINGS["solver"] = "highs"
        try:
            return solve_ilp(prob, time_limit=time_limit)
        except SolverNotAvailableError:
            pass                                        # HiGHS does not run here: use the default
        finally:
            helpers.SETTINGS["solver"] = chosen
    return solve_ilp(prob, time_limit=time_limit)


def solve(G, demands, k=3, weight="hops", time_limit=120):
    # ---- the data of the model (given) ------------------------------------------
    def links_of(path):
        return list(zip(path[:-1], path[1:]))

    def Lambda(path):
        """λ0 ... λ_{W-1}: the wavelengths that exist on EVERY link of the path."""
        return range(min(G.edges[l, k]["capacity"] for (l, k) in links_of(path)))

    Q = {c.id: candidate_pairs(G, c.origin, c.destination, k, weight) for c in demands}
    v_c = {c.id: c.traffic for c in demands}       # v_c[c.id] = wavelengths requested by c
    l = {(c.id, n): len(W) - 1 + len(B) - 1 for c in demands for n, (W, B) in enumerate(Q[c.id])}
    RW, RB = {}, {}                                # RW[l, k] / RB[l, k] = pairs (c.id, n) whose
    for c in demands:                              # working / backup path uses link (l, k)
        for n, (W, B) in enumerate(Q[c.id]):
            for (i, j) in links_of(W):
                RW.setdefault((i, j), []).append((c.id, n))
            for (i, j) in links_of(B):
                RB.setdefault((i, j), []).append((c.id, n))
    F = {(i, j): G.edges[i, j].get("fibers", 1) for (i, j) in G.edges}
    # blocking one demand costs more than its most expensive pair: serving always pays
    M = 1 + sum(max((v_c[c.id] * l[c.id, n] for n in range(len(Q[c.id]))), default=0) for c in demands)

    prob = pulp.LpProblem("route_formulation_1plus1", pulp.LpMinimize)

    # ---- decision variables (given) ------------------------------------------------
    x, y, rW, rB = {}, {}, {}, {}
    for c in demands:
        y[c.id] = prob.add_variable(f"y_{c.id}", cat=pulp.LpBinary)
        for n, (W, B) in enumerate(Q[c.id]):
            x[c.id, n] = prob.add_variable(f"x_{c.id}_{n}", cat=pulp.LpBinary)
            for lam in Lambda(W):
                rW[c.id, n, lam] = prob.add_variable(f"rW_{c.id}_{n}_{lam}", cat=pulp.LpBinary)
            for lam in Lambda(B):
                rB[c.id, n, lam] = prob.add_variable(f"rB_{c.id}_{n}_{lam}", cat=pulp.LpBinary)

    # ---- objective function (given) --------------------------------------------------
    prob += (M * pulp.lpSum(y.values())
             + pulp.lpSum(v_c[c.id] * l[c.id, n] * x[c.id, n] for c in demands for n in range(len(Q[c.id]))))

    # ---- TODO 1: demand constraints  Σ_n x_{c,n} + y_c = 1   ∀ c ------------------------
    # For every demand c: it is served on exactly one of its pairs n = 0 .. len(Q[c.id]) - 1,
    # or it is blocked (y[c.id] = 1).
    raise NotCompletedError("TODO 1: write the demand constraints (one pair, or blocked).")

    # ---- TODO 2: demand constraints of the working paths  Σ_λ r^W_{c,n,λ} = v_c x_{c,n} ---
    # For every demand c and every pair n = (W, B) of Q[c.id]: the working path W of the
    # chosen pair (x[c.id, n] = 1) gets v_c[c.id] wavelengths, the working path of a pair
    # that is not chosen gets none. The wavelengths of W are Lambda(W).
    raise NotCompletedError("TODO 2: write the demand constraints of the working paths.")

    # ---- TODO 3: demand constraints of the backup paths  Σ_λ r^B_{c,n,λ} = v_c x_{c,n} ----
    # The same for the backup path B, with the variables rB (1+1: the backup path
    # reserves its own v_c wavelengths).
    raise NotCompletedError("TODO 3: write the demand constraints of the backup paths.")

    # ---- wavelength capacity (given): Σ_{W ∈ R(l,k)} r^W + Σ_{B ∈ R(l,k)} r^B <= F_{l,k} ---
    # on every link and wavelength λ0 ... λ_{W-1}: working AND backup paths, once per fibre
    for (i, j) in G.edges:
        for lam in range(G.edges[i, j]["capacity"]):            # λ0 ... λ_{W-1}
            terms = ([rW[cid, n, lam] for (cid, n) in RW.get((i, j), []) if (cid, n, lam) in rW]
                     + [rB[cid, n, lam] for (cid, n) in RB.get((i, j), []) if (cid, n, lam) in rB])
            if len(terms) > F[i, j]:
                prob += pulp.lpSum(terms) <= F[i, j], f"capacity_{i}_{j}_{lam}"

    # ---- solve (given) -----------------------------------------------------------
    _solve(prob, time_limit)

    # ---- build the solution (given) ------------------------------------------------
    # the chosen pair of every served demand, with the wavelengths that have r = 1
    sol = Solution(objective=value(prob.objective))
    for c in demands:
        for n, (W, B) in enumerate(Q[c.id]):
            if value(x[c.id, n]) > 0.5:
                wl = [lam for lam in Lambda(W) if value(rW[c.id, n, lam]) > 0.5]
                bl = [lam for lam in Lambda(B) if value(rB[c.id, n, lam]) > 0.5]
                sol.add_route(c, W, len(wl), wavelengths=wl, backup=False)
                sol.add_route(c, B, len(bl), wavelengths=bl, backup=True)
                break
    return sol
