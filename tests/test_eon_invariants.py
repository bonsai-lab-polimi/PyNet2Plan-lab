"""Invariants of the EON results (fast): accounting identities, an independent
check of the spectrum, reach and 1+1, common-sense relations (more slots or
reach never serve fewer...), failures, round trip and CLI exit codes."""
import os
import subprocess
import sys

import pytest

from conftest import needs_solutions

from pynet2plan import network, traffic
from pynet2plan.eon import helpers, results as eres, runner, transponders as tpm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(tpm.__file__)))  # .../pynet2plan
ROOT = os.path.dirname(ROOT)
DATA = os.path.join(ROOT, "data")
TABLE = tpm.load_table()
TP = {tp.name: tp for tp in TABLE}
ALGOS = {"rsa": ("rsa_greedy", {}),
         "1p1": ("rsa_1plus1_two_step", {}), "3r": ("solutions/rsa_3r", {})}


@pytest.fixture(scope="module")
def eon6():
    G = network.load_topology(os.path.join(DATA, "topologies", "eon6.json"))
    return G, traffic.load_traffic(os.path.join(DATA, "traffic_eon", "eon6_traffic.csv"), G)


def segs(lp):
    return helpers.segments_of(lp.path, lp.regenerators)


def invariants(res, demands, num_slots=320, table=TABLE):
    s, sol = res.summary, res.solution
    types = {tp.name: tp for tp in table}
    served = {lp.demand_id for lp in sol.lightpaths if not lp.backup}
    assert s["served_demands"] + s["blocked_demands"] == s["num_demands"] == len(demands)
    assert s["carried_gbps"] + s["blocked_gbps"] == s["offered_gbps"] == sum(d.traffic for d in demands)
    assert s["served_demands"] == len(served & {d.id for d in demands})
    # 2 per lightpath, and 2 per 3R (back to back)
    assert s["transponders"] == 2 * (s["lightpaths"] + s["backup_lightpaths"] + s["regenerators"]) \
        == sum(2 + 2 * len(lp.regenerators) for lp in sol.lightpaths)
    assert s["regenerators"] == sum(len(lp.regenerators) for lp in sol.lightpaths)
    assert s["hardware_cost"] == pytest.approx(sum(2 * types[lp.transponder].cost * (1 + len(lp.regenerators))
                                                   for lp in sol.lightpaths))
    assert s["total_slots_used"] == sum(types[lp.transponder].slots * (len(g) - 1)
                                        for lp in sol.lightpaths for g in segs(lp))
    assert 0 <= s["spectrum_utilization"] <= s["max_link_utilization"] <= 1
    assert s["max_slot_index"] <= num_slots
    assert (s["blocked_spectrum"] + s["blocked_reach"] + s["blocked_disjoint"] + s["blocked_other"]
            + s["unreachable_demands"]) == s["blocked_demands"]
    # independent non-overlap / band / reach / capacity
    grid = set()
    Hw = network.working_graph(res_graph(res))
    for lp in sol.lightpaths:
        tp = types[lp.transponder]
        for g, st in zip(segs(lp), lp.starts):
            assert 0 <= st and st + tp.slots <= num_slots
            assert helpers.path_length(Hw, g) <= tp.reach + 1e-6
            for e in zip(g[:-1], g[1:]):
                for x in range(st, st + tp.slots):
                    assert (e, x) not in grid
                    grid.add((e, x))
    for d in demands:
        if d.id in served:
            assert sum(types[lp.transponder].rate for lp in sol.of_demand(d.id, backup=False)) >= d.traffic


_GRAPH = {}


def res_graph(res):
    return _GRAPH[id(res)]


def run(G, D, key, **kw):
    name, params = ALGOS[key]
    res = runner.run_eon(G, D, name, dict(params, **kw.pop("params", {})), save=False, **kw)
    Gn = G.copy()
    network.normalize(Gn)
    _GRAPH[id(res)] = Gn
    return res


@needs_solutions
@pytest.mark.parametrize("key", list(ALGOS))
def test_accounting_invariants_eon6(eon6, key):
    G, D = eon6
    res = run(G, D, key)
    assert res.ok and not [i for i in res.issues if i.severity == "error"]
    invariants(res, D)


@needs_solutions
def test_eon6_reference_values(eon6):
    G, D = eon6
    want = {"rsa": (120, 155, 310, 0, 1768, 45), "1p1": (77, 97, 418, 0, 3344, 0),
            "3r": (120, 152, 326, 11, 1636, 45)}
    for key, w in want.items():
        s = run(G, D, key).summary
        assert (s["served_demands"], s["lightpaths"], s["transponders"], s["regenerators"],
                s["total_slots_used"], s["demands_down_worst_cut"]) == w


@needs_solutions
def test_protection_backup_is_fibre_disjoint_and_survives_every_cut(eon6):
    G, D = eon6
    res = run(G, D, "1p1")
    sol = res.solution
    for i in sol.served_ids():
        w = set().union(*(helpers.path_fibres(lp.path) for lp in sol.of_demand(i, backup=False)))
        b = set().union(*(helpers.path_fibres(lp.path) for lp in sol.of_demand(i, backup=True)))
        assert b and not (w & b)
    assert all(r["demands_down"] == 0 for r in res.tables["cuts"])


@needs_solutions
def test_prefix_consistency(eon6):
    """as_given greedy: the first n demands get exactly the lightpaths they get in the full run."""
    G, D = eon6
    for key in ("rsa", "1p1", "3r"):
        full = run(G, D, key).solution
        part = run(G, D[:50], key).solution
        sig = lambda s, ids: [(l.demand_id, l.path, l.transponder, l.starts, l.backup) for l in s.lightpaths
                              if l.demand_id in ids]
        assert sig(part, set(range(50))) == sig(full, {d.id for d in D[:50]})


@needs_solutions
def test_more_slots_and_more_reach(eon6):
    G, D = eon6
    for key in ("rsa", "3r"):
        served = [run(G, D, key, num_slots=S).summary["served_demands"] for S in (8, 40, 80, 160, 320)]
        assert served == sorted(served)
        b_reach = [run(G, D, key, table=tpm.scale_reach(TABLE, f)).summary["blocked_reach"]
                   for f in (0.1, 0.25, 0.5, 1)]
        assert b_reach == sorted(b_reach, reverse=True)


@needs_solutions
def test_3r_never_blocks_more_for_reach_than_rsa(eon6):
    G, D = eon6
    t = tpm.scale_reach(TABLE, 0.25)
    assert run(G, D, "3r", table=t).summary["blocked_reach"] <= run(G, D, "rsa", table=t).summary["blocked_reach"]


@needs_solutions
def test_failures_and_odd_inputs(eon6):
    G, D = eon6
    H = G.copy()
    for u, v in list(H.edges):
        if "B" in (u, v):
            network.set_link_up(H, u, v, False)
    for key in ALGOS:
        res = run(H, D, key)
        assert res.ok
        assert res.summary["unreachable_demands"] == sum(1 for d in D if "B" in (d.origin, d.destination))
        assert all("B" not in lp.path for lp in res.solution.lightpaths)
        invariants(res, D)
    assert run(G, [], "rsa").status == "FEASIBLE"
    r = run(G, D, "rsa", num_slots=1)
    assert r.summary["served_demands"] == 0 and r.summary["blocked_spectrum"] == len(D)


def test_huge_demand_split_or_blocked(eon6):
    G, D = eon6
    Dm = traffic.Demand
    res = run(G, [Dm(0, "A", "C", 1500), Dm(1, "B", "E", 1)], "rsa")
    assert res.status == "FEASIBLE"
    invariants(res, [Dm(0, "A", "C", 1500), Dm(1, "B", "E", 1)])


def test_too_many_lightpaths_is_not_a_reach_problem(eon6):
    G, _ = eon6
    res = run(G, [traffic.Demand(0, "A", "C", 12800)], "rsa")
    assert res.status == "FEASIBLE" and res.summary["lightpaths"] == 26        # 26 x 500G


@needs_solutions
def test_results_roundtrip(eon6, tmp_path):
    G, D = eon6
    res = runner.run_eon(G, D, "solutions/rsa_3r", save=True, output_root=str(tmp_path))
    run_ = eres.load_run(res.folder)
    t = res.summary["total_slots_used"]
    assert sum(r["slots_used"] for r in run_.links) == t == sum(r["slots"] for r in run_.spectrum)
    assert sum(r["slots_used"] for r in run_.demands_table) == t
    assert run_.summary["served_demands"] == sum(r["state"] == "SERVED" for r in run_.demands_table)


def test_cli_errors_are_clean(tmp_path):
    topo, traf = os.path.join(DATA, "topologies", "eon6.json"), os.path.join(DATA, "traffic_eon", "eon6_traffic.csv")
    for args in (["eon-sweep", "-t", topo, "-d", traf, "-a", "rsa_greedy", "--axis", "num_slots", "--values", "abc"],
                 ["eon-sweep", "-t", topo, "-d", traf, "-a", "rsa_greedy", "--axis", "reach_scale",
                  "--values", "1,0", "-o", str(tmp_path)],
                 ["eon-cost", "--span", "0"], ["eon-cost", "--rate", "0"],
                 ["eon-traffic", "-t", topo, "-o", str(tmp_path)]):
        p = subprocess.run([sys.executable, "-m", "pynet2plan"] + args, cwd=ROOT, capture_output=True, text=True)
        assert p.returncode == 2 and "Traceback" not in p.stderr and p.stderr.startswith("Error:"), args


def test_cli_sweep_exit_code_when_all_runs_fail(tmp_path):
    p = subprocess.run([sys.executable, "-m", "pynet2plan", "eon-sweep", "-t",
                        os.path.join(DATA, "topologies", "eon6.json"), "-d",
                        os.path.join(DATA, "traffic_eon", "eon6_traffic.csv"), "-a", "no_such_algorithm",
                        "-o", str(tmp_path)], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode != 0
