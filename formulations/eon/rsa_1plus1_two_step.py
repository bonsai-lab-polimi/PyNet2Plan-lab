"""
RSA + 1+1 protection, two-step method                                   [GIVEN - complete]
=========================================================================================

1+1 dedicated protection: every demand is carried TWICE, all the time, on a
WORKING path and on a BACKUP path that shares NO FIBRE with it (a fibre =
both directions of a link: a digger cuts both). When the working path goes
dark, the receiver switches to the backup path within ~50 ms. Each path has
its own lightpaths, transponders and spectrum.

The two-step method finds the pair of paths in the simplest possible way:

1. the WORKING path is the shortest path (km) from s to t;
2. its fibres are removed from the network (BOTH directions of every link),
   and the BACKUP path is the shortest path in what is left.

If nothing is left from s to t, the demand is blocked: "no disjoint path".
The rest (transponders of each path, spectrum, all or nothing) is done by
``pynet2plan.eon.protection.solve_1plus1``, as in RSA.

Try it on EON-6 (File > Open example) with the demand C -> D: it is blocked
although the map shows two paths from C to D that share no fibre. Why? The
route formulation rsa_1plus1_ilp.py looks for the pair in another way.
"""

import networkx as nx

from pynet2plan.eon.helpers import fibre, path_fibres
from pynet2plan.eon.protection import solve_1plus1

NAME = "greedy heuristic (1+1 protection)"
PROTECTION = True            # every served demand must have a fibre-disjoint backup (checked!)
REGENERATION = False

PARAMETER_HELP = {
    "order": "'as_given' (arrival order) or 'largest_first' (highest data rate first).",
    "choose": "'slots' (fewest slots) or 'cost' (cheapest hardware).",
}
PARAMETER_CHOICES = {"order": ["as_given", "largest_first"], "choose": ["slots", "cost"]}


def disjoint_pairs(G, s, t):
    """[(working, backup)] found in two steps, or [] if there is no backup path."""
    try:
        working = nx.shortest_path(G, s, t, weight="length")           # step 1
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []
    used = path_fibres(working)                                          # step 2
    H = G.copy()
    H.remove_edges_from([(u, v) for (u, v) in G.edges if fibre(u, v) in used])
    try:
        backup = nx.shortest_path(H, s, t, weight="length")
    except nx.NetworkXNoPath:
        return []
    return [(working, backup)]


def solve(G, demands, order="as_given", choose="slots"):
    return solve_1plus1(G, demands, disjoint_pairs, order=order, choose=choose)
