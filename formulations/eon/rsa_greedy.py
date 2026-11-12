"""
RSA - greedy Routing and Spectrum Assignment                 [GIVEN - complete, read it first]
==============================================================================================

The baseline of the EON lab: no protection, no 3R. The demands are served
one at a time, in order, and an earlier decision is never revisited (that is
what makes it greedy, and why the order of the demands matters).

A demand asks for R Gb/s from a source to a destination. It may be carried
by SEVERAL lightpaths of ONE transponder type on the same path (e.g. 800 Gb/s =
2 x 400G PCS 16QAM, never 400G + 100G + ...); each lightpath has its own two
transponders and its own slots.

For each demand:

1. take the k shortest paths (by km);
2. ROUTING + transponders: on each path keep the transponder types whose
   reach covers the whole path, and choose the type (n lightpaths of it)
   with the fewest slots that carries at least R Gb/s (``best_combination``);
3. SPECTRUM: first-fit every lightpath of the combination on that path
   (continuity: the same slots on every link; contiguity: adjacent slots;
   non-overlap: only free slots). The first path where they ALL fit is used;
4. if no path works the demand is blocked: "reach" if no transponder type
   reaches the destination on any path, "spectrum" otherwise.

Example on the slide's A -> B -> C (700 + 500 = 1200 km):
  500 Gb/s -> 500G PCS 16QAM (reach 1300 km): 1 lightpath, 8 slots
  600 Gb/s -> 600G 16QAM reaches only 700 km, 500G not enough alone: 2 x 300G PCS 16QAM, 16 slots
             (a demand uses ONE transponder type: never 500G + 100G)

Inputs: ``G`` (links with "length" in km), ``demands`` (d.traffic in Gb/s);
``transponder_table(G)`` and ``Spectrum(G)`` come from the EON settings of
the run (number of slots, transponder table).
"""

from pynet2plan.eon.helpers import (Spectrum, best_combination, k_shortest_paths, path_length,
                                   transponder_table, types_reaching)
from pynet2plan.eon.solution import EonSolution

NAME = "greedy heuristic (no protection)"
PROTECTION = False           # no backup paths
REGENERATION = False         # every lightpath must reach its destination on its own

PARAMETER_HELP = {
    "k": "Number of candidate paths tried for each demand (k shortest by km).",
    "order": "'as_given' (arrival order) or 'largest_first' (highest data rate first).",
    "choose": "How the lightpaths of a demand are chosen: 'slots' (fewest slots) or "
              "'cost' (cheapest hardware, see the 'cost' column of the transponder table).",
}
PARAMETER_CHOICES = {"order": ["as_given", "largest_first"], "choose": ["slots", "cost"]}


def solve(G, demands, k=3, order="as_given", choose="slots"):
    if order == "largest_first":
        demands = sorted(demands, key=lambda d: -d.traffic)
    table = transponder_table(G)          # the transponder types (rate, slots, reach, ...)
    spectrum = Spectrum(G)                # all slots free on every link
    sol = EonSolution()

    for d in demands:
        served = False
        reach_ok = False                  # did some transponder type reach on some path?
        for path in k_shortest_paths(G, d.origin, d.destination, k):
            km = path_length(G, path)

            # ---- ROUTING: the transponder types that reach the destination -------
            # without 3R a type needs reach >= the whole path; 0 = no regenerator
            candidates = [(tp, 0) for tp in types_reaching(table, km)]
            combo = best_combination(candidates, d.traffic, choose)
            if combo is None:
                continue                  # no type reaches that far: try the next path
            reach_ok = True

            # ---- SPECTRUM: first-fit every lightpath, all or nothing -------------
            # Work on a copy: if one lightpath of the combination does not fit, the
            # demand must not keep the slots taken by the others.
            trial = spectrum.copy()
            starts = []
            for tp, _ in combo:
                start = trial.first_fit(path, tp.slots)     # continuity + contiguity
                if start is None:
                    break                 # not enough free slots on this path
                trial.occupy(path, start, tp.slots)
                starts.append(start)
            if len(starts) < len(combo):
                continue                  # try the next path

            spectrum = trial              # keep the slots
            for (tp, _), start in zip(combo, starts):
                sol.add_lightpath(d, path, tp, start)
            served = True
            break

        if not served:
            sol.block(d, "spectrum" if reach_ok else "reach")
    return sol
