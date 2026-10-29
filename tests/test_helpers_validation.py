import pulp
import pytest

from pynet2plan import helpers
from pynet2plan.errors import InfeasibleError, SolverError, UnboundedError
from pynet2plan.solution import Solution, path_from_links
from pynet2plan.traffic import Demand
from pynet2plan.validation import has_errors, validate_solution

from conftest import small_network


@pytest.mark.parametrize("solver", ["auto", "cbc", "highs"])
def test_solve_ilp_statuses(solver):
    old = helpers.SETTINGS["solver"]
    helpers.SETTINGS["solver"] = solver
    try:
        p = pulp.LpProblem("t", pulp.LpMinimize)
        x = p.add_variable("x", lowBound=0, cat=pulp.LpInteger)
        p += x
        p += x >= 2.5
        assert helpers.solve_ilp(p) == "Optimal"
        assert helpers.value(x) == 3
        assert helpers.SOLVE_LOG[-1]["num_variables"] == 1
        q = pulp.LpProblem("q", pulp.LpMinimize)
        y = q.add_variable("y", 0, 1, cat=pulp.LpInteger)
        q += y
        q += y >= 2
        with pytest.raises(InfeasibleError):
            helpers.solve_ilp(q)
        u = pulp.LpProblem("u", pulp.LpMinimize)
        z = u.add_variable("z")
        u += z
        u += z <= 5
        with pytest.raises(UnboundedError, match="constraint"):
            helpers.solve_ilp(u)
    finally:
        helpers.SETTINGS["solver"] = old


def test_solve_ilp_warnings_and_duplicates():
    helpers.reset_solve_log()
    w = pulp.LpProblem("w", pulp.LpMinimize)
    a = w.add_variable("a", 0)
    w += a >= 2
    helpers.solve_ilp(w)
    assert "no objective" in helpers.SOLVE_LOG[-1]["warnings"][0]
    d = pulp.LpProblem("d", pulp.LpMinimize)
    a1, a2 = d.add_variable("a", 0), d.add_variable("a", 0)
    d += a1 + a2
    d += a1 + a2 >= 1
    with pytest.raises(SolverError, match="same name"):
        helpers.solve_ilp(d)


def test_solver_report():
    rep = helpers.solver_report()
    assert "PuLP" in rep and "Optimal" in rep


def test_flow_to_routes():
    flow = {("A", "B"): 2, ("B", "C"): 3, ("A", "D"): 1, ("D", "C"): 1, ("C", "A"): 0.0,
            ("X", "Y"): 5, ("B", "B2"): 1, ("B2", "B"): 1}            # cycle B-B2-B ignored
    routes = helpers.flow_to_routes(flow, "A", "C")
    assert sorted((tuple(p), a) for p, a in routes) == [(("A", "B", "C"), 2), (("A", "D", "C"), 1)]
    assert helpers.flow_to_routes({}, "A", "C") == []


def test_k_shortest_paths():
    G = small_network()
    paths = helpers.k_shortest_paths(G, "A", "C", 3)
    assert paths[0] in (["A", "B", "C"], ["A", "D", "C"]) and len(paths) == 3
    assert helpers.k_shortest_paths(G, "A", "C", 0) == []
    assert helpers.k_shortest_paths(G, "A", "Z", 2) == []
    assert helpers.path_links(["A", "B", "C"]) == [("A", "B"), ("B", "C")]


def test_solution_api():
    s = Solution(objective=5)
    d = Demand(0, "A", "C", 3)
    s.add_route(d, ["A", "B", "C"], 2.0000000001)
    s.add_route(0, [("A", "D"), ("D", "C")], 1)
    assert s.add_route(d, ["A", "B", "C"], 1e-9) is None          # ~0 ignored
    assert s.routes[0].traffic == 2 and isinstance(s.routes[0].traffic, int)
    assert s.routes[1].path == ["A", "D", "C"]
    assert s.carried() == {0: 3}
    assert s.link_occupancy()[("A", "B")] == 2
    assert s.wavelength_links() == 6
    assert Solution.from_dict(s.to_dict()).carried() == {0: 3}
    with pytest.raises(TypeError):
        s.add_route("x", ["A", "C"], 1)
    with pytest.raises(ValueError):
        path_from_links([("A", "B"), ("C", "D")])


def _issues(sol, demands, **flags):
    return validate_solution(small_network(capacity=4), demands, sol, **flags)


def test_validation_detects_errors():
    D = [Demand(0, "A", "C", 3), Demand(1, "B", "D", 2)]
    ok = Solution(objective=8)
    ok.add_route(0, ["A", "B", "C"], 3)
    ok.add_route(1, ["B", "D"], 2)
    assert not has_errors(_issues(ok, D, splittable=False))

    s = Solution()
    s.add_route(0, ["A", "B", "C"], 2)          # 2 of 3 carried
    s.add_route(1, ["B", "C", "D"], 2)
    msgs = " | ".join(i.message for i in _issues(s, D))
    assert "carries 2 of the 3" in msgs
    assert has_errors(_issues(s, D)) and not has_errors(_issues(s, D, allows_blocking=True))

    s = Solution()
    s.add_route(0, ["A", "B", "C"], 2)
    s.add_route(0, ["A", "D", "C"], 1)
    s.add_route(1, ["B", "D"], 2)
    assert not has_errors(_issues(s, D, splittable=True))
    assert "split over 2 paths" in " ".join(i.message for i in _issues(s, D, splittable=False))

    s = Solution()
    s.add_route(0, ["A", "B", "C"], 3)
    s.add_route(1, ["B", "C", "D"], 2)           # B->C gets 5 > 4
    assert "capacity is 4" in " ".join(i.message for i in _issues(s, D))

    s = Solution()
    s.add_route(0, ["A", "C"], 3)                # no link A->C
    s.add_route(1, ["D", "B"], 2)                # wrong direction
    msgs = " ".join(i.message for i in _issues(s, D))
    assert "does not exist" in msgs and "should go from B to D" in msgs

    s = Solution()
    s.add_route(7, ["A", "B"], 1)
    assert "no demand with id 7" in " ".join(i.message for i in _issues(s, D))


def test_validation_wavelengths_and_objective():
    D = [Demand(0, "A", "C", 2), Demand(1, "B", "C", 1)]
    s = Solution(objective=5)
    s.add_route(0, ["A", "B", "C"], 2, wavelengths=[0, 1])
    s.add_route(1, ["B", "C"], 1, wavelengths=[1])          # clash on B->C, wavelength 1
    msgs = " ".join(i.message for i in _issues(s, D, wavelength_continuity=True))
    assert "Wavelength 1 is used by 2 routes on link B->C" in msgs
    s = Solution(objective=99)
    s.add_route(0, ["A", "B", "C"], 2, wavelengths=[0, 7])  # 7 >= capacity 4
    s.add_route(1, ["B", "C"], 1)                            # no wavelengths
    issues = _issues(s, D, wavelength_continuity=True)
    msgs = " ".join(i.message for i in issues)
    assert "wavelength 7 does not exist" in msgs and "no wavelengths assigned" in msgs
    assert any(i.severity == "warning" and "objective" in i.message for i in issues)
    s = Solution()
    s.add_route(0, ["A", "B", "C"], 2, wavelengths=[0])
    assert "lists 1 wavelength" in " ".join(i.message for i in _issues(s, D[:1]))


def test_fractional_warning():
    D = [Demand(0, "A", "C", 3)]
    s = Solution()
    s.add_route(0, ["A", "B", "C"], 1.5)
    s.add_route(0, ["A", "D", "C"], 1.5)
    issues = _issues(s, D)
    assert not has_errors(issues)
    assert any("fractional" in i.message for i in issues)
