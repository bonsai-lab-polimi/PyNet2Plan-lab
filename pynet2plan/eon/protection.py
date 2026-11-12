"""
pynet2plan.eon.protection
========================

The common part of the 1+1 algorithms. A 1+1 algorithm only has to say
WHICH pair of paths protects a demand; this module does the rest, exactly as
RSA (``formulations/eon/rsa_greedy.py``) does for one path:

* for each candidate pair (working path, backup path), best first, the
  lightpaths of each path: n lightpaths of one transponder type whose reach
  covers that path (``best_combination``);
* first-fit of ALL the lightpaths of BOTH paths, all or nothing: the first
  pair where everything fits is used;
* otherwise the demand is blocked: "no disjoint path" (no candidate pair),
  "reach" (no type reaches one of the two paths) or "spectrum".

    from pynet2plan.eon.protection import solve_1plus1

    def disjoint_pairs(G, s, t):          # the part written for each algorithm
        ...
        return [(working, backup), ...]   # best first; [] if there is none

    def solve(G, demands, order="as_given", choose="slots"):
        return solve_1plus1(G, demands, disjoint_pairs, order=order, choose=choose)

The pairs are NOT checked here: a pair whose paths share a fibre gives an
INVALID result, with the shared fibre in the message (the independent
checker of pynet2plan.eon.validation).
"""

from __future__ import annotations

from .helpers import Spectrum, best_combination, path_length, transponder_table, types_reaching
from .solution import EonSolution


def lightpaths_of(G, table, path, rate, choose="slots"):
    """The transponder types of the lightpaths of ``path`` (n times one type), or None
    if no type reaches the whole path."""
    return best_combination([(tp, 0) for tp in types_reaching(table, path_length(G, path))], rate, choose)


def solve_1plus1(G, demands, disjoint_pairs, order: str = "as_given", choose: str = "slots") -> EonSolution:
    """RSA + 1+1 dedicated protection: every served demand is carried on a working
    path AND on a backup path, given by ``disjoint_pairs(G, origin, destination)``
    (a list of (working, backup) pairs, best first)."""
    if order == "largest_first":
        demands = sorted(demands, key=lambda d: -d.traffic)
    table = transponder_table(G)
    spectrum = Spectrum(G)
    sol = EonSolution()

    for d in demands:
        pairs = list(disjoint_pairs(G, d.origin, d.destination) or [])
        reach_ok = served = False
        for working, backup in pairs:
            combo_w = lightpaths_of(G, table, working, d.traffic, choose)
            combo_b = lightpaths_of(G, table, backup, d.traffic, choose)
            if combo_w is None or combo_b is None:
                continue                                  # one of the two paths is out of reach
            reach_ok = True
            plan = [(working, tp, False) for tp, _ in combo_w] + [(backup, tp, True) for tp, _ in combo_b]
            trial = spectrum.copy()                       # all or nothing: try on a copy
            starts = []
            for path, tp, _ in plan:
                start = trial.first_fit(path, tp.slots)
                if start is None:
                    break
                trial.occupy(path, start, tp.slots)
                starts.append(start)
            if len(starts) < len(plan):
                continue                                  # does not fit: next pair
            spectrum = trial
            for (path, tp, is_backup), start in zip(plan, starts):
                sol.add_lightpath(d, path, tp, start, backup=is_backup)
            served = True
            break
        if not served:
            sol.block(d, "no disjoint path" if not pairs else ("spectrum" if reach_ok else "reach"))
    return sol


__all__ = ["solve_1plus1", "lightpaths_of"]
