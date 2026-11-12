"""
pynet2plan.eon.helpers
=====================

What the EON algorithms of ``formulations/eon/`` use::

    from pynet2plan.eon.helpers import (transponder_table, Spectrum, k_shortest_paths,
                                       path_length, path_links, path_fibres,
                                       types_reaching, best_combination)

The EON settings travel with the network
----------------------------------------
Before calling ``solve(G, demands, ...)`` the EON runner stores the
transponder table and the size of the spectrum in ``G.graph``::

    table = transponder_table(G)   # list of Transponder (rate, modulation, slots, reach, cost)
    S = num_slots(G)               # slots per link (320 = 4 THz / 12.5 GHz)

The spectrum
------------
:class:`Spectrum` is the state of the whole network: for every
*unidirectional* link ``(u, v)`` a numpy array of ``S`` booleans,
``spectrum.used[(u, v)][s] == True`` meaning slot ``s`` is taken on that
link. A lightpath ``A -> B -> C`` occupies the links ``(A, B)`` and
``(B, C)``; the opposite direction ``C -> A`` has its own spectrum.

A *fibre* is the pair of opposite links ``{(u, v), (v, u)}``: a digger cuts
both directions at once, so 1+1 protection needs paths that share no fibre
(``path_fibres``).
"""

from __future__ import annotations


import networkx as nx
import numpy as np

from .. import helpers as _base
from .transponders import DEFAULT_NUM_SLOTS, DEFAULT_SLOT_WIDTH

# ----------------------------------------------------------------------
# EON settings stored in G.graph by the runner
# ----------------------------------------------------------------------
GRAPH_TABLE = "eon_transponders"
GRAPH_SLOTS = "eon_num_slots"
GRAPH_SLOT_WIDTH = "eon_slot_width"


def transponder_table(G) -> list:
    """The transponder types available on this network (list of Transponder)."""
    table = G.graph.get(GRAPH_TABLE)
    if table is None:
        from .transponders import load_table
        table = load_table(slot_width=slot_width(G))
    return list(table)


def num_slots(G) -> int:
    """Number of frequency slots on every link."""
    return int(G.graph.get(GRAPH_SLOTS, DEFAULT_NUM_SLOTS))


def slot_width(G) -> float:
    """Width of one slot in GHz."""
    return float(G.graph.get(GRAPH_SLOT_WIDTH, DEFAULT_SLOT_WIDTH))


def setup(G, table=None, slots: int = DEFAULT_NUM_SLOTS, width: float = DEFAULT_SLOT_WIDTH):
    """Store the EON settings in ``G.graph`` (the runner does this for you;
    handy in scripts and notebooks). Returns ``G``."""
    if table is None:
        from .transponders import load_table
        table = load_table(slot_width=width)
    G.graph[GRAPH_TABLE] = list(table)
    G.graph[GRAPH_SLOTS] = int(slots)
    G.graph[GRAPH_SLOT_WIDTH] = float(width)
    return G


# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------
def path_links(path) -> list:
    """``["A", "B", "C"]`` -> ``[("A", "B"), ("B", "C")]``"""
    return list(zip(path[:-1], path[1:]))


def path_length(G, path) -> float:
    """Length of a path in km (sum of the link lengths)."""
    return sum(float(G.edges[u, v]["length"]) for u, v in path_links(path))


def k_shortest_paths(G, source, target, k: int = 3) -> list:
    """The k shortest loopless paths by length in km (lists of nodes)."""
    return _base.k_shortest_paths(G, source, target, k, weight="length")


def fibre(u, v) -> frozenset:
    """The fibre of link (u, v): the same object for (u, v) and (v, u)."""
    return frozenset((u, v))


def path_fibres(path) -> set:
    """The fibres crossed by a path."""
    return {fibre(u, v) for u, v in path_links(path)}


def segments_of(path, regenerators) -> list:
    """Cut ``path`` at the 3R nodes: ``(["A","B","C","D"], ["C"])`` ->
    ``[["A","B","C"], ["C","D"]]``."""
    segs, start = [], 0
    for i, n in enumerate(path):
        if 0 < i < len(path) - 1 and n in regenerators:
            segs.append(list(path[start:i + 1]))
            start = i
    segs.append(list(path[start:]))
    return segs


# ----------------------------------------------------------------------
# Transponder types
# ----------------------------------------------------------------------
def types_reaching(table, km: float) -> list:
    """The transponder types whose reach covers ``km`` (no 3R)."""
    return [tp for tp in table if tp.reach >= km - 1e-9]


def _head(order, slots, regens, cost):
    return {"slots": (slots, regens), "3R": (regens, slots), "cost": (cost, slots)}[order]


def best_combination(candidates, rate: int, order: str = "slots", max_lightpaths: int | None = None):
    """The lightpaths that carry ``rate`` Gb/s: ``n`` lightpaths of ONE
    transponder type, chosen among ``candidates``.

    A demand never mixes transponder types (no 500G PCS 16QAM + 100G QPSK):
    every lightpath of a demand has the same configuration (rate, modulation,
    slots), also on both sides of every 3R. ``n`` = ceil(rate / rate of the type).

    candidates   list of ``(transponder, number_of_3R)`` pairs that can be used
                 on the path (``number_of_3R`` is 0 without regeneration)
    order        "slots": fewest slots, then fewest 3R   (default)
                 "3R":    fewest 3R, then fewest slots
                 "cost":  lowest hardware cost (2 transponders + 2 per 3R), then fewest slots
    Further ties: fewest lightpaths, least unused capacity.

    max_lightpaths  at most this many lightpaths (default: no limit)

    Returns a list of ``(transponder, number_of_3R)``, the same pair ``n``
    times, or None if ``candidates`` is empty (or every type needs more than
    ``max_lightpaths`` lightpaths).

    Example: 600 Gb/s over 1200 km without 3R -> 2 x 300G PCS 16QAM (16 slots).
    """
    if order not in ("slots", "3R", "cost"):
        raise ValueError("order must be 'slots', '3R' or 'cost'")
    cand = sorted(set((tp, int(r)) for tp, r in candidates),
                  key=lambda c: (-c[0].rate, c[0].slots, c[1], c[0].name))
    if not cand or rate <= 0:
        return None
    best, best_key = None, None
    for tp, r in cand:
        n = -(-int(rate) // int(tp.rate))                               # ceil
        if max_lightpaths is not None and n > max_lightpaths:
            continue
        key = _head(order, n * tp.slots, n * r, n * tp.cost * (2 + 2 * r)) + (n, n * tp.rate - rate)
        if best_key is None or key < best_key:
            best, best_key = (tp, r), key
    return [best] * (-(-int(rate) // int(best[0].rate))) if best is not None else None


def combination_text(names) -> str:
    """``["300G PCS 16QAM", "300G PCS 16QAM"]`` -> ``"2 × 300G PCS 16QAM"``
    (repeated types as ``"2 × 300G PCS 16QAM"``). Accepts names or Transponders."""
    names = [getattr(n, "name", n) for n in names]
    return " + ".join(f"{names.count(n)} × {n}" if names.count(n) > 1 else n
                      for n in dict.fromkeys(names))


# ----------------------------------------------------------------------
# Spectrum bookkeeping
# ----------------------------------------------------------------------
class Spectrum:
    """Which slots are taken on every unidirectional link of ``G``.

    ``spectrum.used[(u, v)]`` is a numpy array of ``num_slots`` booleans.
    """

    def __init__(self, G, slots: int | None = None):
        self.num_slots = int(slots if slots is not None else num_slots(G))
        self.used = {(u, v): np.zeros(self.num_slots, dtype=bool) for u, v in G.edges}

    def copy(self) -> "Spectrum":
        new = Spectrum.__new__(Spectrum)
        new.num_slots = self.num_slots
        new.used = {e: occ.copy() for e, occ in self.used.items()}
        return new

    def free_on_path(self, path) -> np.ndarray:
        """CONTINUITY: the slots that are free on EVERY link of the path."""
        free = np.ones(self.num_slots, dtype=bool)
        for e in path_links(path):
            free &= ~self.used[e]
        return free

    def first_fit(self, path, n: int):
        """Lowest slot ``s`` such that slots ``s .. s+n-1`` are free on every
        link of the path (continuity + contiguity). None if it does not fit."""
        free = self.free_on_path(path)
        for s in range(self.num_slots - n + 1):
            if free[s:s + n].all():          # contiguity: n slots side by side
                return s
        return None

    def is_free(self, path, start: int, n: int) -> bool:
        if start < 0 or start + n > self.num_slots:
            return False
        return bool(self.free_on_path(path)[start:start + n].all())

    def occupy(self, path, start: int, n: int) -> None:
        """Mark slots ``start .. start+n-1`` as taken on every link of the path."""
        for e in path_links(path):
            self.used[e][start:start + n] = True

    def release(self, path, start: int, n: int) -> None:
        for e in path_links(path):
            self.used[e][start:start + n] = False

    def slots_used(self, link) -> int:
        return int(self.used[link].sum())

    def total_slots_used(self) -> int:
        """Sum over all links of the slots in use."""
        return int(sum(occ.sum() for occ in self.used.values()))

    def max_slot_index(self) -> int:
        """Highest slot in use on any link, + 1 (0 if the network is empty)."""
        top = [int(np.flatnonzero(occ)[-1]) + 1 for occ in self.used.values() if occ.any()]
        return max(top, default=0)


__all__ = ["transponder_table", "num_slots", "slot_width", "setup", "path_links", "path_length",
           "k_shortest_paths", "fibre", "path_fibres", "segments_of",
           "types_reaching", "best_combination", "combination_text", "Spectrum"]
