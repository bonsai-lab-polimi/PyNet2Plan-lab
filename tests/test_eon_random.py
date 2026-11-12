"""Randomized tests of the EON part: random networks, random traffic, random
settings; every result is re-checked by an independent, deliberately simple
oracle written here (not the checker of pynet2plan.eon.validation)."""

import math
import random

import pytest

from pynet2plan import network
from pynet2plan.eon import helpers, runner, transponders as tpm
from pynet2plan.eon.solution import EonSolution
from pynet2plan.eon.traffic import random_eon_traffic
from pynet2plan.eon.validation import validate_eon
from pynet2plan.traffic import Demand

from conftest import HAS_SOLUTIONS

TABLE = tpm.load_table()
ALGOS = ["rsa_greedy", "rsa_1plus1_two_step", "rsa_1plus1_ilp"] + (
    ["solutions/rsa_3r"] if HAS_SOLUTIONS else [])


def random_net(seed):
    rnd = random.Random(seed)
    G = network.random_topology(rnd.randint(4, 9), rnd.randint(1, 6), seed=seed)
    for u, v in list(G.edges):
        if u < v:
            km = rnd.choice([50, 100, 150, 300, 400, 600, 800, 1200, 2000])
            G.edges[u, v]["length"] = km
            if G.has_edge(v, u):
                G.edges[v, u]["length"] = km
    return G


def oracle_errors(G, demands, sol, table, num_slots, protection, regeneration):
    """Independent re-check: returns a list of problems (empty = valid)."""
    types = {tp.name: tp for tp in table}
    rate = {d.id: d for d in demands}
    grid = {}
    out = []
    for k, lp in enumerate(sol.lightpaths):
        tp = types.get(lp.transponder)
        d = rate.get(lp.demand_id)
        if tp is None or d is None:
            out.append(f"{k}: unknown type/demand")
            continue
        p = lp.path
        if len(p) < 2 or p[0] != d.origin or p[-1] != d.destination or len(set(p)) != len(p):
            out.append(f"{k}: bad path")
            continue
        if any(not G.has_edge(a, b) for a, b in zip(p, p[1:])):
            out.append(f"{k}: missing link")
            continue
        if lp.regenerators and not regeneration:
            out.append(f"{k}: 3R not allowed")
        cuts = [0] + sorted(p.index(r) for r in lp.regenerators if r in p[1:-1]) + [len(p) - 1]
        if len(cuts) - 2 != len(lp.regenerators) or len(set(lp.regenerators)) != len(lp.regenerators):
            out.append(f"{k}: bad 3R")
            continue
        if sorted(lp.regenerators, key=p.index) != list(lp.regenerators):
            out.append(f"{k}: 3R order")
            continue
        if len(lp.starts) != len(cuts) - 1:
            out.append(f"{k}: starts")
            continue
        for (i, j), s in zip(zip(cuts, cuts[1:]), lp.starts):
            seg = p[i:j + 1]
            km = sum(G.edges[a, b]["length"] for a, b in zip(seg, seg[1:]))
            if km > tp.reach + 1e-6:
                out.append(f"{k}: reach")
            if s < 0 or s + tp.slots > num_slots:
                out.append(f"{k}: band")
                continue
            for a, b in zip(seg, seg[1:]):
                for x in range(s, s + tp.slots):
                    if (a, b, x) in grid:
                        out.append(f"{k}: overlap with {grid[(a, b, x)]}")
                    grid[(a, b, x)] = k
    for d in demands:
        w = [lp for lp in sol.lightpaths if lp.demand_id == d.id and not lp.backup]
        b = [lp for lp in sol.lightpaths if lp.demand_id == d.id and lp.backup]
        if not w:
            if b:
                out.append(f"d{d.id}: backup only")
            continue
        if sum(types[lp.transponder].rate for lp in w if lp.transponder in types) < d.traffic:
            out.append(f"d{d.id}: capacity")
        for group in (w, b):                     # one transponder type per demand (working / backup)
            if len({lp.transponder for lp in group}) > 1:
                out.append(f"d{d.id}: mixed types")
        if protection:
            if sum(types[lp.transponder].rate for lp in b if lp.transponder in types) < d.traffic:
                out.append(f"d{d.id}: backup capacity")
            fw = {frozenset(e) for lp in w for e in zip(lp.path, lp.path[1:])}
            fb = {frozenset(e) for lp in b for e in zip(lp.path, lp.path[1:])}
            if fw & fb:
                out.append(f"d{d.id}: shared fibre")
        elif b:
            out.append(f"d{d.id}: backup without protection")
    return out


@pytest.mark.parametrize("seed", range(12))
def test_random_networks_all_algorithms(seed):
    rnd = random.Random(1000 + seed)
    G = random_net(seed)
    slots = rnd.choice([16, 40, 96, 320])
    table = tpm.scale_reach(TABLE, rnd.choice([0.3, 0.6, 1.0, 1.5]))
    demands = random_eon_traffic(G, rnd.randint(5, 60), tpm.rates(table), seed=seed)
    for alg in ALGOS:
        info = runner.find_eon_formulation(alg)
        params = {"k": rnd.randint(1, 4), "order": rnd.choice(["as_given", "largest_first"])}
        params = {key: v for key, v in params.items() if key in info.parameters}   # each its own parameters
        r = runner.run_eon(G, demands, alg, params, table=table, num_slots=slots, save=False)
        assert r.status in ("FEASIBLE", "BLOCKING"), (alg, r.status, r.message)
        bad = oracle_errors(netw(G), demands, r.solution, table, slots, info.protection, info.regeneration)
        assert bad == [], (alg, bad[:5])
        s = r.summary
        # bookkeeping is consistent
        assert s["served_demands"] + s["blocked_demands"] == len(demands)
        assert s["blocked_demands"] == s["blocked_spectrum"] + s["blocked_reach"] + s["blocked_disjoint"] \
            + s["blocked_other"] + s["unreachable_demands"]
        used = sum(tp.slots * (len(lp.path) - 1) for lp in r.solution.lightpaths
                   for tp in [tpm.by_name(table)[lp.transponder]])
        assert used == s["total_slots_used"]
        assert s["transponders"] == 2 * (s["lightpaths"] + s["backup_lightpaths"] + s["regenerators"])
        assert s["max_slot_index"] <= slots
        if info.protection:
            assert s["demands_down_worst_cut"] == 0
        if not info.regeneration:
            assert s["regenerators"] == 0
        # a blocked demand really has no room: with the same algorithm alone it fits
        # only if the network was empty -> blocking reason "reach" must be confirmed by
        # the table: no type reaches any of its k paths (without 3R)
        for row in r.tables["demands"]:
            if row["reason"] == "reach" and not info.regeneration and "k" in params:
                d = next(x for x in demands if x.id == row["demand_id"])
                paths = helpers.k_shortest_paths(netw(G), d.origin, d.destination, params["k"])
                if not info.protection:
                    assert all(helpers.best_combination(
                        [(tp, 0) for tp in helpers.types_reaching(table, helpers.path_length(G, p))],
                        d.traffic) is None for p in paths)


def netw(G):
    return network.working_graph(G)


def test_more_slots_never_serve_fewer_in_isolation():
    """One demand alone: if it fits with S slots it fits with 2S (monotonicity sanity check)."""
    G = random_net(3)
    for d in random_eon_traffic(G, 25, tpm.rates(TABLE), seed=9):
        a = runner.run_eon(G, [d], "rsa_greedy", num_slots=8, save=False).summary["served_demands"]
        b = runner.run_eon(G, [d], "rsa_greedy", num_slots=16, save=False).summary["served_demands"]
        assert b >= a


@pytest.mark.parametrize("seed", range(6))
def test_checker_agrees_with_oracle_on_mutations(seed):
    """Take valid solutions, mutate them at random: the checker and the oracle must agree."""
    rnd = random.Random(seed)
    G = random_net(20 + seed)
    H = netw(G)
    demands = random_eon_traffic(G, 25, tpm.rates(TABLE), seed=seed)
    for alg, prot, regen in (("rsa_greedy", False, False),) + (
            (("rsa_1plus1_two_step", True, False), ("solutions/rsa_3r", False, True)) if HAS_SOLUTIONS else ()):
        base = runner.run_eon(G, demands, alg, num_slots=48, save=False).solution
        if not base.lightpaths:
            continue
        for trial in range(40):
            sol = EonSolution.from_dict(base.to_dict())
            lp = rnd.choice(sol.lightpaths)
            what = rnd.randrange(7)
            if what == 0:
                lp.starts = [s + rnd.choice([-3, -1, 1, 2, 5]) for s in lp.starts]
            elif what == 1:
                lp.transponder = rnd.choice(TABLE).name
            elif what == 2 and len(lp.path) > 2:
                lp.regenerators = [rnd.choice(lp.path[1:-1])]
                lp.starts = lp.starts[:1] * 2
            elif what == 3:
                lp.backup = not lp.backup
            elif what == 4:
                other = rnd.choice(sol.lightpaths)
                lp.starts = list(other.starts[:1]) * len(lp.starts)
            elif what == 5:
                sol.lightpaths.remove(lp)
            else:
                lp.starts = [rnd.randrange(0, 60) for _ in lp.starts]
            mine = [i for i in validate_eon(H, demands, sol, TABLE, 48, protection=prot, regeneration=regen)
                    if i.severity == "error"]
            ref = oracle_errors(H, demands, sol, TABLE, 48, prot, regen)
            assert bool(mine) == bool(ref), (alg, what, [i.message for i in mine][:3], ref[:3])


def test_traffic_generator_statistics():
    G = random_net(5)
    rates = [100, 200, 400, 800]
    dem = random_eon_traffic(G, 8000, rates, seed=123)
    counts = {r: sum(1 for d in dem if d.traffic == r) for r in rates}
    expected = len(dem) / len(rates)
    chi2 = sum((c - expected) ** 2 / expected for c in counts.values())
    assert chi2 < 16.3                                      # 3 dof, p = 0.001
    nodes = list(G.nodes)
    pairs = {}
    for d in dem:
        pairs[(d.origin, d.destination)] = pairs.get((d.origin, d.destination), 0) + 1
    n_pairs = len(nodes) * (len(nodes) - 1)
    assert len(pairs) == n_pairs                            # every ordered pair appears
    exp = len(dem) / n_pairs
    chi2 = sum((c - exp) ** 2 / exp for c in pairs.values())
    dof = n_pairs - 1
    assert chi2 < dof + 4 * math.sqrt(2 * dof)              # ~ uniform over the ordered pairs
    origins = {n: sum(1 for d in dem if d.origin == n) for n in nodes}
    assert max(origins.values()) / min(origins.values()) < 1.25
    assert len({d.id for d in dem}) == len(dem)


def test_unidirectional_links_and_isolated_demands():
    G = network.new_network("one way")
    for n, x in zip("ABCD", range(4)):
        network.add_node(G, n, x=100 * x, y=0)
    network.add_link(G, "A", "B", length=300)
    network.add_link(G, "B", "C", length=300)
    network.add_link(G, "C", "A", length=300)               # a one-way ring, D isolated
    dem = [Demand(0, "A", "C", 400), Demand(1, "C", "B", 400), Demand(2, "A", "D", 100)]
    r = runner.run_eon(G, dem, "rsa_greedy", save=False)
    assert r.status == "BLOCKING" and r.summary["unreachable_demands"] == 1
    paths = {row["demand_id"]: row["path"] for row in r.tables["demands"]}
    assert paths[0] == "A > B > C" and paths[1] == "C > A > B"
    if HAS_SOLUTIONS:
        p = runner.run_eon(G, dem[:2], "rsa_1plus1_two_step", save=False)
        assert p.summary["served_demands"] == 0 and p.summary["blocked_disjoint"] == 2
