"""The teaching examples of the EON window, on Spain-7 (data/traffic_eon/spain7_lab4_*.csv,
spain7_first_plan.csv), still show what they are made for."""
import os

import pytest

from conftest import DATA, needs_solutions
from pynet2plan import network, traffic
from pynet2plan.eon import runner

pytestmark = needs_solutions


@pytest.fixture(scope="module")
def spain():
    return network.load_topology(os.path.join(DATA, "topologies", "spain7.json"))


def runs(G, name):
    D = traffic.load_traffic(os.path.join(DATA, "traffic_eon", name), G)
    return D, {a: runner.run_eon(G, D, alg, save=False).summary
               for a, alg in (("rsa", "rsa_greedy"), ("1p1", "rsa_1plus1_two_step"), ("3r", "solutions/rsa_3r"))}


def test_example_files_are_reproducible(spain):
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(DATA), "tools"))
    import build_eon_data as b
    for which, fname in b.EXAMPLE_FILES.items():
        assert b.example_demands(spain, which) == traffic.load_traffic(os.path.join(DATA, "traffic_eon", fname), spain)


def test_lab4_example1_rsa_basics(spain):
    D, r = runs(spain, "spain7_first_plan.csv")
    res = runner.run_eon(spain, D, "rsa_greedy", save=False)
    assert r["rsa"]["served_demands"] == len(D) == 30
    # every type that reaches a link of Spain-7 (800G PCS 64QAM and 300G 64QAM reach 150 / 100 km)
    assert len({lp.transponder for lp in res.solution.lightpaths}) == 7


def test_lab3_example1_no_protection_vs_protection(spain):
    D, r = runs(spain, "spain7_lab4_protection.csv")
    a, b = r["rsa"], r["1p1"]
    assert a["served_demands"] == b["served_demands"] == len(D) == 40
    assert b["transponders"] > 2 * a["transponders"] and b["total_slots_used"] > 2.5 * a["total_slots_used"]
    assert a["demands_down_worst_cut"] == 17 and b["demands_down_worst_cut"] == 0
    two = runner.run_eon(spain, D, "rsa_1plus1_two_step", save=False).summary
    assert two["served_demands"] == 40                  # on Spain-7 the two-step method has no trap


def test_lab4_example2_no_3r_vs_3r(spain):
    D, r = runs(spain, "spain7_lab4_3r.csv")
    a, c = r["rsa"], r["3r"]
    assert (a["served_demands"], c["served_demands"]) == (93, 100) and a["blocked_spectrum"] == 7
    assert c["total_slots_used"] < a["total_slots_used"] and c["regenerators"] == 63
    assert c["hardware_cost"] > a["hardware_cost"]


def test_lab3_example3_one_demand(spain):
    """One demand: one lightpath without protection, a backup path that needs two; the cut of
    Madrid-Valencia takes it down without protection, and switches it to its backup with 1+1."""
    path = os.path.join(DATA, "traffic_eon", "spain7_lab4_one_demand.csv")
    D = traffic.load_traffic(path, spain)
    assert [(d.origin, d.destination, d.traffic) for d in D] == [("Madrid", "Valencia", 700)]
    assert "# cut fibre: Madrid-Valencia\n" in open(path, encoding="utf-8").read()
    H = spain.copy()
    H.graph["cut_after_planning"] = ("Madrid", "Valencia")
    g = runner.run_eon(H, D, "rsa_greedy", save=False).summary
    p = runner.run_eon(H, D, "rsa_1plus1_two_step", save=False).summary
    assert (g["demands_down_cut"], g["served_after_cut"]) == (1, 0)
    assert (p["demands_down_cut"], p["demands_switched_cut"], p["served_after_cut"]) == (0, 1, 1)
    a = runner.run_eon(spain, D, "rsa_greedy", save=False).solution.lightpaths
    b = runner.run_eon(spain, D, "rsa_1plus1_two_step", save=False).solution.lightpaths
    assert [(lp.transponder, lp.path) for lp in a] == [("700G PCS 64QAM", ["Madrid", "Valencia"])]
    backup = [lp for lp in b if lp.backup]
    assert [lp.transponder for lp in backup] == ["400G PCS 16QAM"] * 2
    assert backup[0].path == ["Madrid", "Zaragoza", "Barcelona", "Valencia"] and len(b) == 3


def test_lab3_example2_protection_heuristics_vs_ilp(spain):
    """With 1200 GHz per link the route formulation serves more of the 40 demands than the heuristic;
    with 4000 GHz the three give the same plan."""
    D = traffic.load_traffic(os.path.join(DATA, "traffic_eon", "spain7_lab4_ilp.csv"), spain)
    served = {alg: runner.run_eon(spain, D, alg, save=False, num_slots=96).summary["served_demands"]
              for alg in ("rsa_greedy", "rsa_1plus1_two_step", "rsa_1plus1_ilp")}
    assert served == {"rsa_greedy": 40, "rsa_1plus1_two_step": 25, "rsa_1plus1_ilp": 29}
    full = {alg: runner.run_eon(spain, D, alg, save=False).summary for alg in ("rsa_1plus1_two_step", "rsa_1plus1_ilp")}
    assert all(s["served_demands"] == 40 for s in full.values())
    assert full["rsa_1plus1_ilp"]["total_slots_used"] == full["rsa_1plus1_two_step"]["total_slots_used"]


def test_example2_cut_after_planning_in_runs_and_sweeps(spain, tmp_path):
    """The cut after planning travels with the network: summary and sweep rows count what is
    left; RSA loses demands, 1+1 none."""
    D = traffic.load_traffic(os.path.join(DATA, "traffic_eon", "spain7_lab4_protection.csv"), spain)
    G = spain.copy()
    G.graph["cut_after_planning"] = ("Murcia", "Valencia")
    assert network.topology_from_dict(network.topology_to_dict(G)).graph["cut_after_planning"] == (
        "Murcia", "Valencia")
    a = runner.run_eon(G, D, "rsa_greedy", save=False).summary
    b = runner.run_eon(G, D, "rsa_1plus1_two_step", save=False).summary
    assert (a["cut_fibre"], a["demands_down_cut"], a["served_after_cut"]) == ("Murcia-Valencia", 17, 23)
    assert (b["demands_down_cut"], b["demands_switched_cut"], b["served_after_cut"]) == (0, 17, 40)
    sw = runner.run_eon_sweep(G, D, [("rsa_greedy", {}), ("rsa_1plus1_two_step", {})], "num_demands",
                              [10, 40], output_root=str(tmp_path))
    after = sorted(int(r["served_after_cut"]) for r in sw.rows)
    assert after[-2:] == [23, 40]                                       # the 40 demands: 23 without, 40 with 1+1
    from pynet2plan.eon import results as eres
    loaded = eres.load_sweep(sw.folder)
    assert eres.load_run(loaded.run_folder(loaded.rows[0])).G.graph["cut_after_planning"] == ("Murcia", "Valencia")
