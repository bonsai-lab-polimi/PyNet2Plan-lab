"""
RSA + 3R regeneration                                          [GIVEN - complete, read it first]
================================================================================================

Without 3R a lightpath must reach the end of its path, so long paths can
only use the slow transponder types, which need more slots per Gb/s. A 3R
regenerator at an intermediate node receives the signal, cleans it
electrically (re-amplify, re-shape, re-time) and transmits it again:

1. the reach RESTARTS at the 3R: it applies to each SEGMENT (between two
   consecutive 3R, or between an end and a 3R), not to the whole path;
2. spectrum continuity BREAKS at the 3R: each segment gets its own slots.

So 3R trades fewer slots for more hardware (a 3R = 2 transponders back to
back). What 3R cannot do: a single LINK longer than the reach (there is no
node in the middle of a link to put a 3R).

The algorithm is RSA (rsa_greedy.py) with one change: a transponder type may
also be used on a path if 3R make it reach. Among the combinations of
lightpaths it takes the fewest slots, then the fewest 3R (parameter
``choose``). A lightpath keeps the same transponder type on every segment.

Slide example (A -700- B -500- C, 200 Gb/s): without 3R RSA needs a
300G PCS 16QAM lightpath (8 slots); with a 3R at B, 200G 16QAM (4 slots per
link), possibly on DIFFERENT slots on A-B and B-C.

Questions: compare with rsa_greedy (total slots used, 3R, hardware cost).
With choose="3R", why does it behave exactly like rsa_greedy on EON-6? On NSFNET-14
(File > Open example) halve the reaches (menu Transponders > Scale every reach... 0.5):
how many demands blocked by RSA for "reach" does RSA + 3R bring back? And
with 0.4, why are some demands blocked even with 3R (and what does a larger k change)?
"""

from pynet2plan.eon.helpers import (Spectrum, best_combination, k_shortest_paths, transponder_table)
from pynet2plan.eon.solution import EonSolution

NAME = "greedy heuristic (no protection, 3R regenerators)"
PROTECTION = False
REGENERATION = True          # lightpaths may use 3R (reach checked on every segment)

PARAMETER_HELP = {
    "k": "Number of candidate paths tried for each demand (k shortest by km).",
    "order": "'as_given' (arrival order) or 'largest_first' (highest data rate first).",
    "choose": "'slots' (fewest slots, then fewest 3R), '3R' (fewest 3R, then fewest slots) "
              "or 'cost' (cheapest hardware: transponders + 3R).",
}
PARAMETER_CHOICES = {"order": ["as_given", "largest_first"], "choose": ["slots", "3R", "cost"]}


def segment_path(G, path, reach_km):
    """Cut ``path`` into segments no longer than ``reach_km``, putting a 3R at
    the last node before the reach would be exceeded. Returns the list of
    segments (lists of nodes, consecutive segments share the 3R node), or None
    if one single link is longer than the reach.

    segment_path(G, ["A", "B", "C"], 900) -> [["A", "B"], ["B", "C"]]   (700 + 500 km)
    """
    # ---- 3R placement ----------------------------------------------------
    segments, start, acc = [], 0, 0.0
    for i in range(len(path) - 1):
        link = G.edges[path[i], path[i + 1]]["length"]
        if link > reach_km:
            return None                       # no node in the middle of a link
        if acc + link > reach_km:
            segments.append(path[start:i + 1])    # 3R at node path[i]
            start, acc = i, link
        else:
            acc += link
    segments.append(path[start:])
    return segments


def solve(G, demands, k=3, order="as_given", choose="slots"):
    if order == "largest_first":
        demands = sorted(demands, key=lambda d: -d.traffic)
    table = transponder_table(G)
    spectrum = Spectrum(G)
    sol = EonSolution()

    for d in demands:
        served, reach_ok = False, False
        for path in k_shortest_paths(G, d.origin, d.destination, k):
            # ---- the usable types, with the number of 3R each one needs -----
            candidates = []
            for tp in table:
                segs = segment_path(G, path, tp.reach)
                if segs is not None:
                    candidates.append((tp, len(segs) - 1))
            combo = best_combination(candidates, d.traffic, choose)
            if combo is None:
                continue
            reach_ok = True

            # ---- first-fit every SEGMENT of every lightpath (all or nothing) --
            trial = spectrum.copy()
            placed = []                       # (transponder, segments, starts)
            ok = True
            for tp, _ in combo:
                segs = segment_path(G, path, tp.reach)
                starts = []
                for seg in segs:
                    start = trial.first_fit(seg, tp.slots)   # continuity only within a segment
                    if start is None:
                        ok = False
                        break
                    trial.occupy(seg, start, tp.slots)
                    starts.append(start)
                if not ok:
                    break
                placed.append((tp, segs, starts))
            if not ok:
                continue                      # a segment does not fit: try the next path
            spectrum = trial
            for tp, segs, starts in placed:
                sol.add_lightpath(d, path, tp, starts, regenerators=[seg[0] for seg in segs[1:]])
            served = True
            break

        if not served:
            sol.block(d, "spectrum" if reach_ok else "reach")
    return sol
