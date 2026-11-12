"""
pynet2plan.eon.validation
========================

An independent checker for the solutions of the EON algorithms. The EON
runner calls it before saving, so a mistake in an algorithm is reported as
INVALID with a clear message instead of producing nonsense. It checks the
four RSA constraints plus protection and regeneration:

* **reach**        every segment of a lightpath is not longer than the reach
                   of its transponder type
                   ("Lightpath #3 (demand 5, 200G 16QAM): segment A > B > C is
                   1200 km but the reach of 200G 16QAM is 900 km.")
* **contiguity**   implied by the solution format: a lightpath occupies
                   ``slots`` adjacent slots starting at ``start``
* **continuity**   the same slots on every link of a segment (again implied
                   by the format: one start per segment)
* **non-overlap**  two lightpaths never share a slot on the same link
                   ("Slot 12 of link B->C is used by 2 lightpaths (demands 3, 7).")
* every slot inside the band ``0 .. num_slots-1``
* every served demand carries at least its data rate, with lightpaths of ONE
  transponder type (no 500G PCS 16QAM + 100G QPSK; the same type also on both
  sides of every 3R, which the format implies)
* **1+1**          (PROTECTION = True) every served demand has a backup path
                   that shares no fibre with its working path
* **3R**           only at intermediate nodes of the path, and only if the
                   algorithm declares REGENERATION = True
"""

from __future__ import annotations

from ..network import link_label
from ..validation import MAX_MESSAGES, Issue
from .helpers import path_fibres, path_length

_EPS = 1e-6


def validate_eon(G, demands: list, solution, table: list, num_slots: int, *,
                 protection: bool = False, regeneration: bool = False,
                 allows_blocking: bool = True) -> list:
    """Check ``solution`` on ``G`` (the up links only) for the ``demands`` given
    to the algorithm. Returns a list of :class:`~pynet2plan.validation.Issue`."""
    errors: list = []
    warnings: list = []
    by_id = {d.id: d for d in demands}
    types = {tp.name: tp for tp in table}
    owner: dict = {}               # (u, v) -> list (per slot) of lightpath index or None
    clashes: dict = {}             # (u, v) -> (first slot, set of lightpath indices)

    for k, lp in enumerate(solution.lightpaths):
        where = f"Lightpath #{k + 1} (demand {lp.demand_id}, {lp.transponder}{', backup' if lp.backup else ''})"
        d = by_id.get(lp.demand_id)
        if d is None:
            errors.append(f"{where}: there is no demand with id {lp.demand_id}.")
            continue
        tp = types.get(lp.transponder)
        if tp is None:
            errors.append(f"{where}: unknown transponder type '{lp.transponder}'. Known types: "
                          f"{', '.join(types)}.")
            continue
        path = lp.path
        if len(path) < 2:
            errors.append(f"{where}: the path {path} has less than 2 nodes.")
            continue
        if path[0] != d.origin or path[-1] != d.destination:
            errors.append(f"{where}: the path {lp.path_str()} should go from {d.origin} to "
                          f"{d.destination}.")
        bad_links = [e for e in lp.links if not G.has_edge(*e)]
        for e in bad_links:
            errors.append(f"{where}: the path uses the link {link_label(*e)}, which does not exist "
                          f"(or is down).")
        if bad_links:
            continue
        if len(set(path)) != len(path):
            errors.append(f"{where}: the path {lp.path_str()} visits a node twice (loop).")
            continue

        # ---- 3R ---------------------------------------------------------
        regs = list(lp.regenerators)
        if regs and not regeneration:
            errors.append(f"{where}: uses 3R at {', '.join(map(str, regs))}, but this algorithm is "
                          f"declared without regeneration (REGENERATION = False).")
        inner = path[1:-1]
        if any(r not in inner for r in regs):
            too_long = [(u, v) for u, v in zip(path[:-1], path[1:])
                        if path_length(G, [u, v]) > tp.reach + _EPS]
            why = (f" The link {too_long[0][0]}-{too_long[0][1]} ({path_length(G, list(too_long[0])):g} km) "
                   f"is longer than the reach of {tp.name} ({tp.reach:g} km): no 3R can help, a 3R sits "
                   f"at a node." if too_long else "")
            errors.append(f"{where}: a 3R can only sit at an intermediate node of the path "
                          f"({', '.join(map(str, inner)) or 'none'}), got {regs}.{why}")
            continue
        if len(set(regs)) != len(regs) or regs != sorted(regs, key=inner.index):
            errors.append(f"{where}: the 3R nodes {regs} must be distinct and listed in path order.")
            continue
        segments = lp.segments
        if len(lp.starts) != len(segments):
            errors.append(f"{where}: {len(segments)} segment(s) ({len(regs)} × 3R) but "
                          f"{len(lp.starts)} start slot(s) {lp.starts}: give one start per segment.")
            continue

        # ---- reach, slot range, overlap ---------------------------------
        for seg, start in zip(segments, lp.starts):
            km = path_length(G, seg)
            if km > tp.reach + _EPS:
                seg_txt = " > ".join(map(str, seg))
                longest = max(path_length(G, list(e)) for e in zip(seg[:-1], seg[1:]))
                if longest > tp.reach + _EPS:
                    hint = (f" (a single link of the segment is {longest:g} km: no 3R can help, a 3R "
                            f"sits at a node)" if regeneration else "")
                else:
                    hint = " (put a 3R on the way)" if regeneration else ""
                errors.append(f"{where}: {'segment' if regs else 'path'} {seg_txt} is {km:g} km but "
                              f"the reach of {tp.name} is {tp.reach:g} km{hint}.")
            if start < 0 or start + tp.slots > num_slots:
                errors.append(f"{where}: slots {start}..{start + tp.slots - 1} are outside the band "
                              f"(slots 0..{num_slots - 1}).")
                continue
            for e in zip(seg[:-1], seg[1:]):
                occ = owner.setdefault(e, [None] * num_slots)
                for s in range(start, start + tp.slots):
                    if occ[s] is not None:
                        c = clashes.setdefault(e, [s, set()])
                        c[1].update((occ[s], k))
                    else:
                        occ[s] = k

    for e, (slot, ks) in sorted(clashes.items(), key=lambda t: str(t[0])):
        dems = sorted({solution.lightpaths[i].demand_id for i in ks})
        errors.append(f"Slot {slot} of link {link_label(*e)} is used by {len(ks)} lightpaths "
                      f"(demands {', '.join(map(str, dems))}): two lightpaths cannot share a slot.")

    # ---- demands ---------------------------------------------------------
    for d in demands:
        name = f"Demand {d.id} ({d.origin}->{d.destination}, {d.traffic} Gb/s)"
        work = [lp for lp in solution.lightpaths if lp.demand_id == d.id and not lp.backup]
        back = [lp for lp in solution.lightpaths if lp.demand_id == d.id and lp.backup]
        cap_w = sum(types[lp.transponder].rate for lp in work if lp.transponder in types)
        cap_b = sum(types[lp.transponder].rate for lp in back if lp.transponder in types)
        if not work:
            if back:
                errors.append(f"{name} has backup lightpaths but no working lightpath.")
            elif not allows_blocking:
                errors.append(f"{name} is not served.")
            continue
        if d.id in solution.blocked:
            warnings.append(f"{name} is marked as blocked ({solution.blocked[d.id] or 'no reason'}) "
                            f"but has lightpaths.")
        for role, lps in (("working", work), ("backup", back)):
            kinds = sorted({lp.transponder for lp in lps})
            if len(kinds) > 1:
                errors.append(f"{name}: its {role} lightpaths mix transponder types ({', '.join(kinds)}): "
                              f"every lightpath of a demand must use the same type (same rate, "
                              f"modulation and slots).")
        if cap_w < d.traffic:
            errors.append(f"{name}: its lightpaths carry only {cap_w} Gb/s.")
        elif work and cap_w - min(types[lp.transponder].rate for lp in work
                                  if lp.transponder in types) >= d.traffic:
            warnings.append(f"{name}: {cap_w} Gb/s of lightpaths, one of them could be removed.")
        if protection:
            if cap_b < d.traffic:
                errors.append(f"{name}: 1+1 protection, but its backup lightpaths carry only "
                              f"{cap_b} Gb/s.")
            shared = set()
            for lw in work:
                for lb in back:
                    shared |= path_fibres(lw.path) & path_fibres(lb.path)
            if shared:
                f = sorted(tuple(sorted(map(str, x))) for x in shared)[0]
                errors.append(f"{name}: working and backup paths share the fibre {f[0]}-{f[1]}: "
                              f"one cut would take both down (they must be fibre-disjoint).")
        elif back:
            errors.append(f"{name} has backup lightpaths, but this algorithm is declared without "
                          f"protection (PROTECTION = False).")

    issues = [Issue("error", m) for m in errors] + [Issue("warning", m) for m in warnings]
    if len(issues) > MAX_MESSAGES:
        extra = len(issues) - MAX_MESSAGES
        issues = issues[:MAX_MESSAGES] + [Issue("error" if errors else "warning",
                                                f"... and {extra} more issue(s).")]
    return issues
