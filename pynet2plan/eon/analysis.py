"""
pynet2plan.eon.analysis
======================

What an EON solution costs and what it survives (no GUI, no files)::

    from pynet2plan.eon import analysis
    cuts = analysis.fibre_cuts(G, demands, sol)          # one row per fibre
    hw = analysis.hardware(sol, table)                   # transponders, 3R, cost
    analysis.break_even(hw_a, slots_a, hw_b, slots_b)    # price of a slot where a == b
    analysis.chain_comparison(table, 1200, range(200, 3200, 200))   # long reach vs 3R

Fibre cuts
----------
A *fibre* carries both directions of a link pair, so cutting it takes down
the links (u, v) and (v, u). A demand whose working path crosses the cut
fibre goes **down** unless it has a backup path (1+1) that does not cross
it; then it is **switched** to the backup path.

Cost model (Part III of the EON lab)
------------------------------------
* a lightpath needs 2 transponders (``cost`` of its type each);
* a 3R regenerator is two transponders back to back: ``2 * cost``;
* spectrum: ``C_SLOT`` per slot per link (``total slots used``).

**total cost = hardware cost + C_SLOT × total slots used**. A slot is cheap
in an empty network and expensive in a full one (it is a demand you cannot
serve later), so which option is cheaper depends on ``C_SLOT``.
"""

from __future__ import annotations

import math

import networkx as nx

from .helpers import best_combination, combination_text, fibre, path_fibres, path_length


def by_name(table) -> dict:
    return {tp.name: tp for tp in table}


# ----------------------------------------------------------------------
# Hardware and spectrum
# ----------------------------------------------------------------------
def lightpath_slot_links(lp, table) -> int:
    """Slots x links used by one lightpath."""
    tp = by_name(table).get(lp.transponder)
    return (tp.slots if tp else 0) * max(0, len(lp.path) - 1)


def hardware(solution, table) -> dict:
    """Transponders, 3R and hardware cost of a solution. A lightpath has 2 transponders (one at
    each end) and every 3R on it is 2 more (back to back), of the type of the lightpath."""
    types = by_name(table)
    n_tx = n_3r = 0
    cost = 0.0
    for lp in solution.lightpaths:
        tp = types.get(lp.transponder)
        c = tp.cost if tp else 1.0
        r = len(lp.regenerators)
        n_tx += 2 + 2 * r
        n_3r += r
        cost += 2 * c + 2 * c * r
    return dict(lightpaths=len(solution.lightpaths), transponders=n_tx, regenerators=n_3r,
                hardware_cost=round(cost, 6))


def total_cost(hardware_cost: float, total_slots: float, c_slot: float) -> float:
    return hardware_cost + c_slot * total_slots


def break_even(hw_a: float, slots_a: float, hw_b: float, slots_b: float):
    """``C_SLOT`` at which options a and b cost the same, or None if never
    (same slots) / always ordered the same way (break-even <= 0)."""
    if abs(slots_a - slots_b) < 1e-12:
        return None
    c = (hw_b - hw_a) / (slots_a - slots_b)
    return c if c > 0 else None


# ----------------------------------------------------------------------
# Fibre cuts
# ----------------------------------------------------------------------
def fibres_of(G) -> list:
    """The fibres of the network (each pair of opposite links once), sorted."""
    seen = {}
    for u, v, a in G.edges(data=True):
        f = fibre(u, v)
        if f not in seen:
            seen[f] = (u, v) if str(u) <= str(v) else (v, u)
    return sorted(seen.values(), key=lambda e: (str(e[0]), str(e[1])))


def fibre_cuts(G, demands, solution) -> list:
    """One row per fibre: what happens when it is cut (all other fibres work).

    hit       served demands whose working path crosses the fibre
    down      hit demands without a backup path that survives the cut
    switched  hit demands moved to their (surviving) backup path
    """
    rate = {d.id: d.traffic for d in demands}
    work, back = {}, {}
    for lp in solution.lightpaths:
        (back if lp.backup else work).setdefault(lp.demand_id, set()).update(path_fibres(lp.path))
    rows = []
    for u, v in fibres_of(G):
        f = fibre(u, v)
        hit = [i for i, fs in work.items() if f in fs]
        down = [i for i in hit if i not in back or f in back[i]]
        length = G.edges[u, v].get("length") if G.has_edge(u, v) else G.edges[v, u].get("length")
        rows.append(dict(fibre=f"{u}-{v}", u=u, v=v, length=length, demands_hit=len(hit),
                         demands_down=len(down), demands_switched=len(hit) - len(down),
                         gbps_down=sum(rate.get(i, 0) for i in down),
                         down_ids=";".join(str(i) for i in sorted(down))))
    return rows


ONEWAY = "oneway"


def cut_fibres(G) -> list:
    """What is cut after planning: a list of (u, v) (a fibre: both directions) or (u, v, "oneway")
    (only the link u->v). ``G.graph["cut_after_planning"]`` is one pair (one fibre, as in older
    files) or a list of such entries."""
    c = G.graph.get("cut_after_planning")
    if not c:
        return []
    if not isinstance(c[0], (list, tuple)):
        c = [c]
    return [(str(e[0]), str(e[1])) + ((ONEWAY,) if len(e) > 2 and e[2] == ONEWAY else ()) for e in c]


def is_oneway(entry) -> bool:
    return len(entry) > 2 and entry[2] == ONEWAY


def cut_name(entry) -> str:
    """'D-E' (a fibre, both directions) or 'D>E' (only the link D->E)."""
    return f"{entry[0]}>{entry[1]}" if is_oneway(entry) else f"{entry[0]}-{entry[1]}"


def cut_links(entries) -> set:
    """The directed links (u, v) cut by these entries."""
    out = set()
    for e in entries:
        out.add((str(e[0]), str(e[1])))
        if not is_oneway(e):
            out.add((str(e[1]), str(e[0])))
    return out


def set_cut_fibres(G, entries) -> None:
    """Cut these fibres / links after planning (an empty list repairs everything). A fibre
    replaces the single directions of the same pair; a direction already cut is not repeated."""
    out = []
    for e in entries:
        e = (str(e[0]), str(e[1])) + ((ONEWAY,) if is_oneway(e) else ())
        pair = fibre(e[0], e[1])
        if not is_oneway(e):
            if any(fibre(x[0], x[1]) == pair and not is_oneway(x) for x in out):
                continue                                         # this fibre is already cut
            out = [x for x in out if fibre(x[0], x[1]) != pair]  # it replaces its single directions
        elif any(fibre(x[0], x[1]) == pair and (not is_oneway(x) or x[:2] == e[:2]) for x in out):
            continue
        out.append(e)
    if not out:
        G.graph.pop("cut_after_planning", None)
    else:
        G.graph["cut_after_planning"] = out[0] if len(out) == 1 and not is_oneway(out[0]) else out


def cut_effect(G, demands, solution, entries) -> dict:
    """What happens when all these fibres / links are cut together: a served demand whose working
    path uses a cut link is switched to its backup path if the backup uses none, else DOWN."""
    cut = cut_links(entries)
    rate = {d.id: d.traffic for d in demands}
    work, back = {}, {}
    for lp in solution.lightpaths:
        links = {(str(a), str(b)) for a, b in zip(lp.path[:-1], lp.path[1:])}
        (back if lp.backup else work).setdefault(lp.demand_id, set()).update(links)
    hit = [i for i, ls in work.items() if ls & cut]
    down = [i for i in hit if i not in back or back[i] & cut]
    return dict(fibre=", ".join(cut_name(e) for e in entries), demands_hit=len(hit),
                demands_down=len(down), demands_switched=len(hit) - len(down),
                gbps_down=sum(rate.get(i, 0) for i in down), down_ids=";".join(str(i) for i in sorted(down)))


def cut_metrics(cut_rows: list) -> dict:
    if not cut_rows:
        return dict(demands_down_avg_cut=0.0, demands_down_worst_cut=0, gbps_down_worst_cut=0,
                    worst_cut="")
    worst = max(cut_rows, key=lambda r: (r["demands_down"], r["gbps_down"]))
    return dict(demands_down_avg_cut=sum(r["demands_down"] for r in cut_rows) / len(cut_rows),
                demands_down_worst_cut=worst["demands_down"], gbps_down_worst_cut=worst["gbps_down"],
                worst_cut=worst["fibre"] if worst["demands_down"] else "")


# ----------------------------------------------------------------------
# Reach
# ----------------------------------------------------------------------
def reach_islands(G, transponder) -> list:
    """Groups of nodes connected by links not longer than the reach of
    ``transponder``. With unlimited 3R a lightpath of this type can only join
    two nodes of the same island (a 3R sits at a node, never in the middle of
    a link). Largest island first."""
    H = nx.Graph()
    H.add_nodes_from(G.nodes)
    H.add_edges_from((u, v) for u, v, a in G.edges(data=True) if float(a["length"]) <= transponder.reach)
    return sorted((sorted(c, key=str) for c in nx.connected_components(H)), key=lambda c: (-len(c), c))


# ----------------------------------------------------------------------
# Long reach or 3R? A chain of equal spans
# ----------------------------------------------------------------------
def regenerators_on_chain(km: float, span: float, reach: float):
    """3R needed by one lightpath on a chain of ``km / span`` links of ``span``
    km (a node every ``span`` km). None if a single link is beyond the reach."""
    if span > reach:
        return None
    hops = int(round(km / span))
    per_segment = int(math.floor(reach / span + 1e-9))
    return max(0, math.ceil(hops / per_segment) - 1)


def carry_on_chain(table, rate: int, km: float, span: float, with_3r: bool, order: str = "slots") -> dict:
    """How ``rate`` Gb/s is carried over ``km`` (a node every ``span`` km):
    without 3R (long-reach types only) or with 3R (fast types too)."""
    cand = []
    for tp in table:
        if with_3r:
            r = regenerators_on_chain(km, span, tp.reach)
            if r is not None:
                cand.append((tp, r))
        elif tp.reach >= km - 1e-9:
            cand.append((tp, 0))
    combo = best_combination(cand, rate, order)
    links = int(round(km / span))
    if not combo:
        return dict(km=km, lightpaths="— no transponder type —", n_lightpaths=0, transponders=0,
                    regenerators=0, hardware_cost=None, slots_per_link=None, links=links,
                    total_slots=None)
    hw = sum(2 * tp.cost * (1 + r) for tp, r in combo)
    slots = sum(tp.slots for tp, _ in combo)
    return dict(km=km, lightpaths=combination_text([tp for tp, _ in combo]), n_lightpaths=len(combo),
                transponders=2 * len(combo), regenerators=sum(r for _, r in combo),
                hardware_cost=round(hw, 6), slots_per_link=slots, links=links,
                total_slots=slots * links)


def verdict(extra_hw, slots_saved, be) -> str:
    """Which option is cheaper, in words."""
    if extra_hw is None or slots_saved is None:
        return "one option is not possible"
    if extra_hw == 0 and slots_saved == 0:
        return "same lightpaths: no difference"
    if extra_hw <= 0 and slots_saved >= 0:
        return "3R always cheaper"
    if extra_hw >= 0 and slots_saved <= 0:
        return "long reach always cheaper"
    return f"3R cheaper if C_SLOT > {be:.3g}" if be is not None else ""


def chain_comparison(table, rate: int, distances, span: float = 200.0) -> list:
    """For every distance: long reach (no 3R) vs fast types + 3R, the extra
    hardware cost of 3R, the slots it saves and the break-even ``C_SLOT``."""
    rows = []
    for km in distances:
        lr = carry_on_chain(table, rate, km, span, False)
        r3 = carry_on_chain(table, rate, km, span, True)
        row = dict(km=km, long_reach=lr["lightpaths"], with_3r=r3["lightpaths"],
                   regenerators=r3["regenerators"], hw_long_reach=lr["hardware_cost"],
                   hw_3r=r3["hardware_cost"], slots_long_reach=lr["total_slots"],
                   slots_3r=r3["total_slots"], extra_hw_3r=None, slots_saved_3r=None, break_even=None,
                   verdict="")
        if lr["hardware_cost"] is not None and r3["hardware_cost"] is not None:
            row["extra_hw_3r"] = round(r3["hardware_cost"] - lr["hardware_cost"], 6)
            row["slots_saved_3r"] = lr["total_slots"] - r3["total_slots"]
            row["break_even"] = break_even(lr["hardware_cost"], lr["total_slots"],
                                           r3["hardware_cost"], r3["total_slots"])
        row["verdict"] = verdict(row["extra_hw_3r"], row["slots_saved_3r"], row["break_even"])
        rows.append(row)
    return rows


def path_km(G, path) -> float:
    return path_length(G, path)
