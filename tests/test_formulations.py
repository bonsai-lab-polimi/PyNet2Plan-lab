"""The given formulations, the exercise skeletons and the reference solutions."""

import os

import pytest

from pynet2plan import loader, network, runner
from pynet2plan.traffic import Demand

from conftest import DATA, FORMULATIONS, HAS_SOLUTIONS, SOLUTIONS, needs_solutions, small_demands, small_network

GIVEN = ["splittable_flow"]
EXERCISES = ["unsplittable_flow", "route_formulation_vwp", "ksp_first_fit", "route_formulation_wp"]
#: exercises released to the students for the first labs (see tools/make_student_version.py)
FIRST_LABS = ["unsplittable_flow", "route_formulation_vwp"]


def present(name):
    """Later exercises are not part of the student copy of the first labs."""
    if not os.path.isfile(os.path.join(FORMULATIONS, f"{name}.py")):
        pytest.skip(f"formulations/{name}.py is not part of this copy")


def run(name, G=None, D=None, **params):
    return runner.run_algorithm(G if G is not None else small_network(),
                                D if D is not None else small_demands(), name, params, save=False)


def with_capacity(G, c):
    H = G.copy()
    network.set_uniform_capacity(H, c)
    return H


def test_all_files_load():
    for info in loader.discover(FORMULATIONS):
        assert info.ok, (info.filename, info.error)
    for info in loader.discover(SOLUTIONS, "solutions"):
        assert info.ok, (info.filename, info.error)
    names = {os.path.splitext(i.filename)[0] for i in loader.discover(FORMULATIONS)}
    assert set(GIVEN) <= names
    if HAS_SOLUTIONS:                            # instructors: the exercises of Lab 2 are there too
        assert set(FIRST_LABS) <= names          # (students get them with git pull before Lab 2)
    assert "_template" not in names


@pytest.mark.parametrize("name", GIVEN + [pytest.param("solutions/route_formulation_vwp", marks=needs_solutions)])
def test_given_formulations_are_optimal(name):
    r = run(name)
    assert r.status == "OPTIMAL", r.message
    assert r.summary["objective"] == 20 == r.summary["wavelength_links"]
    assert not [i for i in r.issues if i.severity == "error"]


@pytest.mark.parametrize("name", ["splittable_flow", pytest.param("solutions/route_formulation_vwp",
                                                                   marks=needs_solutions)])
def test_variables_are_integer(name):
    """Wavelengths are discrete: the formulations have no option for continuous variables."""
    folder = SOLUTIONS if name.startswith("solutions/") else FORMULATIONS
    info = loader.load_formulation(os.path.join(folder, f"{os.path.basename(name)}.py"))
    assert "integer" not in info.parameters
    r = run(name)
    assert all(float(route["traffic"]).is_integer() for route in r.tables["routes"])


@needs_solutions
@pytest.mark.parametrize("name", EXERCISES)
def test_exercises_report_not_completed(name):
    """Instructor check: the exercises as distributed still contain their TODOs."""
    present(name)
    info = loader.load_formulation(os.path.join(FORMULATIONS, f"{name}.py"))
    if info.todo_count == 0:
        pytest.skip("exercise already completed")
    r = run(name)
    assert r.status == "NOT_COMPLETED"
    assert "TODO 1" in r.message
    assert f"{name}.py, line" in r.message           # points at the line to complete


def test_todo_placeholder_reported(tmp_path):
    from conftest import todo_formulation
    p = todo_formulation(tmp_path)
    info = loader.load_formulation(p)
    assert info.ok and info.todo_count == 1 and "1 TODO left" in info.label()
    r = run(p)
    assert r.status == "NOT_COMPLETED" and "line 6" in r.message and "TODO 1" in r.message


@needs_solutions
@pytest.mark.parametrize("name", EXERCISES)
def test_exercise_matches_solution(name):
    present(name)
    ex = loader.load_formulation(os.path.join(FORMULATIONS, f"{name}.py"))
    so = loader.load_formulation(os.path.join(SOLUTIONS, f"{name}.py"), "solutions")
    assert (ex.name, ex.parameters, ex.splittable, ex.allows_blocking, ex.wavelength_continuity) == \
        (so.name, so.parameters, so.splittable, so.allows_blocking, so.wavelength_continuity)


@needs_solutions
@pytest.mark.parametrize("name,status,objective", [
    ("solutions/unsplittable_flow", "OPTIMAL", 20),
    ("solutions/route_formulation_vwp", "OPTIMAL", 20),
    ("solutions/route_formulation_wp", "OPTIMAL", 20),
    ("solutions/ksp_first_fit", "FEASIBLE", 22),
])
def test_solutions_small(name, status, objective):
    r = run(name)
    assert r.status == status, r.message
    assert r.summary["wavelength_links"] == objective


@needs_solutions
def test_relations_between_formulations(spain):
    G, D = spain
    G = with_capacity(G, 23)
    sp = run("splittable_flow", G, D)
    un = run("solutions/unsplittable_flow", G, D)
    v = {k: run("solutions/route_formulation_vwp", G, D, k=k) for k in (1, 2, 3)}
    wp = run("solutions/route_formulation_wp", G, D, k=2)
    assert sp.status == un.status == "OPTIMAL"
    assert sp.summary["objective"] <= un.summary["objective"]
    assert v[1].status == "INFEASIBLE"                     # k=1 needs more capacity
    assert v[2].summary["objective"] >= v[3].summary["objective"] >= sp.summary["objective"]
    assert wp.status == "OPTIMAL" and wp.summary["objective"] >= v[2].summary["objective"]
    assert un.summary["split_demands"] == 0
    # wavelengths are listed and consistent
    assert wp.tables["wavelengths"]


@needs_solutions
def test_infeasible_and_blocking(spain):
    G, D = spain
    G = with_capacity(G, 10)
    for name in ["splittable_flow", "solutions/unsplittable_flow", "solutions/route_formulation_vwp",
                 "solutions/route_formulation_wp"]:
        r = run(name, G, D)
        assert r.status == "INFEASIBLE", (name, r.status, r.message)
        assert "infeasible" in r.message.lower()
    r = run("solutions/ksp_first_fit", G, D)
    assert r.status == "BLOCKING" and r.summary["blocked_traffic"] > 0
    r2 = run("solutions/ksp_first_fit", G, D, order="largest_first")
    assert r2.status == "BLOCKING"
    r3 = run("solutions/ksp_first_fit", G, D, k=1, weight="hops")
    assert r3.status == "BLOCKING"


def test_failures_and_unreachable():
    G = small_network()
    network.set_node_up(G, "E", False)
    r = run("splittable_flow", G)
    assert r.status == "OPTIMAL"
    assert r.summary["unreachable_demands"] == 3          # the 3 demands touching E
    states = {row["demand_id"]: row["state"] for row in r.tables["demands"]}
    assert states[1] == states[2] == states[3] == "UNREACHABLE"
    assert "unreachable" in r.message
    G = small_network()
    network.set_link_up(G, "B", "D", False)
    network.set_link_up(G, "D", "B", False)
    r = run("splittable_flow", G)
    assert r.status == "OPTIMAL"
    assert r.summary["objective"] > 20                    # B->D (4 λ) now needs 2 hops
    assert all("B > D" not in row["path"] for row in r.tables["routes"])
    used = {(l["origin"], l["destination"]): l["used"] for l in r.tables["links"]}
    assert used[("B", "D")] == 0


@needs_solutions
def test_solvers_agree(spain):
    G, D = spain
    a = runner.run_algorithm(G, D, "solutions/unsplittable_flow", save=False, solver="cbc")
    b = runner.run_algorithm(G, D, "solutions/unsplittable_flow", save=False, solver="highs")
    assert a.summary["solver"] != b.summary["solver"]
    assert a.summary["objective"] == pytest.approx(b.summary["objective"])


def test_check_formulation(tmp_path):
    from conftest import todo_formulation
    r = runner.check_formulation("splittable_flow")
    assert r.status == "OPTIMAL" and r.summary["objective"] == 20
    assert "Validation passed" in r.message
    assert runner.check_formulation(todo_formulation(tmp_path)).status == "NOT_COMPLETED"


@needs_solutions
@pytest.mark.parametrize("name,status,objective", [
    ("solutions/unsplittable_flow", "OPTIMAL", 21),     # cannot split: 1 more than splittable
    ("solutions/route_formulation_vwp", "OPTIMAL", 20),  # same as the splittable flow formulation
    ("solutions/route_formulation_wp", "OPTIMAL", 20),
    ("solutions/ksp_first_fit", "FEASIBLE", 24),        # heuristic: worse than the ILPs
])
def test_check_network_values(name, status, objective):
    r = runner.check_formulation(name)
    assert r.status == status and r.summary["wavelength_links"] == objective


def test_parameter_errors():
    assert run("splittable_flow", time_limit="abc").status == "ERROR"


@pytest.mark.skipif(not os.path.isfile(os.path.join(FORMULATIONS, "route_formulation_vwp.py")),
                    reason="Lab 2 material not downloaded yet (git pull)")
def test_parameters():
    r = run("route_formulation_vwp", k="2")                 # converted to an integer before solve()
    assert r.status in ("NOT_COMPLETED", "OPTIMAL") and "k=2" in r.summary["parameters"]
    assert run("route_formulation_vwp", k="abc").status == "ERROR"
    assert "Unknown parameter" in run("route_formulation_vwp", kk=2).message
    assert run("splittable_flow", time_limit="abc").status == "ERROR"


@needs_solutions
def test_choice_parameters():
    r = run("solutions/ksp_first_fit", order="random")
    assert r.status == "ERROR" and "must be one of" in r.message


@needs_solutions
def test_split_vs_unsplit_matrix():
    """data/traffic/spain7_traffic_split_vs_unsplit.csv: splitting matters for many capacities."""
    from pynet2plan import traffic
    G = network.load_topology(os.path.join(DATA, "topologies", "spain7.json"))
    D = traffic.load_traffic(os.path.join(DATA, "traffic", "spain7_traffic_split_vs_unsplit.csv"), G)
    expected = {33: (None, None), 34: (431, None), 35: (430, 460), 40: (425, 443),
                41: (424, 424), 50: (415, 422), 56: (409, 422), 57: (408, 408), 60: (408, 408)}
    for c, (sp_obj, un_obj) in expected.items():
        H = with_capacity(G, c)
        sp, un = run("splittable_flow", H, D), run("solutions/unsplittable_flow", H, D)
        assert (sp.summary["objective"] if sp.ok else None) == sp_obj, c
        assert (un.summary["objective"] if un.ok else None) == un_obj, c
