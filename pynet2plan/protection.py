"""
pynet2plan.protection
======================

The common part of the 1+1 protection algorithms. A 1+1 algorithm only has to
say WHICH pair of paths protects each demand; this module does the rest, exactly
as an RWA heuristic (``formulations/ksp_first_fit.py``) does for one path:

* for each candidate pair (working path, backup path), best first, it assigns
  ``d.traffic`` wavelengths to the working path and ``d.traffic`` wavelengths to
  the backup path (wavelength continuity: the same indices on every link of the
  path), with first-fit;
* **all or nothing**: the first pair where BOTH paths fit is used, and both are
  reserved; otherwise the next pair is tried;
* a demand with no pair that fits is blocked (no route is added for it).

    from pynet2plan.protection import solve_1plus1

    def disjoint_pairs(G, s, t):          # the part written for each algorithm
        ...
        return [(working, backup), ...]   # best first; [] if there is none

    def solve(G, demands, order="as_given"):
        return solve_1plus1(G, demands, disjoint_pairs, order=order)

The pairs are NOT checked here: a pair whose paths share a fibre gives an
INVALID result, with the shared fibre in the message (the independent checker
of :mod:`pynet2plan.validation`).
"""

from __future__ import annotations

from .solution import Solution


def _links(path) -> list:
    return list(zip(path[:-1], path[1:]))


WEIGHTS = ["hops", "length"]


def path_weight(weight: str = "hops"):
    """The networkx ``weight`` of a shortest-path search: ``'hops'`` = the fewest links (every
    link costs one more wavelength), equal hops: the shorter in km; ``'length'`` = the
    shortest in km."""
    if weight == "length":
        return "length"
    if weight == "hops":
        return lambda u, v, a: 1 + 1e-7 * float(a.get("length", 0) or 0)
    raise ValueError("weight must be 'hops' or 'length'")


def first_fit(G, path, used: dict, count: int):
    """The ``count`` lowest wavelength indices free on EVERY link of ``path``
    (wavelength continuity, first-fit), or None if fewer than ``count`` exist.
    ``used[(i, j)]`` maps a wavelength index to how many fibres already carry it
    on link (i, j)."""
    links = _links(path)
    if not links:
        return None
    w_max = min(G.edges[i, j]["capacity"] for (i, j) in links)       # exist on every link
    fibers = {(i, j): G.edges[i, j].get("fibers", 1) for (i, j) in links}
    free = []
    for w in range(w_max):
        if all(used[i, j].get(w, 0) < fibers[i, j] for (i, j) in links):
            free.append(w)
            if len(free) == count:
                return free
    return None


def solve_1plus1(G, demands, disjoint_pairs, order: str = "as_given") -> Solution:
    """RWA + 1+1 dedicated protection: every served demand is carried on a working
    path AND on a fibre-disjoint backup path, both given by
    ``disjoint_pairs(G, origin, destination)`` (a list of (working, backup) pairs,
    best first). A demand that fits on no pair is blocked."""
    if order == "largest_first":
        demands = sorted(demands, key=lambda d: -d.traffic)
    elif order != "as_given":
        raise ValueError("order must be 'as_given' or 'largest_first'")

    used = {(i, j): {} for (i, j) in G.edges}        # (i, j) -> {wavelength: fibres carrying it}
    sol = Solution()
    for d in demands:
        count = int(d.traffic)
        for working, backup in disjoint_pairs(G, d.origin, d.destination) or []:
            trial = {e: dict(w) for e, w in used.items()}        # all or nothing: work on a copy
            plan = []
            for path, is_backup in ((working, False), (backup, True)):
                wls = first_fit(G, path, trial, count)
                if wls is None:
                    break
                for (i, j) in _links(path):
                    for w in wls:
                        trial[i, j][w] = trial[i, j].get(w, 0) + 1
                plan.append((path, wls, is_backup))
            if len(plan) < 2:
                continue                                         # one path did not fit: next pair
            used = trial
            for path, wls, is_backup in plan:
                sol.add_route(d, path, len(wls), wavelengths=wls, backup=is_backup)
            break                                                # served
        # no pair fits (or none exists): the demand is blocked (no route added)
    return sol


__all__ = ["solve_1plus1", "first_fit"]
