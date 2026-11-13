"""
RSA + 3R with a choice of the objective                        [HOMEWORK - to complete]        
================================================================================================

rsa_3r.py takes, for every demand, the lightpaths with the fewest slots. That is
one possible objective, not the only one: a 3R saves spectrum (a fast transponder
type can then cover a long path) but costs 2 more transponders; a slow type is
cheap but needs more slots per Gb/s.

Here the choice is driven by a SCORE: on every path the combination of lightpaths
with the LOWEST score is taken, and the parameter ``objective`` selects the score:

    "spectrum"   the spectrum of the combination: its slots, on every link of the path
    "hardware"   its hardware cost: all its transponders, those of its 3R included
    "total"      its hardware cost plus the price of its spectrum (``c_slot`` for
                 one slot on one link)

Everything else is rsa_3r.py:

1. for every demand (in order), the k shortest paths, the shortest first;
2. on a path, for every transponder type that can cover it (with 3R if needed,
   segment_path): the combination of n lightpaths of that type that carries the
   demand. The combination with the lowest score is chosen (on a tie: the fewest
   slots, then the fewest 3R, then the fewest lightpaths);
3. it is placed with first-fit on every segment, all or nothing. If it does not
   fit: the next path. A demand that fits on no path is blocked.

Complete the two TODO blocks below. In each block, write your code and then
DELETE the line ``raise NotCompletedError(...)``. Everything else is given (the
3R placement and the first-fit are the ones of rsa_3r.py).

After completing the TODOs, carry out the experiments described in the
homework on ITALY, FUNET and NSFNET13. Prepare your own tables and plots.
You may write a script to organize the repeated runs and collect the results.
"""

from pynet2plan.eon.helpers import Spectrum, k_shortest_paths, transponder_table
from pynet2plan.eon.solution import EonSolution
from pynet2plan.errors import NotCompletedError

NAME = "greedy heuristic (no protection, 3R regenerators, objective)"
PROTECTION = False
REGENERATION = True          # lightpaths may use 3R (reach checked on every segment)

PARAMETER_HELP = {
    "k": "Number of candidate paths tried for each demand (k shortest by km).",
    "objective": "'spectrum' (fewest slots), 'hardware' (cheapest transponders, 3R included) or "
                 "'total' (hardware cost + c_slot for every slot on every link).",
    "c_slot": "Price of one slot on one link (objective 'total'), in the cost units of the "
              "transponder table.",
}
PARAMETER_CHOICES = {"objective": ["spectrum", "hardware", "total"]}


def segment_path(G, path, reach_km):
    """The segments of ``path`` with a 3R at the last node before the reach would be exceeded
    (as in rsa_3r.py), or None if one link alone is longer than the reach."""
    segments, start, acc = [], 0, 0.0
    for i in range(len(path) - 1):
        link = G.edges[path[i], path[i + 1]]["length"]
        if link > reach_km:
            return None
        if acc + link > reach_km:
            segments.append(path[start:i + 1])
            start, acc = i, link
        else:
            acc += link
    segments.append(path[start:])
    return segments


def hardware_cost(tp, regens, n):
    """The cost of the transponders of n lightpaths of type tp with ``regens`` 3R each."""
    # ---- TODO 1: the hardware cost of a combination ----------------------------------
    # Return the cost of all the transponders of the combination (a number). You have:
    #   n        the number of lightpaths (all of type tp)
    #   regens   the number of 3R on EACH lightpath
    #   tp.cost  the price of ONE transponder of this type (cost column, Transponders tab)
    # A lightpath needs 2 transponders (one at each end); a 3R is 2 more transponders of
    # the same type (back to back).
    raise NotCompletedError("TODO 1: the hardware cost of a combination (3R included).")


def score(objective, tp, regens, n, links, c_slot):
    """The score of n lightpaths of type tp, with ``regens`` 3R each, on a path of ``links``
    links: the lower, the better."""
    slots = n * tp.slots * links          # the spectrum of the combination: slots x links
    if objective == "spectrum":
        return slots
    elif objective == "hardware":
        return hardware_cost(tp, regens, n)
    elif objective == "total":
        # ---- TODO 2: hardware cost plus the price of the spectrum --------------------
        # Return the hardware cost of the combination plus the price of the spectrum
        # that it occupies. You have:
        #   slots    the spectrum of the combination (above)
        #   c_slot   the price of ONE slot on ONE link
        raise NotCompletedError("TODO 2: the score of the objective 'total'.")
    raise ValueError(f"objective must be 'spectrum', 'hardware' or 'total', not '{objective}'")


def combinations(candidates, rate, objective, links, c_slot):
    """All the combinations that carry ``rate`` Gb/s, the lowest score first (on a tie: the
    fewest slots, the fewest 3R, the fewest lightpaths, the fewest Gb/s wasted):
    (transponder, 3R per lightpath, n lightpaths) - n lightpaths of ONE type."""
    out = []
    for i, (tp, regens) in enumerate(sorted(set(candidates), key=lambda c: (-c[0].rate, c[0].slots, c[1], c[0].name))):
        n = -(-int(rate) // int(tp.rate))                               # ceil
        key = (score(objective, tp, regens, n, links, c_slot), n * tp.slots, n * regens, n, n * tp.rate - rate, i)
        out.append((key, (tp, regens, n)))
    return [c for _, c in sorted(out, key=lambda x: x[0])]


def solve(G, demands, k=3, objective="spectrum", c_slot=0.4):
    table = transponder_table(G)
    spectrum = Spectrum(G)
    sol = EonSolution()

    for d in demands:
        served, reach_ok = False, False
        for path in k_shortest_paths(G, d.origin, d.destination, k):
            candidates = []
            for tp in table:
                segs = segment_path(G, path, tp.reach)
                if segs is not None:
                    candidates.append((tp, len(segs) - 1))
            if not candidates:
                continue
            reach_ok = True

            # ---- the combination with the lowest score on this path ----------------------------
            tp, regens, n = combinations(candidates, d.traffic, objective, len(path) - 1, float(c_slot))[0]

            # ---- first-fit every SEGMENT of every lightpath, all or nothing (as in rsa_3r) ----
            segs = segment_path(G, path, tp.reach)
            trial = spectrum.copy()
            placed = []
            for _ in range(n):
                starts = []
                for seg in segs:
                    start = trial.first_fit(seg, tp.slots)
                    if start is None:
                        break
                    trial.occupy(seg, start, tp.slots)
                    starts.append(start)
                if len(starts) < len(segs):
                    break
                placed.append(starts)
            if len(placed) < n:
                continue                  # a segment does not fit: the next path
            spectrum = trial

            for starts in placed:
                sol.add_lightpath(d, path, tp, starts, regenerators=[seg[0] for seg in segs[1:]])
            served = True
            break

        if not served:
            sol.block(d, "spectrum" if reach_ok else "reach")
    return sol
