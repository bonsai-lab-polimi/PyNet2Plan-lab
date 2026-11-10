"""
greedy heuristic with 3R regenerators (no protection)                   [GIVEN - complete]
=========================================================================================

The greedy RWA heuristic of ``greedy_no_protection.py``, for a network with an
OPTICAL REACH (File > Limit the optical reach): an optical signal becomes
unreadable after a certain distance (noise, dispersion), so a lightpath longer
than the reach must be REGENERATED on the way. A **3R regenerator** (Re-amplify,
Re-shape, Re-time) converts the signal to electronics and back to light (O/E/O)
in an intermediate node; after it the signal can travel the full reach again.

The demands are routed one at a time. For each demand we try its k shortest
paths (km) in order; on each path the 3R regenerators are placed as FAR along
the path as possible: the signal goes on while the next link still fits in the
reach, otherwise it is regenerated in the node it has reached
(``pynet2plan.network.regenerator_sites``). This gives the fewest regeneration
nodes on that path. A path with a single link longer than the reach cannot be
used (a 3R sits in a node, not in the middle of a fibre). ALL the wavelengths of
the demand go on the first path with free wavelengths on every link (first fit,
wavelength continuity); a demand that fits on no candidate path is blocked.

A 3R regenerates ONE wavelength: a demand of h wavelengths regenerated in one
node needs h regenerators there. (A 3R could also change the wavelength, since
the signal goes through electronics; here we keep the same wavelengths end to end
to stay as close as possible to the heuristic without 3R.)

Compare it with ``greedy_no_protection.py`` on the same network: without 3R a
demand farther than the reach is blocked; with 3R it is served, at the price of
the regenerators (Report: "3R regenerators"; map: the 3R marks on the nodes).
"""

from itertools import islice

import networkx as nx

from pynet2plan.network import regenerator_sites
from pynet2plan.protection import first_fit
from pynet2plan.solution import Solution

NAME = "greedy heuristic (no protection, 3R regenerators)"
SPLITTABLE = False           # each demand uses a single path
ALLOWS_BLOCKING = True       # a demand that does not fit is blocked
ORDER = 9                    # position in the list of algorithms of the GUI

PARAMETER_HELP = {
    "k": "Number of candidate paths tried for each demand (k shortest paths, in km).",
    "order": "'as_given' (demand id order) or 'largest_first' (largest traffic first).",
}
PARAMETER_CHOICES = {"order": ["as_given", "largest_first"]}


def solve(G, demands, k=3, order="as_given"):
    if order == "largest_first":
        demands = sorted(demands, key=lambda d: -d.traffic)
    elif order != "as_given":
        raise ValueError("order must be 'as_given' or 'largest_first'")

    used = {(i, j): {} for (i, j) in G.edges}          # (i, j) -> {wavelength: fibres carrying it}
    sol = Solution()
    for d in demands:
        count = int(d.traffic)
        for path in islice(nx.shortest_simple_paths(G, d.origin, d.destination, weight="length"), k):
            regs = regenerator_sites(G, path)          # 3R nodes ([] if within the reach)
            if regs is None:
                continue                               # a link longer than the reach: unusable
            wls = first_fit(G, path, used, count)
            if wls is None:
                continue                               # does not fit on this path: try the next
            for (i, j) in zip(path[:-1], path[1:]):
                for wl in wls:
                    used[i, j][wl] = used[i, j].get(wl, 0) + 1
            sol.add_route(d, path, len(wls), wavelengths=wls, regenerators=regs)
            break
        # if no candidate path fits, the demand is blocked (no route added)
    sol.info["regenerators"] = sol.num_regenerators()
    return sol
