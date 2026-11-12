"""Self-check of the EON exercises:   python -m pytest tests/test_eon_exercises.py -v

The tests of an exercise are SKIPPED while its file still contains
'raise NotCompletedError' lines. Once you have completed it, they check that
your algorithm gives valid results, and the same results as the reference.
"""

import os

import pytest

from pynet2plan import network, traffic
from pynet2plan.eon import runner

from conftest import DATA, FORMULATIONS

D = traffic.Demand
#: the files checked (instructors: tests/test_eon.py runs these checks on solutions/eon/ too)
EXERCISES = os.environ.get("PYNET2PLAN_EON_EXERCISES") or os.path.join(FORMULATIONS, "eon")
ROOT_DIR = os.path.dirname(FORMULATIONS)


def len_km(G, path):
    return sum(G.edges[u, v]["length"] for u, v in zip(path[:-1], path[1:]))


def completed(name):
    path = os.path.join(EXERCISES, f"{name}.py")
    if not os.path.isfile(path):
        pytest.skip(f"eon/{name}.py is not part of this copy yet (it comes with a later lab)")
    info = runner.load_eon_formulation(path)
    assert info.ok, info.error
    if info.todo_count:
        pytest.skip(f"eon/{name}.py is not completed yet ({info.todo_count} TODO left)")
    return path


@pytest.fixture(scope="module")
def eon6():
    G = network.load_topology(os.path.join(DATA, "topologies", "eon6.json"))
    return G, traffic.load_traffic(os.path.join(DATA, "traffic_eon", "eon6_traffic.csv"), G)


def run(alg, G, dem, num_slots=320, **params):
    r = runner.run_eon(G, dem, alg, params, num_slots=num_slots, save=False)
    assert r.status in ("FEASIBLE", "BLOCKING"), f"{r.status} with {params or 'the default parameters'}: {r.message}"
    return r


def check_ok(alg):
    r = runner.check_formulation(alg)
    assert r.ok, f"the Check gives {r.status}: {r.message}"


def test_rsa_3r(eon6):
    alg = completed("rsa_3r")
    mod = runner.load_eon_formulation(alg).module
    G, dem = eon6
    # TODO 1 on EON-6: A-D-E-F-C is 300 + 400 + 800 + 600 km
    adefc = ["A", "D", "E", "F", "C"]
    assert mod.segment_path(G, ["A", "B", "C"], 900) == [["A", "B"], ["B", "C"]], \
        "A-B-C (700 + 500 km), reach 900: a 3R at B"
    assert mod.segment_path(G, ["A", "B", "C"], 1300) == [["A", "B", "C"]], "A-B-C, reach 1300: no 3R"
    assert mod.segment_path(G, ["A", "B", "C"], 1200) == [["A", "B", "C"]], \
        "A-B-C is exactly 1200 km: with a reach of 1200 km no 3R is needed (test acc + link > reach, not >=)"
    assert mod.segment_path(G, ["B", "A", "D", "E"], 800) == [["B", "A"], ["A", "D", "E"]], \
        "B-A-D-E (700 + 300 + 400 km), reach 800: one 3R at A; after it the count restarts (acc = link)"
    assert mod.segment_path(G, adefc, 1000) == [["A", "D", "E"], ["E", "F"], ["F", "C"]], \
        "A-D-E-F-C, reach 1000: 3R at E and F (after a 3R the count restarts with the link: acc = link)"
    assert mod.segment_path(G, adefc, 700) is None, "A-D-E-F-C, reach 700: the link E-F (800 km) is too long"
    # the whole algorithm
    check_ok(alg)
    slide = traffic.load_traffic(os.path.join(DATA, "traffic_eon", "eon6_slide_example.csv"), G)
    cr2 = run(alg, G, slide).tables["lightpaths"][2]
    got = (cr2["transponder"], cr2["regenerators"], cr2["slot_ranges"])
    assert got == ("200G 16QAM", "B", "4-7;12-15"), \
        f"the slide's demand A -> C: 200G 16QAM, 3R at B, slots 4-7 then 12-15 expected, found {got}"
    s = run(alg, G, dem).summary
    got = (s["served_demands"], s["regenerators"], s["total_slots_used"])
    assert got == (120, 11, 1636), f"EON-6: (served, 3R, slots) = (120, 11, 1636) expected, found {got}"
    assert run(alg, G, dem, choose="3R").summary["regenerators"] == 0, "choose='3R': the fewest 3R, here none (a path of one segment needs len(segs) - 1 = 0 3R)"
    ex3 = traffic.load_traffic(os.path.join(DATA, "traffic_eon", "eon6_long_fast.csv"), G)
    s = run(alg, G, ex3).summary
    got = (s["served_demands"], s["regenerators"], s["total_slots_used"])
    assert got == (88, 87, 2864), (
        f"EON-6, 88 long, fast demands (eon6_long_fast.csv): (served, 3R, slots) = (88, 87, 2864) expected, "
        f"found {got}")


def test_rsa_3r_budget(eon6):
    alg = completed("rsa_3r_budget")
    G, dem = eon6
    # without a budget: the cheapest combination of every demand, as rsa_3r with choose="cost"
    # (compared with the reference, or with your rsa_3r.py once completed)
    plain = None
    if os.path.isdir(os.path.join(ROOT_DIR, "solutions", "eon")):
        plain = "solutions/rsa_3r"
    elif os.path.isfile(os.path.join(EXERCISES, "rsa_3r.py")) and \
            not runner.load_eon_formulation(os.path.join(EXERCISES, "rsa_3r.py")).todo_count:
        plain = os.path.join(EXERCISES, "rsa_3r.py")
    if plain:
        free = run(alg, G, dem).summary
        ref = run(plain, G, dem, choose="cost").summary
        for key in ("served_demands", "lightpaths", "regenerators", "transponders", "total_slots_used"):
            assert free[key] == ref[key], f"max_cost=None (no budget): {key} must be the one of rsa_3r with choose='cost'"
    check_ok(alg)
    # the slide's demand A -> C, 200 Gb/s (1200 km): 300G PCS 16QAM without 3R (8 slots, 2 transponders) is
    # cheaper than 200G 16QAM with a 3R at B (4 slots, 2 + 2 transponders)
    ac = [D(0, "A", "C", 200)]
    s = run(alg, G, ac, max_cost=4).summary
    assert (s["served_demands"], s["transponders"], s["regenerators"]) == (1, 2, 0), \
        "budget 4: the cheapest combination, 300G PCS 16QAM without 3R (2 transponders)"
    assert run(alg, G, ac, max_cost=1.5).summary["served_demands"] == 0, "budget 1.5: not even one lightpath"
    # the slide's example: two demands A -> C, budget 4: the long-reach type for both, 2 + 2 transponders
    # (the greedy 3R spends 4 on the first one, the fast type with a 3R, and blocks the second)
    two = [D(0, "A", "C", 200), D(1, "A", "C", 200)]
    s = run(alg, G, two, max_cost=4).summary
    assert (s["served_demands"], s["transponders"]) == (2, 4), "budget 4, two demands A -> C: 2 + 2 transponders"
    if plain:
        r = runner.run_eon(G, two, plain, {}, max_cost=4, num_slots=320, save=False)
        assert (r.summary["served_demands"], r.summary["transponders"]) == (1, 4), "greedy 3R, budget 4: 1 served"
    s = run(alg, G, two, max_cost=6).summary
    assert (s["served_demands"], s["transponders"]) == (2, 4), "budget 6, two demands A -> C: 2 + 2 transponders"
    # Lab 4, example 6 (the example of this exercise): more demands than rsa_3r with the same budget
    S = network.load_topology(os.path.join(DATA, "topologies", "spain7.json"))
    ex6 = traffic.load_traffic(os.path.join(DATA, "traffic_eon", "spain7_lab4_budget.csv"), S)
    for budget, served in ((100, 29), (180, 52), (240, 71), (280, 80)):
        s = run(alg, S, ex6, max_cost=budget).summary
        assert s["hardware_cost"] <= budget, f"budget {budget}: the transponders cost {s['hardware_cost']}"
        assert s["served_demands"] == served, (f"example 6, budget {budget}: {served} demands served expected "
                                               f"(rsa_3r with the same budget: fewer), found {s['served_demands']}")
    if plain:
        assert [runner.run_eon(S, ex6, plain, max_cost=b, save=False).summary["served_demands"]
                for b in (100, 180, 240, 280)] == [26, 45, 61, 72]
