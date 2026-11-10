"""
greedy heuristic (no protection)                                        [GIVEN - complete]
=========================================================================================

A fast RWA heuristic, no ILP: the demands are routed one at a time. For each
demand we try its k shortest paths in order (shortest = the fewest hops, since every
link costs one more wavelength; equal hops: the shorter in km) and route ALL its wavelengths on the
FIRST path that still has free wavelengths on every link ("first fit", with
wavelength continuity: the same wavelength indices on every link of the path). A
demand that fits on no candidate path is blocked.

With an optical reach (File > Optical reach), a candidate path longer than the
reach is skipped: without 3R regenerators the signal would not arrive readable.

This is the baseline for 1+1 protection: it uses the fewest wavelengths, but a
single fibre cut takes down every demand whose (only) path crosses it. Compare it
with ``greedy_1plus1_protection.py`` in the Results > Fibre cuts tab.
"""

from itertools import islice

import networkx as nx

from pynet2plan.network import within_reach
from pynet2plan.protection import WEIGHTS, first_fit, path_weight
from pynet2plan.solution import Solution

NAME = "greedy heuristic (no protection)"
SPLITTABLE = False           # each demand uses a single path
ALLOWS_BLOCKING = True       # a demand that does not fit is blocked
ORDER = 6                    # position in the list of algorithms of the GUI

PARAMETER_HELP = {
    "k": "Number of candidate paths tried for each demand (k shortest paths).",
    "weight": "'hops' (fewest links, equal hops: shorter in km) or 'length' (km).",
    "order": "'as_given' (demand id order) or 'largest_first' (largest traffic first).",
}
PARAMETER_CHOICES = {"weight": WEIGHTS, "order": ["as_given", "largest_first"]}


def solve(G, demands, k=3, weight="hops", order="as_given"):
    if order == "largest_first":
        demands = sorted(demands, key=lambda d: -d.traffic)
    elif order != "as_given":
        raise ValueError("order must be 'as_given' or 'largest_first'")
    w = path_weight(weight)

    used = {(i, j): {} for (i, j) in G.edges}          # (i, j) -> {wavelength: fibres carrying it}
    sol = Solution()
    for d in demands:
        count = int(d.traffic)
        for path in islice(nx.shortest_simple_paths(G, d.origin, d.destination, weight=w), k):
            if not within_reach(G, path):
                continue                               # longer than the optical reach (no 3R)
            wls = first_fit(G, path, used, count)
            if wls is None:
                continue                               # does not fit on this path: try the next
            for (i, j) in zip(path[:-1], path[1:]):
                for wl in wls:
                    used[i, j][wl] = used[i, j].get(wl, 0) + 1
            sol.add_route(d, path, len(wls), wavelengths=wls)
            break
        # if no candidate path fits, the demand is blocked (no route added)
    return sol
