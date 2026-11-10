"""
1+1 protection, two-step heuristic                                      [GIVEN - complete]
=========================================================================================

1+1 dedicated protection: every demand is carried TWICE, all the time, on a
WORKING path and on a BACKUP path that shares NO FIBRE with it (a fibre = both
directions of a link: a digger cuts both). When the working path goes dark, the
receiver switches to the backup path within ~50 ms. Each path gets its own
wavelengths (wavelength continuity, no conversion).

The two-step method finds the pair of paths in the simplest possible way:

1. the WORKING path is the shortest path from s to t (the fewest hops: every link costs
   one more wavelength; equal hops: the shorter in km);
2. its fibres are removed from the network (BOTH directions of every link), and
   the BACKUP path is the shortest path in what is left.

If nothing is left from s to t, the demand has no disjoint pair and is blocked.
With an optical reach (File > Optical reach), the demand is also blocked when one
of the two paths is longer than the reach (no 3R regenerators). The backup is
the longer path, so it is usually the one that does not make it.
The rest (wavelengths of each path, all or nothing) is done by
``pynet2plan.protection.solve_1plus1``, exactly as the RWA heuristic routes one
path.

Compare it with no protection (``ksp_first_fit.py``): 1+1 uses about twice the
wavelengths, but no single fibre cut takes a served demand down. The route
formulation ``protection_route_formulation.py`` chooses the pairs of all the
demands together instead of one demand at a time.
"""

import networkx as nx

from pynet2plan.network import fibre, path_fibres, within_reach
from pynet2plan.protection import WEIGHTS, path_weight, solve_1plus1

NAME = "greedy heuristic (1+1 protection)"
SPLITTABLE = False           # one working path and one backup path per demand
ALLOWS_BLOCKING = True       # a demand with no disjoint pair that fits is blocked
PROTECTION = True            # every served demand must have a fibre-disjoint backup (checked!)
ORDER = 7                    # position in the list of algorithms of the GUI

PARAMETER_HELP = {
    "weight": "'hops' (fewest links, equal hops: shorter in km) or 'length' (km).",
    "order": "'as_given' (demand id order) or 'largest_first' (largest traffic first).",
}
PARAMETER_CHOICES = {"weight": WEIGHTS, "order": ["as_given", "largest_first"]}


def disjoint_pairs(G, s, t, weight="hops"):
    """[(working, backup)] found in two steps, or [] if there is no backup path."""
    try:
        working = nx.shortest_path(G, s, t, weight=path_weight(weight))  # step 1
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []
    used = path_fibres(working)                                         # step 2
    H = G.copy()
    H.remove_edges_from([(u, v) for (u, v) in G.edges if fibre(u, v) in used])
    try:
        backup = nx.shortest_path(H, s, t, weight=path_weight(weight))
    except nx.NetworkXNoPath:
        return []
    if not (within_reach(G, working) and within_reach(G, backup)):
        return []                                    # a path longer than the optical reach
    return [(working, backup)]


def solve(G, demands, weight="hops", order="as_given"):
    return solve_1plus1(G, demands, lambda G, s, t: disjoint_pairs(G, s, t, weight), order=order)
