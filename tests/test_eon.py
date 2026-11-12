"""Tests of the EON part (pynet2plan.eon): transponders, traffic, helpers, checker,
runner, results, analysis. The algorithms used here are the given rsa_greedy and,
when solutions/ is present, the reference solutions of the EON exercises."""

import os

import networkx as nx
import numpy as np
import pytest

from pynet2plan import network, traffic
from pynet2plan.errors import TrafficError
from pynet2plan.eon import analysis, helpers, results as eres, runner, transponders as tpm
from pynet2plan.eon import traffic as etraffic
from pynet2plan.eon.solution import EonSolution
from pynet2plan.eon.validation import validate_eon

from conftest import DATA, needs_solutions

D = traffic.Demand
TABLE = tpm.load_table()
TP = tpm.by_name(TABLE)


@pytest.fixture(scope="module")
def eon6():
    return network.load_topology(os.path.join(DATA, "topologies", "eon6.json"))


@pytest.fixture(scope="module")
def eon6_demands(eon6):
    return traffic.load_traffic(os.path.join(DATA, "traffic_eon", "eon6_traffic.csv"), eon6)


def ready(G, slots=320, table=None):
    H = G.copy()
    helpers.setup(H, table or TABLE, slots)
    return H


def lp_rows(res):
    return [(r["demand_id"], r["role"], r["transponder"], r["path"], r["regenerators"], r["slot_ranges"])
            for r in res.tables["lightpaths"]]


# ======================================================================
# transponder table
# ======================================================================
def test_default_table_is_the_slide():
    assert len(TABLE) == 9
    assert [tp.rate for tp in TABLE] == [800, 700, 600, 500, 400, 300, 300, 200, 100]
    assert TP["300G 64QAM"].slots == 4 and TP["300G PCS 16QAM"].slots == 8
    assert TP["200G 16QAM"].reach == 900 and TP["100G QPSK"].reach == 3000
    assert all(tp.cost == 1 for tp in TABLE)
    assert tpm.rates(TABLE) == [100, 200, 300, 400, 500, 600, 700, 800]
    assert TP["600G 16QAM"].gbps_per_slot == 75


def test_slots_and_grids():
    assert tpm.n_slots(50) == 4 and tpm.n_slots(100) == 8 and tpm.n_slots(37.5) == 3
    assert tpm.n_slots(40) == 4                        # always rounded up
    fixed = tpm.with_slot_width(TABLE, 50)
    assert {tp.name: tp.slots for tp in fixed}["100G QPSK"] == 1
    assert tpm.load_table(slot_width=50)[0].slots == 2


def test_table_parse_save_roundtrip(tmp_path):
    text = ("# comment\nrate_gbps;modulation;spacing_ghz;reach_km\n100;QPSK;37,5;3000\n"
            "400;PCS 16QAM;75;2000\n")
    t = tpm.parse_table(text)
    assert [tp.slots for tp in t] == [3, 6] and t[0].cost == 1.0 and t[0].bits_per_symbol == 0
    p = tmp_path / "t.csv"
    tpm.save_table(TABLE, str(p), comments=["x"])
    assert tpm.load_table(str(p)) == TABLE


@pytest.mark.parametrize("text, msg", [
    ("rate_gbps,modulation,spacing_ghz\n100,QPSK,50\n", "reach"),
    ("rate_gbps,modulation,spacing_ghz,reach_km\n100,QPSK,50,3000\n100,QPSK,50,2000\n", "two rows"),
    ("rate_gbps,modulation,spacing_ghz,reach_km\n100,QPSK,-50,3000\n", "invalid"),
    ("rate_gbps,modulation,spacing_ghz,reach_km\n100.5,QPSK,50,3000\n", "whole"),
    ("rate_gbps,modulation,spacing_ghz,reach_km\nabc,QPSK,50,3000\n", "not a number"),
    ("# only a comment\n", "no data"),
])
def test_table_errors(text, msg):
    with pytest.raises(tpm.TransponderError, match=msg):
        tpm.parse_table(text)


def test_scale_reach_does_not_modify_the_table():
    half = tpm.scale_reach(TABLE, 0.5)
    assert half[0].reach == 75 and TABLE[0].reach == 150
    with pytest.raises(tpm.TransponderError):
        tpm.scale_reach(TABLE, 0)


# ======================================================================
# traffic generation
# ======================================================================
def notebook_make_demands(G, n_demands, rates, rng):
    """Verbatim logic of make_demands() of the EON notebook."""
    nodes = list(G.nodes())
    out = []
    for i in range(n_demands):
        s, t = rng.choice(len(nodes), size=2, replace=False)
        out.append({"id": i, "src": nodes[s], "dst": nodes[t], "rate": int(rng.choice(rates))})
    return out


def test_random_traffic_is_the_notebook_one(eon6):
    rates = tpm.rates(TABLE)
    nb = notebook_make_demands(eon6, 120, rates, np.random.default_rng(42))
    ours = etraffic.random_eon_traffic(eon6, 120, rates, seed=42)
    assert [(d.id, d.origin, d.destination, d.traffic) for d in ours] == \
           [(x["id"], x["src"], x["dst"], x["rate"]) for x in nb]


def test_random_traffic_properties(eon6):
    rates = [100, 400, 800]
    a = etraffic.random_eon_traffic(eon6, 200, rates, seed=7)
    assert a == etraffic.random_eon_traffic(eon6, 200, rates, seed=7)        # repeatable
    assert a != etraffic.random_eon_traffic(eon6, 200, rates, seed=8)
    assert len(a) == 200 and [d.id for d in a] == list(range(200))
    assert all(d.origin != d.destination and d.traffic in rates for d in a)
    assert set(etraffic.by_rate(a)) == set(rates)
    assert not traffic.validate_traffic(a, eon6)
    # the first n demands do not depend on how many are drawn (used by the load sweeps)
    assert etraffic.random_eon_traffic(eon6, 50, rates, seed=7) == a[:50]


def test_random_traffic_without_duplicates(eon6):
    a = etraffic.random_eon_traffic(eon6, 100, [100], seed=1, allow_duplicate_pairs=False)
    assert len(a) == 30                                                       # 6 x 5 ordered pairs
    assert len({(d.origin, d.destination) for d in a}) == 30
    b = etraffic.random_eon_traffic(eon6, 10, [100], seed=1, allow_duplicate_pairs=False)
    assert len({(d.origin, d.destination) for d in b}) == 10


def test_full_mesh(eon6):
    m = etraffic.full_mesh_eon_traffic(eon6, [200, 300], seed=3)
    assert len(m) == 30 and len({(d.origin, d.destination) for d in m}) == 30
    assert m == etraffic.full_mesh_eon_traffic(eon6, [200, 300], seed=3)


@pytest.mark.parametrize("kwargs", [dict(num_demands=5, rates=[]), dict(num_demands=5, rates=[0, 100]),
                                    dict(num_demands=-1, rates=[100])])
def test_random_traffic_errors(eon6, kwargs):
    with pytest.raises(TrafficError):
        etraffic.random_eon_traffic(eon6, **kwargs)
    G = network.new_network()
    network.add_node(G, "A", x=0, y=0)
    with pytest.raises(TrafficError):
        etraffic.random_eon_traffic(G, 3, [100])


def test_traffic_csv_roundtrip(eon6, tmp_path):
    a = etraffic.random_eon_traffic(eon6, 40, tpm.rates(TABLE), seed=5)
    p = tmp_path / "t.csv"
    traffic.save_traffic(a, str(p), comments=[etraffic.generation_comment("random_eon_traffic", seed=5)])
    assert traffic.load_traffic(str(p), eon6) == a


def test_data_files(eon6, eon6_demands):
    assert eon6.number_of_nodes() == 6 and eon6.number_of_edges() == 14
    assert eon6.edges["A", "B"]["length"] == 700 and eon6.edges["C", "B"]["length"] == 500
    assert eon6_demands == etraffic.random_eon_traffic(eon6, 120, tpm.rates(TABLE), seed=42)
    for topo, tr in (("nsfnet14", "nsfnet14_eon_traffic"), ("italy10", "italy10_eon_traffic")):
        G = network.load_topology(os.path.join(DATA, "topologies", f"{topo}.json"))
        dem = traffic.load_traffic(os.path.join(DATA, "traffic_eon", f"{tr}.csv"), G)
        assert len(dem) == 150 and {d.traffic for d in dem} <= set(tpm.rates(TABLE))


def test_every_topology_has_eon_traffic():
    """data/traffic_eon/ has Gb/s traffic for every topology; data/traffic/ only wavelengths."""
    import glob
    topos = glob.glob(os.path.join(DATA, "topologies", "*.json")) + \
        glob.glob(os.path.join(DATA, "topologies", "real", "*.json"))
    assert len(topos) > 100
    for t in topos:
        stem = os.path.splitext(os.path.basename(t))[0]
        f = etraffic.find_traffic_for(t, os.path.join(DATA, "traffic_eon"), ("_eon_traffic", "_traffic"))
        assert f, stem
        dem = traffic.load_traffic(f, network.load_topology(t))
        assert len(dem) >= 120 and {d.traffic for d in dem} <= set(tpm.rates(TABLE)), stem
    for f in glob.glob(os.path.join(DATA, "traffic", "**", "*.csv"), recursive=True):
        assert max(d.traffic for d in traffic.load_traffic(f)) < 100, f


# ======================================================================
# helpers
# ======================================================================
@pytest.mark.parametrize("km, rate, expected, slots", [
    (1200, 500, ["500G PCS 16QAM"], 8),
    (1200, 600, ["300G PCS 16QAM", "300G PCS 16QAM"], 16),   # one type per demand: not 500G + 100G
    (1200, 200, ["300G PCS 16QAM"], 8),                      # the slide's red X, without 3R
    (500, 800, ["400G PCS 16QAM", "400G PCS 16QAM"], 16),
    (1000, 800, ["400G PCS 16QAM", "400G PCS 16QAM"], 16),
    (1500, 800, ["400G PCS 16QAM", "400G PCS 16QAM"], 16),
    (2500, 600, ["300G PCS 16QAM", "300G PCS 16QAM"], 16),
    (100, 300, ["300G 64QAM"], 4),
    (5000, 100, None, None),
])
def test_best_combination(km, rate, expected, slots):
    combo = helpers.best_combination([(tp, 0) for tp in helpers.types_reaching(TABLE, km)], rate)
    if expected is None:
        assert combo is None
        return
    names = [tp.name for tp, _ in combo]
    assert names == expected
    assert sum(tp.slots for tp, _ in combo) == slots


def test_best_combination_orders():
    # 200 Gb/s on 1200 km: 300G PCS 16QAM without 3R, or 200G 16QAM with 1 x 3R
    cand = [(TP["300G PCS 16QAM"], 0), (TP["200G 16QAM"], 1), (TP["100G QPSK"], 0)]
    assert helpers.best_combination(cand, 200, "slots") == [(TP["200G 16QAM"], 1)]
    assert helpers.best_combination(cand, 200, "3R") == [(TP["300G PCS 16QAM"], 0)]
    assert helpers.best_combination(cand, 200, "cost") == [(TP["300G PCS 16QAM"], 0)]
    assert helpers.best_combination([], 200) is None
    with pytest.raises(ValueError):
        helpers.best_combination(cand, 200, "fastest")


def test_best_combination_minimal():
    for rate in (100, 300, 700, 1200):
        combo = helpers.best_combination([(tp, 0) for tp in TABLE], rate)
        cap = sum(tp.rate for tp, _ in combo)
        assert cap >= rate and cap - min(tp.rate for tp, _ in combo) < rate


def test_paths_and_fibres(eon6):
    p = helpers.k_shortest_paths(eon6, "C", "D", 3)
    assert p == [["C", "B", "E", "D"], ["C", "B", "A", "D"], ["C", "F", "E", "D"]]
    assert [helpers.path_length(eon6, x) for x in p] == [1000, 1500, 1800]
    assert helpers.fibre("A", "B") == helpers.fibre("B", "A")
    assert helpers.path_fibres(["A", "B", "C"]) == {frozenset("AB"), frozenset("BC")}
    assert helpers.segments_of(["A", "B", "C", "D"], ["C"]) == [["A", "B", "C"], ["C", "D"]]
    assert helpers.segments_of(["A", "B", "C"], []) == [["A", "B", "C"]]
    assert helpers.segments_of(["A", "B", "C", "D"], ["B", "C"]) == [["A", "B"], ["B", "C"], ["C", "D"]]


def test_spectrum_first_fit_notebook_toy(eon6):
    sp = helpers.Spectrum(ready(eon6))
    sp.used[("A", "B")][[0, 1, 2, 3, 8, 9, 10, 11, 16, 17]] = True
    sp.used[("B", "C")][[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19]] = True
    assert sp.first_fit(["A", "B"], 4) == 4
    assert sp.first_fit(["A", "B", "C"], 4) == 12          # 4..7 is taken on B-C
    assert sp.first_fit(["C", "B"], 4) == 0                # the opposite direction is free
    assert sp.is_free(["A", "B", "C"], 12, 4) and not sp.is_free(["A", "B", "C"], 10, 4)
    assert not sp.is_free(["A", "B"], 318, 4)              # outside the band


def test_spectrum_bookkeeping(eon6):
    sp = helpers.Spectrum(ready(eon6, slots=16))
    assert sp.num_slots == 16 and sp.max_slot_index() == 0
    sp.occupy(["A", "B", "C"], 2, 4)
    cp = sp.copy()
    cp.occupy(["A", "B"], 6, 8)
    assert sp.total_slots_used() == 8 and cp.total_slots_used() == 16
    assert sp.max_slot_index() == 6 and cp.max_slot_index() == 14
    assert cp.first_fit(["A", "B"], 4) is None             # 0-1 and 14-15 too small
    sp.release(["A", "B", "C"], 2, 4)
    assert sp.total_slots_used() == 0
    assert helpers.num_slots(ready(eon6, 77)) == 77 and helpers.transponder_table(eon6) == TABLE


# ======================================================================
# the checker
# ======================================================================
def check(G, demands, sol, slots=320, **flags):
    return [i.message for i in validate_eon(G, demands, sol, TABLE, slots, **flags) if i.severity == "error"]


def test_checker_accepts_a_valid_solution(eon6):
    dem = [D(0, "A", "C", 600), D(1, "A", "C", 200)]
    sol = EonSolution()
    sol.add_lightpath(0, ["A", "B", "C"], "300G PCS 16QAM", 0)
    sol.add_lightpath(0, ["A", "B", "C"], TP["300G PCS 16QAM"], 8)
    sol.add_lightpath(1, ["A", "B", "C"], "200G 16QAM", [16, 20], regenerators=["B"])
    assert check(eon6, dem, sol, regeneration=True) == []
    mixed = EonSolution()                                  # 500G + 100G: two types for one demand
    mixed.add_lightpath(0, ["A", "B", "C"], "500G PCS 16QAM", 0)
    mixed.add_lightpath(0, ["A", "B", "C"], TP["100G QPSK"], 8)
    assert any("mix transponder types" in m for m in check(eon6, dem[:1], mixed))


@pytest.mark.parametrize("build, flags, needle", [
    (lambda s: s.add_lightpath(0, ["A", "B", "C"], "600G 16QAM", 0), {}, "reach of 600G 16QAM is 700"),
    (lambda s: s.add_lightpath(0, ["A", "B", "C"], "800G XYZ", 0), {}, "unknown transponder"),
    (lambda s: s.add_lightpath(0, ["A", "D", "C"], "400G PCS 16QAM", 0), {}, "does not exist"),
    (lambda s: s.add_lightpath(0, ["A", "B"], "400G PCS 16QAM", 0), {}, "should go from A to C"),
    (lambda s: s.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", 316), {}, "outside the band"),
    (lambda s: s.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", -1), {}, "outside the band"),
    (lambda s: s.add_lightpath(0, ["A", "B", "C"], "100G QPSK", 0), {}, "carry only 100"),
    (lambda s: s.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", [0, 8], ["B"]), {}, "REGENERATION = False"),
    (lambda s: s.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", [0, 8], ["A"]),
     dict(regeneration=True), "intermediate node"),
    (lambda s: s.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", [0], ["B"]),
     dict(regeneration=True), "one start per segment"),
    (lambda s: s.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", 0, backup=True), {}, "no working"),
    (lambda s: (s.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", 0),
                s.add_lightpath(0, ["A", "D", "E", "F", "C"], "400G PCS 16QAM", 0, backup=True)),
     {}, "PROTECTION = False"),
    (lambda s: s.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", 0), dict(protection=True), "backup"),
    (lambda s: (s.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", 0),
                s.add_lightpath(0, ["A", "D", "E", "B", "C"], "400G PCS 16QAM", 8, backup=True)),
     dict(protection=True), "share the fibre B-C"),
    (lambda s: (s.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", 0),
                s.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", 4)), {}, "two lightpaths cannot share"),
    (lambda s: s.add_lightpath(0, ["A", "B", "A", "B", "C"], "400G PCS 16QAM", 0), {}, "loop"),
])
def test_checker_finds_mistakes(eon6, build, flags, needle):
    sol = EonSolution()
    build(sol)
    errs = check(eon6, [D(0, "A", "C", 400)], sol, **flags)
    assert any(needle in e for e in errs), errs


def test_checker_reverse_direction_and_loops():
    G = network.new_network("ring")
    for n, x in zip("ABCD", (0, 1, 2, 3)):
        network.add_node(G, n, x=x, y=x % 2)
    for u, v in ("AB", "BC", "CD", "DA", "AC"):
        network.add_link(G, u, v, length=100, bidirectional=True)
    dem = [D(0, "A", "C", 400)]
    sol = EonSolution()
    sol.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", 0)
    sol.add_lightpath(0, ["A", "D", "C", "B", "A", "C"], "400G PCS 16QAM", 0, backup=True)
    errs = check(G, dem, sol, protection=True)
    assert any("loop" in e for e in errs)
    # the opposite direction of a working link is the SAME fibre
    sol = EonSolution()
    sol.add_lightpath(0, ["A", "C"], "400G PCS 16QAM", 0)
    sol.add_lightpath(1, ["C", "A"], "400G PCS 16QAM", 0)              # other demand, other direction: ok
    assert check(G, [D(0, "A", "C", 400), D(1, "C", "A", 400)], sol) == []


def test_checker_warnings(eon6):
    sol = EonSolution()
    sol.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", 0)
    sol.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", 8)
    sol.block(0, "spectrum")
    issues = validate_eon(eon6, [D(0, "A", "C", 400)], sol, TABLE, 320)
    assert not [i for i in issues if i.severity == "error"]
    w = " ".join(i.message for i in issues)
    assert "could be removed" in w and "marked as blocked" in w
    assert check(eon6, [D(0, "A", "C", 400)], EonSolution(), allows_blocking=False)


def test_solution_api_errors():
    sol = EonSolution()
    with pytest.raises(TypeError):
        sol.add_lightpath(0, ["A", "B"], 123, 0)
    with pytest.raises(TypeError):
        sol.add_lightpath(0, ["A", "B"], "100G QPSK", None)
    with pytest.raises(TypeError):
        sol.add_lightpath("x", ["A", "B"], "100G QPSK", 0)
    sol.add_lightpath(D(4, "A", "B", 100), ["A", "B"], "100G QPSK", 3)
    back = EonSolution.from_dict(sol.to_dict())
    assert back.lightpaths == sol.lightpaths and sol.served_ids() == {4}


# ======================================================================
# runner: the slide's examples, exactly
# ======================================================================
def test_slide_example_rsa(eon6):
    dem = traffic.load_traffic(os.path.join(DATA, "traffic_eon", "eon6_slide_example.csv"), eon6)
    r = runner.run_eon(eon6, dem, "rsa_greedy", save=False)
    assert r.status == "FEASIBLE", r.message
    assert lp_rows(r) == [(1, "working", "100G QPSK", "A > B > C", "", "0-3"),
                          (3, "working", "600G 16QAM", "B > C", "", "4-11"),
                          (2, "working", "300G PCS 16QAM", "A > B > C", "", "12-19")]


@needs_solutions
def test_slide_example_3r(eon6):
    dem = traffic.load_traffic(os.path.join(DATA, "traffic_eon", "eon6_slide_example.csv"), eon6)
    r = runner.run_eon(eon6, dem, "solutions/rsa_3r", save=False)
    assert r.status == "FEASIBLE", r.message
    # CR2: 200G 16QAM with a 3R at B, on DIFFERENT slots on A-B and B-C
    assert lp_rows(r)[2] == (2, "working", "200G 16QAM", "A > B > C", "B", "4-7;12-15")
    assert r.summary["regenerators"] == 1 and r.summary["total_slots_used"] == 8 + 8 + 8


def test_c_to_d_protection(eon6):
    """The trap of the two-step method; the route formulation (ILP) finds the disjoint pair."""
    dem = [D(0, "C", "D", 500)]
    a = runner.run_eon(eon6, dem, "rsa_greedy", save=False)
    assert runner.run_eon(eon6, dem, "rsa_1plus1_two_step", save=False).status == "BLOCKING"
    p = runner.run_eon(eon6, dem, "rsa_1plus1_ilp", save=False)
    assert (a.summary["total_slots_used"], a.summary["transponders"]) == (24, 2)
    assert (p.summary["total_slots_used"], p.summary["transponders"]) == (96, 8)
    assert {r["path"] for r in p.tables["lightpaths"]} == {"C > B > A > D", "C > F > E > D"}
    assert p.summary["demands_down_worst_cut"] == 0 and a.summary["demands_down_worst_cut"] == 1
    # with k=1 the only candidate (C-B-E-D) has no backup path: the trap
    k1 = runner.run_eon(eon6, dem, "rsa_1plus1_ilp", {"k": 1}, save=False)
    assert k1.status == "BLOCKING" and k1.tables["demands"][0]["reason"] == "no disjoint path"
    assert k1.summary["blocked_disjoint"] == 1


def test_reach_blocking_and_unreachable(eon6):
    short = tpm.scale_reach(TABLE, 0.1)                 # 100G QPSK reaches 300 km
    r = runner.run_eon(eon6, [D(0, "A", "C", 100), D(1, "B", "E", 100)], "rsa_greedy", table=short,
                       save=False)
    assert r.status == "BLOCKING"
    assert [x["state"] for x in r.tables["demands"]] == ["BLOCKED", "SERVED"]
    assert r.tables["demands"][0]["reason"] == "reach" and r.summary["blocked_reach"] == 1
    G = eon6.copy()
    network.set_node_up(G, "C", False)
    r = runner.run_eon(G, [D(0, "A", "C", 100), D(1, "A", "B", 100)], "rsa_greedy", save=False)
    assert r.status == "BLOCKING" and r.summary["unreachable_demands"] == 1
    assert r.tables["demands"][0]["state"] == "UNREACHABLE"


def test_spectrum_blocking(eon6):
    dem = [D(i, "B", "E", 800) for i in range(5)]       # 800G PCS 64QAM: 8 slots, B-E is 100 km
    r = runner.run_eon(eon6, dem, "rsa_greedy", num_slots=24, save=False)
    assert r.status == "FEASIBLE"                       # 3 on B-E, 2 on longer paths with slower types
    assert [x["path"] for x in r.tables["demands"]].count("B > E") == 3
    r = runner.run_eon(eon6, [D(i, "B", "E", 800) for i in range(30)], "rsa_greedy", num_slots=24,
                       save=False)
    assert r.summary["blocked_spectrum"] > 0 and r.summary["max_slot_index"] == 24


def test_fixed_grid_divides_slots_by_4(eon6, eon6_demands):
    a = runner.run_eon(eon6, eon6_demands, "rsa_greedy", save=False)
    b = runner.run_eon(eon6, eon6_demands, "rsa_greedy", num_slots=80, slot_width=50, save=False)
    assert a.summary["total_slots_used"] == 4 * b.summary["total_slots_used"]
    assert a.summary["max_slot_index"] == 4 * b.summary["max_slot_index"]


def test_runner_errors(eon6, tmp_path):
    def run(code, **kw):
        p = tmp_path / "alg.py"
        p.write_text(code)
        return runner.run_eon(eon6, [D(0, "A", "C", 100)], str(p), save=False, **kw)
    head = "from pynet2plan.eon.solution import EonSolution\n"
    assert run(head + "def solve(G, demands):\n    return None\n").status == "ERROR"
    r = run(head + "from pynet2plan.solution import Solution\ndef solve(G, demands):\n    return Solution()\n")
    assert r.status == "ERROR" and "EonSolution" in r.message
    r = run(head + "def solve(G, demands):\n    return 1 / 0\n")
    assert r.status == "ERROR" and "ZeroDivisionError" in r.message
    r = run(head + "from pynet2plan.errors import NotCompletedError\ndef solve(G, demands):\n"
                   "    raise NotCompletedError('TODO 1: x')\n")
    assert r.status == "NOT_COMPLETED" and "line 4" in r.message
    r = run(head + "def solve(G, demands, k=3):\n    return EonSolution()\n", )
    assert r.status == "BLOCKING"
    assert run(head + "def solve(G, demands, k=3):\n    return EonSolution()\n",
               num_slots=0).status == "BLOCKING"                  # 0 slots: allowed, nothing served
    r = run(head + "def solve(G, demands, k=3):\n    return EonSolution()\n", num_slots=-1)
    assert r.status == "ERROR" and "at least 0" in r.message
    r = runner.run_eon(eon6, [D(0, "A", "Z", 100)], "rsa_greedy", save=False)
    assert r.status == "ERROR" and "unknown node" in r.message
    r = runner.run_eon(eon6, [D(0, "A", "C", 100)], "rsa_greedy", {"k": "x"}, save=False)
    assert r.status == "ERROR"
    r = runner.run_eon(eon6, [D(0, "A", "C", 100)], "does_not_exist", save=False)
    assert r.status == "ERROR" and "No EON algorithm" in r.message
    p = tmp_path / "bad.py"
    p.write_text("def solve(G, demands):\n    return (\n")
    assert runner.run_eon(eon6, [D(0, "A", "C", 100)], str(p), save=False).status == "ERROR"
    # an algorithm that cheats on the slots is INVALID, the folder is still written
    p.write_text(head + "def solve(G, demands):\n    s = EonSolution()\n"
                        "    for d in demands:\n        s.add_lightpath(d, ['A', 'B', 'C'], '100G QPSK', 0)\n"
                        "    return s\n")
    r = runner.run_eon(eon6, [D(0, "A", "C", 100), D(1, "A", "C", 100)], str(p),
                       output_root=str(tmp_path / "res"))
    assert r.status == "INVALID" and "cannot share" in r.message and r.folder


def test_discover_and_find():
    names = {os.path.basename(f.path) for f in runner.discover(include_solutions=False)}
    released = {n for n in ("rsa_3r.py",)                                             # exercises of a later
                if os.path.isfile(os.path.join(runner.EON_FORMULATIONS_DIR, n))}   # lab may be missing
    assert {"rsa_greedy.py"} | released <= names
    f = runner.find_eon_formulation("rsa_greedy")
    assert f.ok and not f.protection and not f.regeneration and f.parameters["k"] == 3
    assert runner.find_eon_formulation("formulations/eon/rsa_greedy").ok
    assert runner.find_eon_formulation(f.path).origin == "formulations"
    # the main window does not list the EON algorithms
    from pynet2plan import loader
    assert not any("eon" in i.path.split(os.sep)[-2] for i in loader.discover_all())


# ======================================================================
# results folders
# ======================================================================
def test_results_roundtrip(eon6, eon6_demands, tmp_path):
    r = runner.run_eon(eon6, eon6_demands, "rsa_greedy", output_root=str(tmp_path),
                       traffic_file="eon6_traffic.csv")
    assert r.status == "FEASIBLE" and r.folder
    files = set(os.listdir(r.folder))
    assert {"summary.csv", "demands.csv", "lightpaths.csv", "links.csv", "spectrum.csv",
            "fibre_cuts.csv", "validation.csv", "report.txt", "topology.json", "traffic.csv",
            "transponders.csv", "formulation.py"} <= files
    run = eres.load_run(r.folder)
    assert run.summary["served_demands"] == 120 and run.summary["kind"] == "eon"
    assert run.summary["total_slots_used"] == r.summary["total_slots_used"]
    assert len(run.lightpaths) == r.summary["lightpaths"] and run.table == TABLE
    assert run.demands == eon6_demands and run.G.number_of_edges() == 14
    assert "eon_transponders" not in run.G.graph
    assert sum(x["slots"] * 1 for x in run.spectrum) == run.summary["total_slots_used"]
    assert sum(l["slots_used"] for l in run.links) == run.summary["total_slots_used"]
    assert len(run.cuts) == 7 and "Served:" in run.report and run.num_slots == 320
    assert eres.list_runs(str(tmp_path))[0]["served"] == "120/120"
    # the main results browser ignores EON runs written to results/eon/
    from pynet2plan import results as base
    assert not base.is_run_folder(str(tmp_path)) and eres.is_eon_run_folder(r.folder)
    with pytest.raises(Exception):
        eres.load_run(str(tmp_path))


def test_sweep(eon6, eon6_demands, tmp_path):
    algs = [("rsa_greedy", {"k": [1, 3]})]
    sw = runner.run_eon_sweep(eon6, eon6_demands, algs, "num_demands", [20, 60],
                              output_root=str(tmp_path))
    assert len(sw.rows) == 4 and not sw.cancelled
    loaded = eres.load_sweep(sw.folder)
    assert [r["sweep_value"] for r in loaded.rows] == [20, 20, 60, 60]
    assert [r["num_demands"] for r in loaded.rows] == [20, 20, 60, 60]
    assert all(loaded.run_folder(r) for r in loaded.rows)
    assert eres.list_runs(str(tmp_path))[0]["kind"] == "sweep"
    sw2 = runner.run_eon_sweep(eon6, eon6_demands[:30], [("rsa_greedy", {})], "num_slots", [8, 320],
                               save=False)
    assert sw2.rows[0]["blocked_demands"] > 0 and sw2.rows[1]["blocked_demands"] == 0
    sw3 = runner.run_eon_sweep(eon6, eon6_demands[:30], [("rsa_greedy", {})], "reach_scale", [0.1, 1],
                               save=False)
    assert sw3.rows[0]["blocked_reach"] > 0 and sw3.rows[1]["blocked_reach"] == 0
    with pytest.raises(ValueError):
        runner.run_eon_sweep(eon6, eon6_demands, algs, "colour", [1], save=False)
    stop = runner.run_eon_sweep(eon6, eon6_demands, algs, "none", [], save=False, should_stop=lambda: True)
    assert stop.cancelled and stop.rows == []


def test_payload_dispatch_and_jobs(eon6, tmp_path):
    from pynet2plan import runner as base_runner
    from pynet2plan.jobs import Job
    payload = dict(kind="eon_run", topology=network.topology_to_dict(eon6), demands=traffic.demands_to_dicts(
        [D(0, "A", "C", 600)]), formulation="rsa_greedy", params={"k": 2}, num_slots=64, slot_width=12.5,
        table=tpm.table_to_dicts(TABLE), output_root=str(tmp_path))
    out = base_runner.payload_run(payload)
    assert out["kind"] == "eon_run" and out["status"] == "FEASIBLE" and out["folder"]
    assert out["summary"]["num_slots"] == 64
    out = base_runner.payload_run(dict(kind="eon_check", formulation="rsa_greedy"))
    assert out["status"] == "BLOCKING" and "Validation passed" in out["message"]
    sweep = dict(payload, kind="eon_sweep", algorithms=[dict(formulation="rsa_greedy", grid={})],
                 axis="num_slots", values=[16, 32])
    for use_process in (False, True):
        job = Job(sweep, use_process=use_process)
        assert job.wait(120)
        assert job.result["kind"] == "eon_sweep" and len(job.result["rows"]) == 2, job.crash


def test_check_formulation():
    r = runner.check_formulation("rsa_greedy")
    assert r.ok and "Validation passed" in r.message
    G, dem = runner.check_network()
    assert G.number_of_edges() == 14 and len(dem) == 9
    assert runner.check_formulation("rsa_1plus1_ilp").status in ("BLOCKING", "FEASIBLE")


# ======================================================================
# analysis
# ======================================================================
def test_fibre_cuts_and_hardware(eon6):
    sol = EonSolution()
    sol.add_lightpath(0, ["A", "B", "C"], "400G PCS 16QAM", 0)
    sol.add_lightpath(1, ["C", "B"], "200G 16QAM", 0)
    sol.add_lightpath(1, ["C", "F", "E", "B"], "200G 16QAM", 0, backup=True)
    sol.add_lightpath(2, ["A", "D"], "200G 16QAM", [0], [])
    dem = [D(0, "A", "C", 400), D(1, "C", "B", 200), D(2, "A", "D", 200)]
    cuts = {r["fibre"]: r for r in analysis.fibre_cuts(eon6, dem, sol)}
    assert len(cuts) == 7
    assert cuts["B-C"]["demands_hit"] == 2 and cuts["B-C"]["demands_down"] == 1
    assert cuts["B-C"]["demands_switched"] == 1 and cuts["B-C"]["gbps_down"] == 400
    assert cuts["E-F"]["demands_hit"] == 0
    m = analysis.cut_metrics(list(cuts.values()))
    assert m["demands_down_worst_cut"] == 1 and m["worst_cut"] in ("A-B", "B-C", "A-D")
    hw = analysis.hardware(sol, TABLE)
    assert hw == dict(lightpaths=4, transponders=8, regenerators=0, hardware_cost=8.0)
    sol.lightpaths[0].regenerators = ["B"]
    assert analysis.hardware(sol, TABLE)["hardware_cost"] == 10.0


def test_cost_model_part3():
    # 1.2 Tb/s from A to C (700 + 500 km), as in Part III of the notebook
    lr = analysis.carry_on_chain(TABLE, 1200, 1200, 600, with_3r=False)
    r3 = analysis.carry_on_chain(TABLE, 1200, 1200, 600, with_3r=True)
    assert lr["lightpaths"] == "3 × 400G PCS 16QAM" and lr["hardware_cost"] == 6 and lr["total_slots"] == 48
    assert r3["lightpaths"] == "2 × 600G 16QAM" and r3["regenerators"] == 2
    assert r3["hardware_cost"] == 8 and r3["total_slots"] == 32
    assert analysis.break_even(6, 48, 8, 32) == pytest.approx(0.125)
    assert analysis.break_even(6, 48, 8, 48) is None and analysis.break_even(8, 48, 6, 32) is None
    assert analysis.total_cost(6, 48, 0.125) == analysis.total_cost(8, 32, 0.125)
    rows = analysis.chain_comparison(TABLE, 1200, range(200, 3200, 200), span=200)
    assert all(r["slots_saved_3r"] == 0 for r in rows if r["km"] <= 600)   # no 3R needed: no gap
    assert all(r["regenerators"] > 0 for r in rows if r["km"] > 700)
    assert all(r["slots_saved_3r"] >= 0 and r["extra_hw_3r"] >= 0 for r in rows)
    assert analysis.regenerators_on_chain(1200, 200, 700) == 1
    assert analysis.regenerators_on_chain(1200, 200, 150) is None
    assert analysis.regenerators_on_chain(600, 200, 700) == 0
    with_costs = [tpm.Transponder(**{**tp.__dict__, "cost": 1 + tp.rate / 400}) for tp in TABLE]
    assert analysis.carry_on_chain(with_costs, 100, 600, 200, True)["hardware_cost"] == pytest.approx(2.5)


def test_reach_islands(eon6):
    assert analysis.reach_islands(eon6, TP["800G PCS 64QAM"]) == [["B", "E"], ["A"], ["C"], ["D"], ["F"]]
    isl = analysis.reach_islands(eon6, TP["700G PCS 64QAM"])
    assert isl[0] == ["A", "B", "D", "E"] and len(isl) == 3
    assert analysis.reach_islands(eon6, TP["100G QPSK"]) == [list("ABCDEF")]


# ======================================================================
# the 120 demands of EON-6 (reference values; each direction has its own spectrum)
# ======================================================================
def test_eon6_rsa_reference(eon6, eon6_demands):
    r = runner.run_eon(eon6, eon6_demands, "rsa_greedy", save=False)
    s = r.summary
    assert r.status == "FEASIBLE"
    assert (s["served_demands"], s["lightpaths"], s["transponders"], s["total_slots_used"]) == (120, 155, 310, 1768)
    assert s["regenerators"] == 0 and s["blocked_reach"] == 0
    assert s["demands_down_worst_cut"] > 0


@needs_solutions
def test_eon6_reference_solutions(eon6, eon6_demands):
    p = runner.run_eon(eon6, eon6_demands, "rsa_1plus1_two_step", save=False).summary
    t = runner.run_eon(eon6, eon6_demands, "solutions/rsa_3r", save=False).summary
    g = runner.run_eon(eon6, eon6_demands, "rsa_greedy", save=False).summary
    assert p["served_demands"] == 77 and p["blocked_spectrum"] == 37 and p["blocked_disjoint"] == 6
    assert p["demands_down_worst_cut"] == 0 and p["backup_lightpaths"] > 0
    assert (t["served_demands"], t["lightpaths"], t["regenerators"], t["total_slots_used"]) == (120, 152, 11, 1636)
    assert t["total_slots_used"] < g["total_slots_used"] and t["hardware_cost"] > g["hardware_cost"]
    same = runner.run_eon(eon6, eon6_demands, "solutions/rsa_3r", {"choose": "3R"}, save=False).summary
    assert same["regenerators"] == 0 and same["total_slots_used"] == g["total_slots_used"]


@needs_solutions
def test_protection_survives_every_cut(eon6, eon6_demands):
    r = runner.run_eon(eon6, eon6_demands, "rsa_1plus1_two_step", save=False)
    assert all(c["demands_down"] == 0 for c in r.tables["cuts"])
    assert sum(c["demands_switched"] for c in r.tables["cuts"]) > 0


def test_nx_version_sanity():
    assert nx.__version__ >= "3"


# ======================================================================
# exercises vs reference solutions
# ======================================================================
EON_EXERCISES = ["rsa_3r"]


@needs_solutions
@pytest.mark.parametrize("name", EON_EXERCISES)
def test_eon_exercise_matches_solution(name):
    from conftest import FORMULATIONS, SOLUTIONS
    ex = runner.load_eon_formulation(os.path.join(FORMULATIONS, "eon", f"{name}.py"))
    so = runner.load_eon_formulation(os.path.join(SOLUTIONS, "eon", f"{name}.py"), "solutions")
    assert ex.ok and so.ok, (ex.error, so.error)
    assert (ex.name, ex.parameters, ex.parameter_choices, ex.protection, ex.regeneration) == \
           (so.name, so.parameters, so.parameter_choices, so.protection, so.regeneration)
    assert so.todo_count == 0
    if ex.todo_count:
        r = runner.check_formulation(ex)
        assert r.status == "NOT_COMPLETED" and "TODO 1" in r.message and f"{name}.py, line" in r.message


@needs_solutions
@pytest.mark.parametrize("name", EON_EXERCISES)
def test_eon_solutions_pass_the_check(name):
    r = runner.check_formulation(f"solutions/{name}")
    assert r.ok and "Validation passed" in r.message, r.message


# ======================================================================
# edge cases, fair comparison, command line
# ======================================================================
def test_zero_and_huge_demands(eon6):
    r = runner.run_eon(eon6, [D(0, "A", "C", 0)], "rsa_greedy", save=False)
    assert r.status == "ERROR" and "positive number of Gb/s" in r.message
    big = runner.run_eon(eon6, [D(0, "B", "E", 6000), D(1, "A", "C", 6000)], "rsa_greedy", save=False)
    assert big.status == "FEASIBLE", big.message                  # 12 lightpaths of 500G: allowed
    assert big.summary["lightpaths"] >= 8 + 12
    combo = helpers.best_combination([(TP["100G QPSK"], 0)], 2000)
    assert len(combo) == 20                                       # more than 16 lightpaths: still carried
    assert len(helpers.best_combination([(TP["100G QPSK"], 0)], 1600)) == 16
    # 12.8 Tb/s over A-C (1200 km): 500G reaches, 26 lightpaths; not blocked "for reach"
    huge = runner.run_eon(eon6, [D(0, "A", "C", 12800)], "rsa_greedy", save=False)
    assert huge.status == "FEASIBLE" and huge.summary["lightpaths"] == 26, huge.message
    assert len(helpers.best_combination([(tp, 0) for tp in TP.values()], 20000)) == 25    # 25 x 800G


@needs_solutions
def test_protection_comparison(eon6, eon6_demands):
    c = runner.protection_comparison(eon6, eon6_demands, "rsa_greedy", "rsa_1plus1_two_step")
    assert c["message"] == "" and c["same_demands"] == 77
    g = {x["group"]: x for x in c["groups"]}
    assert g["served without protection, blocked with 1+1"]["demands"] == 43
    assert g["served without protection, blocked with 1+1"]["reasons"] == "no disjoint path: 6, spectrum: 37"
    rows = {r["key"]: r for r in c["rows"]}
    assert rows["served_demands"]["unprotected"] == rows["served_demands"]["protected"] == 77
    assert rows["transponders"]["ratio"] > 2 and rows["total_slots_used"]["ratio"] > 3
    assert rows["demands_down_worst_cut"]["protected"] == 0 and rows["demands_down_worst_cut"]["unprotected"] > 0
    text = runner.format_protection_comparison(c)
    assert "The same 77 demands" in text


def test_protection_comparison_reports_errors(eon6, eon6_demands):
    c = runner.protection_comparison(eon6, eon6_demands[:5], "rsa_greedy", "does_not_exist")
    assert "ERROR" in c["message"] and c["rows"] == []


def test_cli(tmp_path, capsys):
    from pynet2plan import cli
    topo = os.path.join(DATA, "topologies", "eon6.json")
    traf = os.path.join(DATA, "traffic_eon", "eon6_slide_example.csv")
    out = str(tmp_path / "res")
    assert cli.main(["eon-list"]) == 0
    assert "rsa_greedy.py" in capsys.readouterr().out
    assert cli.main(["eon-check", "rsa_greedy"]) == 0
    assert "Validation passed" in capsys.readouterr().out
    assert cli.main(["eon-run", "-t", topo, "-d", traf, "-a", "rsa_greedy", "-o", out, "--plot"]) == 0
    text = capsys.readouterr().out
    assert "Served:      3 demands" in text and "spectrum.png" in text
    folder = text.split("Results saved in: ")[1].splitlines()[0].strip()
    assert cli.main(["eon-report", folder]) == 0 and "Served:" in capsys.readouterr().out
    assert cli.main(["eon-plot", folder]) == 0 and "cuts.png" in capsys.readouterr().out
    assert cli.main(["eon-run", "-t", topo, "-d", traf, "-a", "rsa_greedy", "--slots", "8", "--no-save"]) == 0
    assert "BLOCKING" in capsys.readouterr().out
    assert cli.main(["eon-run", "-t", topo, "-d", traf, "-a", "rsa_greedy", "--reach-scale", "0.1",
                     "--no-save"]) == 0
    assert "reach 3" in capsys.readouterr().out
    assert cli.main(["eon-run", "-t", topo, "-d", traf, "-a", "rsa_1plus1_ilp", "--no-save"]) in (0, 1)
    capsys.readouterr()
    assert cli.main(["eon-sweep", "-t", topo, "-d", os.path.join(DATA, "traffic_eon", "eon6_traffic.csv"),
                     "-a", "rsa_greedy:k=1,3", "--axis", "num_demands", "--values", "20-60:20", "-o", out,
                     "--plot"]) == 0
    text = capsys.readouterr().out
    assert "sweep.png" in text and text.count("FEASIBLE") == 6
    sweep = text.split("Sweep saved in: ")[1].splitlines()[0].strip()
    assert cli.main(["eon-report", sweep]) == 0 and "num_demands=60" in capsys.readouterr().out
    assert cli.main(["eon-sweep", "-t", topo, "-d", traf, "-a", "rsa_greedy", "--axis", "reach_scale",
                     "--values", "0.5,1", "-o", out]) == 0
    capsys.readouterr()
    t = str(tmp_path / "t.csv")
    assert cli.main(["eon-traffic", "-t", topo, "-n", "12", "--seed", "3", "--rates", "100,200", "-o", t]) == 0
    dem = traffic.load_traffic(t)
    assert len(dem) == 12 and {d.traffic for d in dem} <= {100, 200}
    assert dem == etraffic.random_eon_traffic(network.load_topology(topo), 12, [100, 200], seed=3)
    assert cli.main(["eon-traffic", "-t", topo, "--full-mesh", "-o", t]) == 0
    assert len(traffic.load_traffic(t)) == 30
    capsys.readouterr()
    assert cli.main(["eon-cost", "--rate", "1200", "--span", "200", "--max-km", "1400"]) == 0
    text = capsys.readouterr().out
    assert "3R cheaper if C_SLOT > 0.0417" in text and "same lightpaths" in text
    rc = cli.main(["eon-protection", "-t", topo, "-d", traf, "--protected", "does_not_exist"])
    assert rc == 1 and "ERROR" in capsys.readouterr().out


@needs_solutions
def test_the_self_check_accepts_the_reference_solutions():
    """tests/test_eon_exercises.py run on solutions/eon/: a student who completes an exercise
    correctly must pass its self-check (no stale reference value)."""
    import subprocess
    import sys
    from conftest import ROOT, SOLUTIONS
    env = dict(os.environ, PYNET2PLAN_EON_EXERCISES=os.path.join(SOLUTIONS, "eon"))
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        os.path.join("tests", "test_eon_exercises.py")], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    assert p.returncode == 0 and "2 passed" in p.stdout, p.stdout[-2000:]


def test_k_below_one_and_unknown_names_are_explained():
    G = network.load_topology(os.path.join(DATA, "topologies", "eon6.json"))
    r = runner.run_eon(G, [traffic.Demand(0, "A", "C", 100)], "rsa_greedy", {"k": 0}, save=False)
    assert r.status == "ERROR" and "at least 1" in r.message
    info = runner.find_eon_formulation("rsa_1+1")
    assert not info.ok and "Available:" in info.error and "rsa_1plus1_two_step" in info.error


def test_check_gives_the_reference_count():
    r = runner.check_formulation("rsa_greedy")
    assert r.ok and "The reference solution serves 7 of 9 demands here too." in r.message


@needs_solutions
def test_several_fibres_cut_together(eon6):
    """One fibre: the same as its row of fibre_cuts. Two fibres: 1+1 survives every single cut,
    but loses the demands whose working path crosses one cut fibre and the backup the other."""
    dem = traffic.load_traffic(os.path.join(DATA, "traffic_eon", "eon6_traffic.csv"), eon6)
    sol = runner.run_eon(eon6, dem, "rsa_1plus1_two_step", save=False).solution
    rows = {r["fibre"]: r for r in analysis.fibre_cuts(eon6, dem, sol)}
    for name, r in rows.items():
        one = analysis.cut_effect(eon6, dem, sol, [(r["u"], r["v"])])
        assert (one["demands_down"], one["demands_switched"]) == (r["demands_down"], r["demands_switched"]) == (
            0, r["demands_hit"])
    two = analysis.cut_effect(eon6, dem, sol, [("D", "E"), ("B", "C")])
    assert two["fibre"] == "D-E, B-C" and two["demands_down"] > 0
    assert two["demands_down"] + two["demands_switched"] == two["demands_hit"]
    G = eon6.copy()
    analysis.set_cut_fibres(G, [("D", "E"), ("E", "D"), ("B", "C")])          # E-D is the fibre D-E
    assert analysis.cut_fibres(G) == [("D", "E"), ("B", "C")]
    H = network.topology_from_dict(network.topology_to_dict(G))
    assert analysis.cut_fibres(H) == [("D", "E"), ("B", "C")]
    s = runner.run_eon(G, dem, "rsa_1plus1_two_step", save=False).summary
    assert (s["cut_fibre"], s["demands_down_cut"]) == ("D-E, B-C", two["demands_down"])
    analysis.set_cut_fibres(G, [])
    assert "cut_after_planning" not in G.graph and analysis.cut_fibres(G) == []


@needs_solutions
def test_one_direction_cut(eon6):
    """A cut of one direction only (u, v, "oneway"): the demands whose working path uses u -> v."""
    spain = network.load_topology(os.path.join(DATA, "topologies", "spain7.json"))
    dem = traffic.load_traffic(os.path.join(DATA, "traffic_eon", "spain7_lab4_protection.csv"), spain)
    sol = runner.run_eon(spain, dem, "rsa_greedy", save=False).solution
    uses = {lp.demand_id for lp in sol.lightpaths if ("Murcia", "Valencia") in zip(lp.path[:-1], lp.path[1:])}
    one = analysis.cut_effect(spain, dem, sol, [("Murcia", "Valencia", analysis.ONEWAY)])
    both = analysis.cut_effect(spain, dem, sol, [("Murcia", "Valencia")])
    assert one["fibre"] == "Murcia>Valencia" and one["demands_down"] == len(uses) < both["demands_down"]
    prot = runner.run_eon(spain, dem, "rsa_1plus1_two_step", save=False).solution
    assert analysis.cut_effect(spain, dem, prot, [("Murcia", "Valencia", analysis.ONEWAY)])["demands_down"] == 0
    G = spain.copy()
    analysis.set_cut_fibres(G, [("Murcia", "Valencia", analysis.ONEWAY), ("Murcia", "Valencia", analysis.ONEWAY)])
    assert analysis.cut_fibres(G) == [("Murcia", "Valencia", "oneway")]
    assert analysis.cut_fibres(network.topology_from_dict(network.topology_to_dict(G))) == [
        ("Murcia", "Valencia", "oneway")]
    analysis.set_cut_fibres(G, analysis.cut_fibres(G) + [("Valencia", "Murcia")])   # the fibre replaces it
    assert analysis.cut_fibres(G) == [("Valencia", "Murcia")]
    s = runner.run_eon(G, dem, "rsa_greedy", save=False).summary
    assert s["demands_down_cut"] == both["demands_down"]


def test_a_transponder_budget_for_every_algorithm(eon6, eon6_demands):
    """run_eon(max_cost=...): an algorithm without the parameter has its plan cut to the budget
    (its demands in order while the budget lasts), the others are blocked for 'budget'."""
    free = runner.run_eon(eon6, eon6_demands, "rsa_greedy", save=False)
    cut = runner.run_eon(eon6, eon6_demands, "rsa_greedy", max_cost=100, save=False)
    assert cut.ok and cut.summary["hardware_cost"] <= 100 < free.summary["hardware_cost"]
    assert cut.summary["cost_budget"] == 100
    reasons = [r["reason"] for r in cut.tables["demands"] if r.get("reason")]
    assert reasons.count("budget") == free.summary["served_demands"] - cut.summary["served_demands"]
    kept = {lp.demand_id for lp in cut.solution.lightpaths}
    assert kept <= {lp.demand_id for lp in free.solution.lightpaths}       # the same lightpaths, fewer demands
