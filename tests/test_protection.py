"""1+1 protection on the wavelength lab: the two greedy heuristics and the route formulation,
the validator's disjoint-backup check, and the fibre-cut-after-planning analysis."""

import os

import networkx as nx
import pytest

from conftest import DATA, ROOT, needs_solutions  # noqa: F401
from pynet2plan import analysis, network, runner, traffic
from pynet2plan.solution import Solution
from pynet2plan.validation import has_errors, validate_solution

RF = "solutions/protection_route_formulation"        # the reference solution (the exercise has TODOs)
# the student copy has the exercise (with TODOs) but not the reference solution
HAS_RF = os.path.isfile(os.path.join(ROOT, "solutions", "protection_route_formulation.py"))
needs_rf = pytest.mark.skipif(not HAS_RF, reason="the reference route formulation is not part of this copy")
PROTECTED = ("greedy_1plus1_protection", RF)
PROTECTED_PARAMS = ("greedy_1plus1_protection", pytest.param(RF, marks=needs_rf))


@pytest.fixture
def spain_prot():
    G = network.load_topology(os.path.join(DATA, "topologies", "spain7.json"))
    D = traffic.load_traffic(os.path.join(DATA, "traffic", "spain7_protection.csv"), G)
    return G, D


def test_example_declares_the_cut(spain_prot):
    G, D = spain_prot
    assert len(D) == 30
    with open(os.path.join(DATA, "traffic", "spain7_protection.csv"), encoding="utf-8") as fh:
        assert "# cut fibre: Murcia-Valencia" in fh.read()      # the GUI applies it after planning


@pytest.mark.parametrize("alg", ("greedy_no_protection",) + PROTECTED_PARAMS)
def test_runs_and_validates(spain_prot, alg):
    G, D = spain_prot
    res = runner.run_algorithm(G, D, alg, save=False)
    assert res.status in ("FEASIBLE", "OPTIMAL"), res.message
    assert res.summary["errors"] == 0
    assert res.summary["blocked_demands"] == 0          # every demand served at 40 wavelengths


@pytest.mark.parametrize("alg", PROTECTED_PARAMS)
def test_protection_survives_the_cut(spain_prot, alg):
    """Every served demand has a fibre-disjoint backup, so cutting Murcia-Valencia takes none down."""
    G, D = spain_prot
    sol = runner.run_algorithm(G, D, alg, save=False).solution
    assert sol.is_protected()
    eff = analysis.cut_effect(G, D, sol, [("Murcia", "Valencia")])
    assert eff["demands_down"] == 0 and eff["demands_switched"] > 0


def test_no_protection_loses_demands_to_the_cut(spain_prot):
    G, D = spain_prot
    sol = runner.run_algorithm(G, D, "greedy_no_protection", save=False).solution
    assert not sol.is_protected()
    assert analysis.cut_effect(G, D, sol, [("Murcia", "Valencia")])["demands_down"] == 11


@needs_rf
def test_route_formulation_serves_at_least_the_heuristic(spain_prot):
    """At a capacity where 1+1 cannot serve everything, the ILP serves at least as many demands."""
    G, _ = spain_prot
    D = traffic.random_traffic(G, 30, 1, 2, seed=7)
    H = G.copy()
    network.set_uniform_capacity(H, 16)
    served = {}
    for alg in PROTECTED:
        s = runner.run_algorithm(H, D, alg, save=False).summary
        served[alg] = len(D) - s["blocked_demands"]
    assert served[RF] >= served["greedy_1plus1_protection"]


@needs_rf
def test_tight_example_separates_the_three_algorithms():
    """The tight (10 lambda) example is the one where the algorithms differ: no protection
    serves everyone (without backup), the greedy 1+1 heuristic blocks 3 demands, and the
    route formulation (ILP, global optimum) protects all of them."""
    G = network.load_topology(os.path.join(DATA, "topologies", "spain7_tight.json"))
    D = traffic.load_traffic(os.path.join(DATA, "traffic", "spain7_tight.csv"), G)
    assert len(D) == 24
    assert {a["capacity"] for _, _, a in G.edges(data=True)} == {10}

    def served(alg):
        s = runner.run_algorithm(G, D, alg, save=False).summary
        return len(D) - s["blocked_demands"]

    no_prot = served("greedy_no_protection")
    heur = served("greedy_1plus1_protection")
    route = served(RF)
    assert no_prot == 24                      # no protection serves everyone (but has no backup)
    assert heur < no_prot                     # protection costs capacity, so the heuristic blocks some
    assert route > heur                       # the ILP protects strictly more than the greedy heuristic
    assert (no_prot, heur, route) == (24, 21, 24)

    # and the cut after planning still tells the protection story
    sol_np = runner.run_algorithm(G, D, "greedy_no_protection", save=False).solution
    sol_h = runner.run_algorithm(G, D, "greedy_1plus1_protection", save=False).solution
    cut = [("Murcia", "Valencia")]
    assert analysis.cut_effect(G, D, sol_np, cut)["demands_down"] == 6
    assert analysis.cut_effect(G, D, sol_h, cut)["demands_down"] == 0


@needs_rf
def test_tight_example_sweep_is_monotone_and_dominant():
    """The sweep over 4-12 is the clean picture: both protection curves fall monotonically as
    capacity grows, and the route formulation blocks no more than the greedy heuristic anywhere."""
    G = network.load_topology(os.path.join(DATA, "topologies", "spain7_tight.json"))
    D = traffic.load_traffic(os.path.join(DATA, "traffic", "spain7_tight.csv"), G)
    caps = list(range(4, 13))

    def blocked(alg):
        out = []
        for c in caps:
            H = G.copy()
            network.set_uniform_capacity(H, c)
            out.append(runner.run_algorithm(H, D, alg, save=False).summary["blocked_demands"])
        return out

    heur = blocked("greedy_1plus1_protection")
    route = blocked(RF)
    assert all(heur[i] >= heur[i + 1] for i in range(len(caps) - 1))     # greedy monotone
    assert all(route[i] >= route[i + 1] for i in range(len(caps) - 1))   # ILP monotone
    assert all(route[i] <= heur[i] for i in range(len(caps)))            # ILP dominates everywhere
    assert route[-1] == 0 and heur[-1] == 0                              # both clear at 12 wavelengths
    assert route[caps.index(10)] == 0 and heur[caps.index(10)] > 0       # the ILP already at 10


@needs_rf
@pytest.mark.parametrize("seed,n,tmax,cap", [(9, 24, 1, 6), (2, 30, 2, 20), (14, 30, 2, 14)])
def test_route_formulation_never_worse_than_greedy(seed, n, tmax, cap):
    """Regression: instances where the old route formulation (wavelengths given by first-fit
    AFTER the ILP) served fewer demands than the greedy. With the wavelengths inside the ILP,
    the greedy plan is a feasible solution, so the optimum serves at least as many."""
    G = network.load_topology(os.path.join(DATA, "topologies", "spain7.json"))
    D = traffic.random_traffic(G, n, 1, tmax, seed=seed)
    network.set_uniform_capacity(G, cap)
    heur = runner.run_algorithm(G, D, "greedy_1plus1_protection", save=False).summary
    res = runner.run_algorithm(G, D, RF, save=False)
    assert res.summary["errors"] == 0
    assert res.summary["blocked_demands"] <= heur["blocked_demands"]


def test_sweep_plots_blocking_runs_as_a_curve():
    """Regression: a BLOCKING run (valid solution with some demands blocked) must be drawn as a
    plotted curve, not treated as 'no valid solution'. This is what the protection sweep compares."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    from pynet2plan import plotting

    rows = [
        {"algorithm": "greedy 1+1", "capacity": 8, "status": "BLOCKING", "blocked_demands": 17},
        {"algorithm": "greedy 1+1", "capacity": 12, "status": "BLOCKING", "blocked_demands": 10},
        {"algorithm": "greedy 1+1", "capacity": 16, "status": "BLOCKING", "blocked_demands": 7},
    ]
    ax = Figure().add_subplot(111)
    plotting.plot_sweep(ax, None, rows, metric="blocked_demands", compact=True)
    curves = [ln for ln in ax.get_lines() if ln.get_linestyle() not in ("none", "None")]
    assert curves, "a BLOCKING series must be drawn as a line, not only crosses on the axis"
    ys = sorted(curves[0].get_ydata())
    assert ys == [7, 10, 17]


def test_validator_requires_a_disjoint_backup(spain_prot):
    G, D = spain_prot
    d = D[0]
    path = nx.shortest_path(G, d.origin, d.destination)
    wl = list(range(int(d.traffic)))
    # served working path, but the backup shares every fibre (reuses the working path)
    sol = Solution()
    sol.add_route(d, path, d.traffic, wavelengths=wl, backup=False)
    sol.add_route(d, path, d.traffic, wavelengths=wl, backup=True)
    issues = validate_solution(G, [d], sol, splittable=False, allows_blocking=True, protection=True)
    assert has_errors(issues)
    assert any("share the fibre" in i.message for i in issues)
    # a backup route on a non-protection formulation is rejected too
    sol2 = Solution()
    sol2.add_route(d, path, d.traffic, backup=True)
    assert has_errors(validate_solution(G, [d], sol2, allows_blocking=True, protection=False))


@needs_solutions
def test_slide72_version_gives_the_same_plan_cost():
    """solutions/protection_route_formulation_prof (slide 72 of the course: unit requests t,
    link-disjoint constraint) and the lab version (disjoint pairs, demand + capacity) agree."""
    G = network.load_topology(os.path.join(DATA, "topologies", "spain7_tight.json"))
    D = traffic.load_traffic(os.path.join(DATA, "traffic", "spain7_tight.csv"), G)
    for C in (6, 10):
        H = G.copy()
        network.set_uniform_capacity(H, C)
        lab = runner.run_algorithm(H, D, RF, save=False)
        prof = runner.run_algorithm(H, D, "solutions/protection_route_formulation_prof", save=False)
        assert not [i for i in prof.issues if i.severity == "error"]
        assert prof.summary["blocked_demands"] == lab.summary["blocked_demands"]
        assert prof.summary["wavelength_links"] == lab.summary["wavelength_links"]


@needs_rf
def test_italy10_exercise_has_the_same_trend():
    """The students' example (Italy-10, 9 wavelengths, 30 single-wavelength demands) shows the
    trend of Spain-7 tight: no protection serves all, the greedy 1+1 blocks some, the route
    formulation protects all; over 5-13 both curves fall, the ILP is never worse and clears first."""
    G = network.load_topology(os.path.join(DATA, "topologies", "italy10_tight.json"))
    D = traffic.load_traffic(os.path.join(DATA, "traffic", "italy10_tight.csv"), G)
    assert len(D) == 30 and {d.traffic for d in D} == {1}
    assert {a["capacity"] for _, _, a in G.edges(data=True)} == {9}

    def blocked(alg, c):
        H = G.copy()
        network.set_uniform_capacity(H, c)
        return runner.run_algorithm(H, D, alg, save=False).summary["blocked_demands"]

    caps = list(range(5, 14))
    nop = [blocked("greedy_no_protection", c) for c in caps]
    heur = [blocked("greedy_1plus1_protection", c) for c in caps]
    route = [blocked(RF, c) for c in caps]
    assert nop == [0] * len(caps)
    assert all(heur[i] >= heur[i + 1] for i in range(len(caps) - 1))
    assert all(route[i] >= route[i + 1] for i in range(len(caps) - 1))
    assert all(route[i] <= heur[i] for i in range(len(caps)))
    assert route[caps.index(9)] == 0 and heur[caps.index(9)] == 4 and heur[-1] == 0
    sol = runner.run_algorithm(G, D, "greedy_no_protection", save=False).solution
    assert analysis.cut_effect(G, D, sol, [("Bari", "Venice")])["demands_down"] == 8
